"""BGAAdapter: observe + act + record against a live table, with per-step
prediction checks.

This is the harness's only channel between thinking and reality:

- ``observe()`` returns a normalized Observation and can snapshot a screenshot.
- ``commit_action(action)`` predicts the outcome with the world model, executes
  the action through the UI map, waits for BGA to apply it, re-observes, and
  compares. **Any misprediction halts the plan**: the transition is recorded to
  the Timeline either way (reality is ground truth), then ``PredictionMismatch``
  is raised so control returns to deliberation with the counterexample.
- Every transition and every observation-relevant event is appended to the
  per-game Timeline (append-only JSONL).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from types import ModuleType

from ..timeline import Timeline
from ..types import (
    Action,
    Observation,
    PredictionMismatch,
    compare_observations,
    state_from_observation,
)
from . import observe as obs_mod
from .ui_map import UIMap

logger = logging.getLogger(__name__)


class ActionRejected(Exception):
    """BGA visibly refused the action (error toast / no state change)."""


class BGAAdapter:
    def __init__(
        self,
        page,
        game: str,
        model: ModuleType,
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
        self._last_obs: Observation | None = None

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
                self.timeline.append({"type": "observe_error", "screenshot": path})
            except Exception:
                logger.exception("screenshot fallback also failed")
            raise
        if screenshot:
            observation["screenshot"] = obs_mod.save_screenshot(
                self.page, self.screenshots_dir, "obs"
            )
        self._last_obs = observation
        return observation

    def wait_for_turn(self, timeout_s: float = 600.0) -> Observation:
        """Poll until it is the viewer's turn or the game is over."""
        deadline = time.monotonic() + timeout_s
        while True:
            observation = self.observe(reload=True)
            if observation["game_over"] or (
                observation["to_move"] is not None
                and observation["to_move"] == observation["viewer_color"]
            ):
                return observation
            if time.monotonic() > deadline:
                raise TimeoutError(f"still not our turn after {timeout_s:.0f}s")
            time.sleep(self.poll_s)

    # -- act -----------------------------------------------------------------

    def _execute(self, action: Action) -> None:
        selector, method = self.ui_map.selector_for(action)
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

    def _wait_for_effect(self, obs_before: Observation) -> Observation:
        """Wait until the table state visibly changed, then return the new observation."""
        deadline = time.monotonic() + self.act_timeout_s
        while True:
            time.sleep(self.poll_s)
            observation = self.observe(reload=True)
            changed = (
                observation["board"] != obs_before["board"]
                or observation["to_move"] != obs_before["to_move"]
                or observation["game_over"] != obs_before["game_over"]
            )
            if changed:
                return observation
            if time.monotonic() > deadline:
                raise ActionRejected(
                    f"table state unchanged {self.act_timeout_s:.0f}s after action"
                )

    def commit_action(self, action: Action, obs_before: Observation | None = None) -> Observation:
        """Predict, execute, re-observe, compare, record. The Schema per-step check.

        Returns the post-action observation on a green check. On divergence the
        transition (with the counterexample) is still recorded, then
        ``PredictionMismatch`` is raised — the caller must void its plan.
        """
        if obs_before is None:
            obs_before = self._last_obs or self.observe(reload=True)

        state = state_from_observation(obs_before)
        predicted = self.model.step(state, action)

        self._execute(action)
        obs_after = self._wait_for_effect(obs_before)

        mismatches = compare_observations(predicted, obs_after)
        self.timeline.append(
            {
                "type": "transition",
                "game": self.game,
                "table_id": obs_after.get("table_id"),
                "obs_before": _strip_logs(obs_before),
                "action": action,
                "obs_after": _strip_logs(obs_after),
                "predicted": predicted,
                "match": not mismatches,
                "mismatches": mismatches,
                "new_logs": _new_log_entries(obs_before, obs_after),
            }
        )
        if mismatches:
            screenshot = obs_mod.save_screenshot(self.page, self.screenshots_dir, "mismatch")
            logger.warning("prediction mismatch (screenshot %s): %s", screenshot, mismatches)
            raise PredictionMismatch(action, mismatches, predicted, obs_after)
        return obs_after


def _strip_logs(observation: Observation) -> Observation:
    return {k: v for k, v in observation.items() if k != "logs"}


def _new_log_entries(obs_before: Observation, obs_after: Observation) -> list[str]:
    """Game-log lines that appeared during the transition (BGA prepends new entries)."""
    before, after = obs_before.get("logs") or [], obs_after.get("logs") or []
    if not before:
        return after
    for i in range(len(after)):
        if after[i:i + len(before)] == before[: len(after) - i]:
            return after[:i]
    return after
