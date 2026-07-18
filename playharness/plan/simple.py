"""Alpha-beta search over a world model, for deterministic perfect-information games.

Planning happens entirely inside the model — it costs zero real actions. Only
the move returned by ``choose_action`` is ever committed to BGA. The full
planner portfolio (expectimax, determinized MCTS) arrives in Phase 4; this
module covers the Phase 2 target game, Reversi.
"""

from __future__ import annotations

import random
from types import ModuleType
from typing import Any

State = dict[str, Any]
Action = dict[str, Any]

WIN = 100_000.0
CORNERS = [(1, 1), (1, 8), (8, 1), (8, 8)]


def _evaluate(model: ModuleType, state: State, player: str) -> float:
    """Heuristic value of ``state`` for ``player``: discs + corners + mobility."""
    opponent = "white" if player == "black" else "black"
    if model.is_terminal(state):
        diff = model.score(state, player) - model.score(state, opponent)
        return WIN * (1 if diff > 0 else -1 if diff < 0 else 0) + diff

    value = model.score(state, player) - model.score(state, opponent)
    board = state["board"]
    mine, theirs = 1 if player == "black" else 2, 1 if opponent == "black" else 2
    for x, y in CORNERS:
        cell = board[y - 1][x - 1]
        if cell == mine:
            value += 25.0
        elif cell == theirs:
            value -= 25.0
    to_move = state["to_move"]
    mobility = len(model.legal_actions(state, to_move))
    value += 2.0 * (mobility if to_move == player else -mobility)
    return value


def _search(model: ModuleType, state: State, player: str, depth: int, alpha: float, beta: float) -> float:
    if depth <= 0 or model.is_terminal(state):
        return _evaluate(model, state, player)
    to_move = state["to_move"]
    actions = model.legal_actions(state, to_move)
    maximizing = to_move == player
    best = -float("inf") if maximizing else float("inf")
    for action in actions:
        value = _search(model, model.step(state, action), player, depth - 1, alpha, beta)
        if maximizing:
            best = max(best, value)
            alpha = max(alpha, best)
        else:
            best = min(best, value)
            beta = min(beta, best)
        if beta <= alpha:
            break
    return best


def choose_action(
    model: ModuleType,
    state: State,
    player: str,
    depth: int = 3,
    rng: random.Random | None = None,
) -> Action | None:
    """Best action for ``player`` (who must be to move), or None if no legal action."""
    actions = model.legal_actions(state, player)
    if not actions:
        return None
    rng = rng or random.Random()
    rng.shuffle(actions)  # random tie-breaking
    best_action, best_value = actions[0], -float("inf")
    for action in actions:
        value = _search(model, model.step(state, action), player, depth - 1, -float("inf"), float("inf"))
        if value > best_value:
            best_action, best_value = action, value
    return best_action


def random_action(model: ModuleType, state: State, player: str, rng: random.Random | None = None) -> Action | None:
    """Uniform-random baseline player."""
    actions = model.legal_actions(state, player)
    return (rng or random.Random()).choice(actions) if actions else None
