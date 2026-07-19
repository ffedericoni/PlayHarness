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


INFINITY = float("inf")


def alphabeta_value(model: WorldModel, state: dict, player: int, depth: int,
                    heuristic: Callable[[WorldModel, dict, int], float] | None = None,
                    alpha: float = -INFINITY, beta: float = INFINITY) -> float:
    """Depth-limited alpha-beta value of ``state`` from ``player``'s viewpoint.

    For games too large for exhaustive search. ``heuristic`` evaluates
    non-terminal cutoff states; the default reuses ``model.score`` (fine for
    games where the score is a meaningful running measure, e.g. disc
    differential in Reversi). Handles turn skips (same player moving twice).
    """
    if model.is_terminal(state):
        # Scale so real outcomes always dominate heuristic estimates.
        return model.score(state, player) * 1_000_000.0
    if depth <= 0:
        return (heuristic or (lambda m, s, p: m.score(s, p)))(model, state, player)

    mover = state["to_move"]
    maximizing = mover == player
    best = -INFINITY if maximizing else INFINITY
    for action in model.legal_actions(state, mover):
        value = alphabeta_value(model, model.step(state, action), player,
                                depth - 1, heuristic, alpha, beta)
        if maximizing:
            best = max(best, value)
            alpha = max(alpha, best)
        else:
            best = min(best, value)
            beta = min(beta, best)
        if beta <= alpha:
            break
    return best


def alphabeta_policy(depth: int,
                     heuristic: Callable[[WorldModel, dict, int], float] | None = None) -> Policy:
    """Build a policy that picks the best action by depth-limited alpha-beta."""

    def policy(model: WorldModel, state: dict, player: int) -> dict:
        actions = model.legal_actions(state, player)
        if not actions:
            raise ValueError(f"player {player} has no legal actions")
        return max(actions, key=lambda a: alphabeta_value(
            model, model.step(state, a), player, depth - 1, heuristic))

    return policy
