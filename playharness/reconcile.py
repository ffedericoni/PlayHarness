"""Naming observed reality by inference — the model reconstructs opponent moves.

On BoardGameArena the harness only ever observes the *resulting board*, never
the opponent's action in the model's encoding. Reconstructing what happened
therefore requires the model, and in Phase 3 that model is the very thing under
test. So opponent-move reconstruction is lifted *into* the deliberation loop:
the environment hands back raw observations and the loop names the transitions
with the model it holds — putting every use of the model, including
reconstructing reality, under the same falsifiable check.

``infer_action_path`` searches for the legal action sequence that turns one
state into an observed target board. A successful inference *is* a certification
of those transitions (the model guaranteed their legality); a failure is a
counterexample the model cannot explain.
"""

from __future__ import annotations

from collections import deque
from typing import Any

Observation = dict[str, Any]
Action = dict[str, Any]


def infer_action_path(model, state: dict, target: Observation, max_moves: int = 4):
    """Legal action sequence from ``state`` to an observed ``target`` board.

    Returns ``[(player, action, next_state), ...]`` (an empty list if the state
    already matches the target) or ``None`` if no sequence of at most
    ``max_moves`` legal actions reproduces the target. Comparison is in
    observation space, so ``target`` is exactly what
    ``model.observation(state, None)`` returns.

    Used to reconstruct the opponent moves (and any auto-skip chain) that
    happened between two of our observations — the model guarantees legality, so
    a successful inference certifies those transitions.

    The pruning assumes pieces are only ever *added* to the board (Reversi /
    Othello, tic-tac-toe): a branch with a piece where the target is empty, or
    with more pieces than the target, cannot lead to it. That holds for every
    game the harness currently learns; a game that removes pieces would need the
    prune relaxed (at worst inference falls back to reporting a counterexample).
    """
    target_board = target["board"]
    target_to_move = target.get("to_move")
    occupied_target = sum(1 for v in target_board if v is not None)

    queue: deque[tuple[dict, list]] = deque([(state, [])])
    while queue:
        current, path = queue.popleft()
        current_obs = model.observation(current, None)
        board = current_obs["board"]
        if board == target_board and current_obs.get("to_move") == target_to_move:
            return path
        if len(path) >= max_moves or current_obs.get("to_move") is None:
            continue
        # discs are only added: prune branches that overshot or diverged
        if sum(1 for v in board if v is not None) > occupied_target:
            continue
        if any(t is None and c is not None for c, t in zip(board, target_board)):
            continue
        mover = current_obs["to_move"]
        for action in model.legal_actions(current, mover):
            try:
                next_state = model.step(current, action)
            except Exception:
                # A model that offers an action its own step() rejects is buggy,
                # but that is not a valid branch — skip it rather than abort the
                # whole reconstruction (the bug surfaces via live rejection when
                # the planner tries to commit such an action for real).
                continue
            queue.append((next_state, path + [(mover, action, next_state)]))
    return None
