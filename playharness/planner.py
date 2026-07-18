"""Planning inside the certified model — free in real-action terms.

Phase 0 ships the deterministic perfect-information member of the planned
portfolio: memoized minimax (negamax form) for two-player zero-sum games.
Expectimax and determinized MCTS come with the games that need them.
"""

from __future__ import annotations

import json
import random
from typing import Callable

from .model_api import WorldModel

Policy = Callable[[WorldModel, dict, int], dict]
"""(model, state, player) -> action"""


def _key(state: dict) -> str:
    return json.dumps(state, sort_keys=True)


def minimax_value(model: WorldModel, state: dict, player: int,
                  _memo: dict | None = None) -> float:
    """Exact game value of ``state`` from ``player``'s viewpoint.

    Assumes two-player zero-sum with a ``to_move`` key (see model_api).
    Exhaustive — only for small games or endgames; budgeted search arrives
    with the bigger games.
    """
    memo = _memo if _memo is not None else {}
    key = (_key(state), player)
    if key in memo:
        return memo[key]

    if model.is_terminal(state):
        value = model.score(state, player)
    else:
        mover = state["to_move"]
        values = (
            minimax_value(model, model.step(state, a), player, memo)
            for a in model.legal_actions(state, mover)
        )
        value = max(values) if mover == player else min(values)

    memo[key] = value
    return value


def minimax_policy(model: WorldModel, state: dict, player: int) -> dict:
    """Pick the action with the best exact game value (ties: first found)."""
    actions = model.legal_actions(state, player)
    if not actions:
        raise ValueError(f"player {player} has no legal actions")
    memo: dict = {}
    return max(actions, key=lambda a: minimax_value(model, model.step(state, a), player, memo))


def random_policy(model: WorldModel, state: dict, player: int,
                  rng: random.Random | None = None) -> dict:
    actions = model.legal_actions(state, player)
    if not actions:
        raise ValueError(f"player {player} has no legal actions")
    return (rng or random).choice(actions)
