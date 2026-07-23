"""BGAAdapter: observe + act + record against a live table, with per-step
prediction checks.

This is the harness's only channel between thinking and reality:

- ``observe()`` returns a normalized Observation (see :mod:`.observe`).
- ``sync()`` reconciles the live table with the tracked model state, inferring
  and recording the opponent's transitions (the model searches for the legal
  action sequence that explains the observed board).
- ``commit_action(action)`` predicts the outcome with the world model,
  executes the action through the UI map, waits for BGA to apply it,
  re-observes, and compares. **Any unexplainable divergence halts the plan**:
  the counterexample is recorded to the Timeline, then ``PredictionMismatch``
  is raised so control returns to deliberation.

The Timeline is written in exactly the entry format the backtest replays
(``init`` / ``transition`` / ``log`` / ``result`` — see
:mod:`playharness.timeline`), so a recorded BGA game certifies the world model
with ``run_backtest`` unchanged. Transitions the harness inferred rather than
directly observed carry ``"inferred": True``; the final observation of every
inferred chain is genuinely observed.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from pathlib import Path
from typing import Any

from ..backtest import diff_paths
from ..model_api import WorldModel
from ..timeline import Timeline
from . import observe as obs_mod
from .ui_map import UIMap

logger = logging.getLogger(__name__)

Observation = dict[str, Any]
Action = dict[str, Any]


class PredictionMismatch(Exception):
    """The observed table state cannot be explained by the world model.

    Reality outranks the model: whoever catches this must void the current
    plan and return to deliberation with the counterexample.
    """

    def __init__(self, action: Action | None, paths: list[str], predicted: Any, actual: Any):
        self.action = action
        self.mismatched_paths = paths
        self.predicted = predicted
        self.actual = actual
        super().__init__(
            f"model prediction diverged from BGA after {action}: mismatch at "
            + (", ".join(paths) or "<unexplainable transition>")
        )


class ActionRejected(Exception):
    """BGA visibly refused the action (error toast / no state change)."""


def project(observation: Observation) -> dict:
    """The model-facing slice of an observation (what the backtest compares)."""
    return {"board": observation["board"], "to_move": observation["to_move"]}


def infer_action_path(
    model: WorldModel, state: dict, target: dict, max_moves: int = 4
) -> list[tuple[int, Action, dict]] | None:
    """Search for the legal action sequence leading from ``state`` to ``target``.

    Returns ``[(player, action, next_state), ...]`` or None if no sequence of
    at most ``max_moves`` legal actions reproduces the target observation.
    Used to reconstruct opponent moves (and auto-skip chains) that happened
    between two of our observations — the model guarantees legality, so a
    successful inference is itself a certification of those transitions.
    """
    target_board, target_to_move = target["board"], target["to_move"]
    occupied_target = sum(1 for v in target_board if v is not None)

    queue: deque[tuple[dict, list]] = deque([(state, [])])
    while queue:
        current, path = queue.popleft()
        if current["board"] == target_board and current["to_move"] == target_to_move:
            return path
        if len(path) >= max_moves or current["to_move"] is None:
            continue
        board = current["board"]
        # Discs are only ever added in Reversi-like games; prune impossible branches.
        if sum(1 for v in board if v is not None) > occupied_target:
            continue
        if any(t is None and c is not None for c, t in zip(board, target_board)):
            continue
        mover = current["to_move"]
        for action in model.legal_actions(current, mover):
            next_state = model.step(current, action)
            queue.append((next_state, path + [(mover, action, next_state)]))
    return None


class BGAAdapter:
    def __init__(
        self,
        page,
        game: str,
        model: WorldModel,
        ui_map: UIMap,
        timeline: Timeline,
        screenshots_dir: str | Path,
        act_timeout_s: float = 30.0,
        poll_s: float = 1.5,
    ):
        self.page = page
        self.game = game
        self.model = model
        self.ui_map = ui_map
        self.timeline = timeline
        self.screenshots_dir = Path(screenshots_dir)
        self.act_timeout_s = act_timeout_s
        self.poll_s = poll_s
        self.state: dict | None = None  # tracked model state, kept in sync with the Timeline
        self._seen_logs: list[str] = []
        self._result_recorded = False

    # -- observe -------------------------------------------------------------

    def observe(self, reload: bool = True, screenshot: bool = False) -> Observation:
        """Authoritative observation of the table. Screenshot on request or on failure."""
        try:
            raw = obs_mod.snapshot(self.page, reload=reload)
            observation = obs_mod.normalize(self.game, raw)
        except Exception:
            # Structured path failed: keep a screenshot as the vision fallback
            # and record the failure before propagating.
            try:
                path = obs_mod.save_screenshot(self.page, self.screenshots_dir, "obs_error")
                self.timeline.append("log", source="harness",
                                     raw=f"observation failed; screenshot {path}")
            except Exception:
                logger.exception("screenshot fallback also failed")
            raise
        if screenshot:
            observation["screenshot"] = obs_mod.save_screenshot(
                self.page, self.screenshots_dir, "obs"
            )
        return observation

    # -- record --------------------------------------------------------------

    def _record_new_logs(self, observation: Observation) -> None:
        """Append BGA game-log lines we haven't seen yet (BGA prepends new entries)."""
        current = observation.get("logs") or []
        new_lines = _lines_added(self._seen_logs, current)
        for line in reversed(new_lines):  # oldest first in the Timeline
            self.timeline.append("log", source="bga", raw=line)
        self._seen_logs = current

    def sync(self, observation: Observation | None = None) -> Observation:
        """Reconcile the tracked model state with the live table, recording
        any transitions (opponent moves, auto-skips) that happened meanwhile.

        Raises ``PredictionMismatch`` if no legal action sequence explains the
        observed state.
        """
        observation = observation or self.observe(reload=True)
        target = project(observation)

        if self.state is None:
            initial = self.model.initial_state({})
            initial_obs = self.model.observation(initial, None)
            if diff_paths(initial_obs, target):
                # Joined mid-game: no init entry — such a timeline is not
                # backtestable from the start, which the record makes explicit.
                self.timeline.append("log", source="harness",
                                     raw="joined mid-game; timeline has no init entry",
                                     observation=target)
                self.state = target
            else:
                self.timeline.append("init", config={}, observation=initial_obs)
                self.state = initial
            self._record_new_logs(observation)
            return observation

        current_obs = self.model.observation(self.state, None)
        if not diff_paths(current_obs, target):
            self._record_new_logs(observation)
            return observation

        path = infer_action_path(self.model, self.state, target)
        if path is None:
            self._halt(None, current_obs, target, observation)
        for mover, action, next_state in path:
            final = next_state is path[-1][2]
            self.timeline.append(
                "transition", player=mover, action=action,
                observation=target if final else self.model.observation(next_state, None),
                inferred=True,
            )
        self.state = path[-1][2]
        self._record_new_logs(observation)
        self._maybe_record_result(observation)
        return observation

    def _maybe_record_result(self, observation: Observation) -> None:
        if observation["game_over"] and observation.get("final_scores") and not self._result_recorded:
            self.timeline.append("result", scores=observation["final_scores"],
                                 bga_scores=observation.get("scores_raw"))
            self._result_recorded = True

    def _halt(self, action: Action | None, predicted: Any, actual: Any,
              observation: Observation) -> None:
        """Record the counterexample, screenshot the table, raise PredictionMismatch."""
        paths = diff_paths(predicted, actual)
        screenshot = obs_mod.save_screenshot(self.page, self.screenshots_dir, "mismatch")
        self.timeline.append(
            "log", source="harness", raw="prediction mismatch — plan voided",
            action=action, predicted=predicted, observed=actual,
            mismatched_paths=paths, screenshot=screenshot,
        )
        logger.warning("prediction mismatch (screenshot %s): %s", screenshot, paths)
        raise PredictionMismatch(action, paths, predicted, actual)

    # -- wait ----------------------------------------------------------------

    def wait_for_turn(self, timeout_s: float = 600.0) -> Observation:
        """Poll (and sync) until it is the viewer's turn or the game is over."""
        deadline = time.monotonic() + timeout_s
        while True:
            observation = self.sync()
            if observation["game_over"] or (
                observation["to_move"] is not None
                and observation["to_move"] == observation["viewer_player"]
            ):
                return observation
            if time.monotonic() > deadline:
                raise TimeoutError(f"still not our turn after {timeout_s:.0f}s")
            time.sleep(self.poll_s)

    # -- act -----------------------------------------------------------------

    def _execute(self, action: Action) -> None:
        extra_vars = obs_mod.action_ui_vars(self.game, action)
        selector, method = self.ui_map.selector_for(action, extra_vars)
        element = self.page.locator(selector).first
        if method == "click":
            element.click(timeout=int(self.act_timeout_s * 1000))
        else:
            raise ActionRejected(f"unsupported UI method {method!r} for {action}")
        # Some games pop a confirmation dialog after the click.
        for confirm_selector in self.ui_map.confirm_selectors():
            try:
                confirm = self.page.locator(confirm_selector).first
                if confirm.is_visible():
                    confirm.click()
            except Exception:
                continue

    def _wait_for_effect(self, before: dict) -> Observation:
        """Wait until the table state visibly changed, then return the new observation."""
        deadline = time.monotonic() + self.act_timeout_s
        while True:
            time.sleep(self.poll_s)
            observation = self.observe(reload=True)
            if diff_paths(before, project(observation)) or observation["game_over"]:
                return observation
            if time.monotonic() > deadline:
                raise ActionRejected(
                    f"table state unchanged {self.act_timeout_s:.0f}s after action"
                )

    def commit_action(self, action: Action) -> Observation:
        """Predict, execute, re-observe, compare, record. The Schema per-step check.

        Call ``sync()`` (or ``wait_for_turn()``) first so ``self.state``
        matches the table. Returns the post-action observation on a green
        check. On divergence the counterexample is recorded, then
        ``PredictionMismatch`` is raised — the caller must void its plan.
        """
        if self.state is None:
            raise RuntimeError("commit_action before sync(): tracked state unknown")
        mover = self.state["to_move"]
        predicted = self.model.step(self.state, action)  # raises ValueError if illegal
        predicted_obs = self.model.observation(predicted, None)

        self._execute(action)
        observation = self._wait_for_effect(project(self.model.observation(self.state, None)))
        target = project(observation)

        if not diff_paths(predicted_obs, target):
            self.timeline.append("transition", player=mover, action=action, observation=target)
            self.state = predicted
        else:
            # The opponent may have replied within the polling window: our
            # prediction then holds for an intermediate state we never saw.
            path = infer_action_path(self.model, predicted, target)
            if path is None:
                self._halt(action, predicted_obs, target, observation)
            self.timeline.append("transition", player=mover, action=action,
                                 observation=predicted_obs, observation_inferred=True)
            for inferred_mover, inferred_action, next_state in path:
                final = next_state is path[-1][2]
                self.timeline.append(
                    "transition", player=inferred_mover, action=inferred_action,
                    observation=target if final else self.model.observation(next_state, None),
                    inferred=True,
                )
            self.state = path[-1][2] if path else predicted
        self._record_new_logs(observation)
        self._maybe_record_result(observation)
        return observation


def _lines_added(old: list[str], new: list[str]) -> list[str]:
    """Log lines that appeared since ``old`` (BGA prepends; old tail may be truncated)."""
    if not old:
        return list(new)
    for start in range(len(new)):
        remainder = new[start:]
        if remainder == old[: len(remainder)]:
            return new[:start]
    return list(new)
