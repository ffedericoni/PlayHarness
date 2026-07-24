"""BGAEnv: a live BoardGameArena table as a Phase 3 :class:`~playharness.env.Environment`.

Where :class:`~playharness.bga.adapter.BGAAdapter` (Phase 2) carried its own
world model and ran a self-contained observe / predict / commit loop, ``BGAEnv``
is *pure reality*: it observes the table, commits the agent's action through the
UI map, and reports what changed. Crucially it holds **no model** — the agent's
own move is reported named (the loop chose it), but the opponent's move comes
back only as a raw board observation. Reconstructing the opponent's action from
that board is now the deliberation loop's job (:mod:`playharness.agent`), so on
BGA the same falsifiable loop that plans also names reality.

Drop it into :func:`playharness.agent.play_game` in place of ``ReferenceEnv`` to
drive a real table with the full Schema loop — certify, plan, check every
prediction, repair from counterexamples.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from ..backtest import diff_paths
from ..env import IllegalActionError, TransitionEvent
from . import observe as obs_mod
from .ui_map import UIMap

logger = logging.getLogger(__name__)

Observation = dict[str, Any]
Action = dict[str, Any]

# Interface knowledge: the action wire format, declared to the theorizer up
# front. Rejections reveal nothing, so a wrong encoding could never be repaired
# from live play — but on BGA the UI map fixes the encoding and the table
# visibly offers the opening moves, so declaring it is observation, not leaked
# rules (preconditions/effects are still learned from recorded play).
ACTION_SPECS = {
    "reversi": (
        "Actions are committed to the interface as JSON dicts "
        '{"type": "place", "cell": N}, where N is the 0-based flat index '
        "(row-major, row*8 + col) of the cell to place a disc on. The table "
        "offers the legal opening placements before the first move; the "
        "encoding is fixed by the interface."
    ),
}


def project(observation: Observation) -> dict:
    """The model-facing slice of an observation — exactly what
    ``model.observation(state, None)`` returns, so it is directly comparable."""
    return {"board": observation["board"], "to_move": observation["to_move"]}


class BGAEnv:
    def __init__(self, page, game: str, ui_map: UIMap, screenshots_dir: str | Path,
                 *, spec: str | None = None, act_timeout_s: float = 30.0,
                 poll_s: float = 1.5, move_timeout_s: float = 600.0):
        self.page = page
        self.game = game
        self.ui_map = ui_map
        self.screenshots_dir = Path(screenshots_dir)
        self.spec = spec or ACTION_SPECS.get(
            game, "Actions are committed to the interface as JSON dicts.")
        self.act_timeout_s = act_timeout_s
        self.poll_s = poll_s
        self.move_timeout_s = move_timeout_s
        self.agent_seat: int | None = None
        self._last: Observation | None = None

    # -- Environment interface ------------------------------------------------

    def action_spec(self) -> str:
        return self.spec

    def reset(self) -> tuple[dict, dict, list[TransitionEvent]]:
        observation = self.observe(reload=True)
        seat = observation.get("viewer_player")
        if seat is None:
            raise RuntimeError("cannot determine the agent's seat from the table")
        self.agent_seat = seat
        events = self._advance_to_our_turn(observation)
        return {}, project(observation), events

    def act(self, action: Action) -> list[TransitionEvent]:
        if self.agent_seat is None:
            raise RuntimeError("act() before reset()")
        observation = self._last or self.observe(reload=True)
        if observation["game_over"]:
            raise IllegalActionError("the game is over")
        if observation["to_move"] != self.agent_seat:
            raise IllegalActionError("it is not your turn")

        before = project(observation)
        self._execute(action)
        # `after` is the first change we observe: usually just our move, but the
        # opponent may already have replied — the loop's reconciliation names
        # whatever extra happened, so we report the board as our own (named)
        # move and let inference sort out any collapsed reply.
        after = self._wait_for_change(before)
        events = [TransitionEvent(project(after), player=self.agent_seat, action=action)]
        events += self._advance_to_our_turn(after)
        return events

    def is_terminal(self) -> bool:
        observation = self._last or self.observe(reload=True)
        return bool(observation["game_over"])

    def scores(self) -> dict[int, float]:
        observation = self._last or self.observe(reload=True)
        if not observation["game_over"]:
            raise RuntimeError("scores() before the game is over")
        final = observation.get("final_scores") or {}
        return {int(k): float(v) for k, v in final.items()}

    # -- observation ----------------------------------------------------------

    def observe(self, reload: bool = True, screenshot: bool = False) -> Observation:
        """Authoritative observation of the table; screenshot on request or failure."""
        try:
            raw = obs_mod.snapshot(self.page, reload=reload)
            observation = obs_mod.normalize(self.game, raw)
        except Exception:
            try:
                path = obs_mod.save_screenshot(self.page, self.screenshots_dir, "obs_error")
                logger.warning("observation failed; screenshot %s", path)
            except Exception:
                logger.exception("screenshot fallback also failed")
            raise
        if screenshot:
            observation["screenshot"] = obs_mod.save_screenshot(
                self.page, self.screenshots_dir, "obs")
        self._last = observation
        return observation

    # -- internals ------------------------------------------------------------

    def _advance_to_our_turn(self, observation: Observation) -> list[TransitionEvent]:
        """Poll until it is our turn or the game ends, returning the resulting
        board as a single raw observation (empty if nothing changed)."""
        start = project(observation)
        deadline = time.monotonic() + self.move_timeout_s
        while not (observation["game_over"]
                   or observation["to_move"] == self.agent_seat):
            if time.monotonic() > deadline:
                raise TimeoutError(f"still not our turn after {self.move_timeout_s:.0f}s")
            time.sleep(self.poll_s)
            observation = self.observe(reload=True)
        current = project(observation)
        return [] if current == start else [TransitionEvent(current)]

    def _execute(self, action: Action) -> None:
        extra_vars = obs_mod.action_ui_vars(self.game, action)
        selector, method = self.ui_map.selector_for(action, extra_vars)
        element = self.page.locator(selector).first
        if method == "click":
            element.click(timeout=int(self.act_timeout_s * 1000))
        else:
            raise IllegalActionError(f"unsupported UI method {method!r} for {action}")
        for confirm_selector in self.ui_map.confirm_selectors():
            try:
                confirm = self.page.locator(confirm_selector).first
                if confirm.is_visible():
                    confirm.click()
            except Exception:
                continue

    def _wait_for_change(self, before: dict) -> Observation:
        """Wait until the table state visibly changed. A move reality never
        applies is a rejection — reported as :class:`IllegalActionError`, which
        the loop feeds to repair (the model's precondition/encoding was wrong)."""
        deadline = time.monotonic() + self.act_timeout_s
        while True:
            time.sleep(self.poll_s)
            observation = self.observe(reload=True)
            if diff_paths(before, project(observation)) or observation["game_over"]:
                return observation
            if time.monotonic() > deadline:
                raise IllegalActionError(
                    f"table state unchanged {self.act_timeout_s:.0f}s after action")
