"""Executable world model for Reversi (Othello), as played on BoardGameArena.

Hand-written for Phase 2 to validate the harness interfaces; from Phase 3 on,
this file is owned by the agent and repaired against the Timeline whenever the
backtest or a per-step prediction check produces a counterexample.

Conventions (matching BGA's Reversi implementation):
- Board is 8x8, coordinates are 1-indexed with x = column, y = row, so cell
  (x, y) lives at ``board[y-1][x-1]``.
- Cell values: 0 empty, 1 black disc, 2 white disc.
- Black moves first. Initial center: white on (4,4) and (5,5), black on
  (5,4) and (4,5).
- A player with no legal placement is skipped automatically (BGA does this
  server-side; there is no explicit pass action). When neither player can
  move the game is over and ``to_move`` is None.
"""

from __future__ import annotations

import copy
from typing import Any

State = dict[str, Any]
Action = dict[str, Any]

SIZE = 8
EMPTY = 0
BLACK = "black"
WHITE = "white"
DISC = {BLACK: 1, WHITE: 2}
OPPONENT = {BLACK: WHITE, WHITE: BLACK}
DIRECTIONS = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]


class IllegalAction(Exception):
    pass


def initial_state(config: dict | None = None) -> State:
    board = [[EMPTY] * SIZE for _ in range(SIZE)]
    board[3][3] = DISC[WHITE]  # (4,4)
    board[4][4] = DISC[WHITE]  # (5,5)
    board[3][4] = DISC[BLACK]  # (5,4)
    board[4][3] = DISC[BLACK]  # (4,5)
    return {"board": board, "to_move": BLACK}


def _captures(board: list[list[int]], x: int, y: int, player: str) -> list[tuple[int, int]]:
    """All opponent discs flipped by ``player`` placing at (x, y); empty if illegal."""
    if not (1 <= x <= SIZE and 1 <= y <= SIZE) or board[y - 1][x - 1] != EMPTY:
        return []
    mine, theirs = DISC[player], DISC[OPPONENT[player]]
    flipped: list[tuple[int, int]] = []
    for dx, dy in DIRECTIONS:
        line: list[tuple[int, int]] = []
        cx, cy = x + dx, y + dy
        while 1 <= cx <= SIZE and 1 <= cy <= SIZE and board[cy - 1][cx - 1] == theirs:
            line.append((cx, cy))
            cx, cy = cx + dx, cy + dy
        if line and 1 <= cx <= SIZE and 1 <= cy <= SIZE and board[cy - 1][cx - 1] == mine:
            flipped.extend(line)
    return flipped


def _has_move(board: list[list[int]], player: str) -> bool:
    return any(
        _captures(board, x, y, player)
        for y in range(1, SIZE + 1)
        for x in range(1, SIZE + 1)
    )


def legal_actions(state: State, player: str) -> list[Action]:
    if state["to_move"] != player:
        return []
    board = state["board"]
    return [
        {"type": "play_disc", "x": x, "y": y}
        for y in range(1, SIZE + 1)
        for x in range(1, SIZE + 1)
        if _captures(board, x, y, player)
    ]


def step(state: State, action: Action) -> State:
    player = state["to_move"]
    if player is None:
        raise IllegalAction("game is over")
    if action.get("type") != "play_disc":
        raise IllegalAction(f"unknown action type: {action.get('type')!r}")
    x, y = action["x"], action["y"]
    board = copy.deepcopy(state["board"])
    flipped = _captures(board, x, y, player)
    if not flipped:
        raise IllegalAction(f"{player} cannot play at ({x},{y})")
    board[y - 1][x - 1] = DISC[player]
    for fx, fy in flipped:
        board[fy - 1][fx - 1] = DISC[player]

    opponent = OPPONENT[player]
    if _has_move(board, opponent):
        to_move = opponent
    elif _has_move(board, player):
        to_move = player  # opponent skipped
    else:
        to_move = None  # neither side can move: game over
    return {"board": board, "to_move": to_move}


def is_terminal(state: State) -> bool:
    return state["to_move"] is None


def score(state: State, player: str) -> float:
    disc = DISC[player]
    return float(sum(cell == disc for row in state["board"] for cell in row))


def observation(state: State, player: str) -> State:
    """Reversi is perfect-information: every player observes the full state."""
    return copy.deepcopy(state)
