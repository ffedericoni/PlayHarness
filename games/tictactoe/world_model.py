"""Tic-tac-toe world model — hand-written reference implementation.

Validates the Phase 0 harness interfaces (Timeline, backtest, sandbox,
planner) without any Claude calls. Player 0 is "X" and moves first;
player 1 is "O". Cells are indexed 0-8, row-major.
"""

MARKS = {0: "X", 1: "O"}

LINES = (
    (0, 1, 2), (3, 4, 5), (6, 7, 8),  # rows
    (0, 3, 6), (1, 4, 7), (2, 5, 8),  # columns
    (0, 4, 8), (2, 4, 6),             # diagonals
)


def _winner(board):
    for a, b, c in LINES:
        if board[a] is not None and board[a] == board[b] == board[c]:
            return board[a]
    return None


def initial_state(config):
    return {"board": [None] * 9, "to_move": 0}


def legal_actions(state, player):
    if state["to_move"] != player:
        return []
    return [{"type": "place", "cell": i}
            for i, mark in enumerate(state["board"]) if mark is None]


def step(state, action):
    player = state["to_move"]
    if player is None:
        raise ValueError("game is over")
    if action.get("type") != "place":
        raise ValueError(f"unknown action type: {action!r}")
    cell = action.get("cell")
    if not isinstance(cell, int) or not 0 <= cell <= 8:
        raise ValueError(f"cell must be an int in 0..8, got {cell!r}")
    if state["board"][cell] is not None:
        raise ValueError(f"cell {cell} is already occupied")

    board = list(state["board"])
    board[cell] = MARKS[player]
    game_over = _winner(board) is not None or all(m is not None for m in board)
    return {"board": board, "to_move": None if game_over else 1 - player}


def is_terminal(state):
    return _winner(state["board"]) is not None or all(m is not None for m in state["board"])


def score(state, player):
    winner = _winner(state["board"])
    if winner is None:
        return 0.0
    return 1.0 if winner == MARKS[player] else -1.0


def observation(state, player):
    # Perfect information: every observer sees the full state.
    return {"board": list(state["board"]), "to_move": state["to_move"]}
