"""Offline simulator mode: play a world model against itself.

Drives a full game with per-player policies and (optionally) records it to a
Timeline in exactly the format the BGA adapter will produce — so the backtest,
recorder, and planner interfaces are exercised without touching BGA.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model_api import WorldModel
from .planner import Policy
from .timeline import Timeline


@dataclass
class MatchResult:
    scores: dict[int, float]
    num_moves: int
    final_state: dict


def play_game(model: WorldModel, policies: dict[int, Policy],
              config: dict | None = None, timeline: Timeline | None = None,
              max_moves: int = 1000) -> MatchResult:
    """Play one game to termination. ``policies`` maps player id -> policy."""
    config = config or {}
    state = model.initial_state(config)
    if timeline is not None:
        timeline.append("init", config=config, observation=model.observation(state, None))

    moves = 0
    while not model.is_terminal(state):
        if moves >= max_moves:
            raise RuntimeError(f"game exceeded {max_moves} moves without terminating")
        player = state["to_move"]
        action = policies[player](model, state, player)
        state = model.step(state, action)
        moves += 1
        if timeline is not None:
            timeline.append("transition", player=player, action=action,
                            observation=model.observation(state, None))

    scores = {p: model.score(state, p) for p in policies}
    if timeline is not None:
        timeline.append("result", scores={str(p): s for p, s in scores.items()})
    return MatchResult(scores=scores, num_moves=moves, final_state=state)
