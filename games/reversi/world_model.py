"""World model for Othello (Reversi).

Board encoding: a flat list of 64 cells, index = (row-1)*8 + col, with
a1 at top-left (col a=0..h=7, row 1=0..8=7). Each cell is "B", "W", or null.
Player 0 = Black ("B"), Player 1 = White ("W"). Black moves first.

Passes are handled automatically inside step(): after a placement the next
player to move is the opponent if the opponent has a legal move, otherwise the
mover again (opponent forced-passed), otherwise the game is terminal. Thus a
non-terminal state's ``to_move`` player always has at least one legal action,
and passes are never emitted as explicit actions.
"""

import copy

BOARD_SIZE = 8
NUM_CELLS = BOARD_SIZE * BOARD_SIZE

# 8 directions as (drow, dcol)
_DIRECTIONS = [
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
]


def _color(player):
    return "B" if player == 0 else "W"


def _rc(cell):
    return divmod(cell, BOARD_SIZE)


def _in_bounds(r, c):
    return 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE


def _flips_for_move(board, cell, player):
    """Return the list of cells that would be flipped by placing player's disc
    on ``cell`` (evaluated against the pre-move board, standard semantics)."""
    if board[cell] is not None:
        return []
    me = _color(player)
    opp = _color(1 - player)
    r0, c0 = _rc(cell)
    flips = []
    for dr, dc in _DIRECTIONS:
        r, c = r0 + dr, c0 + dc
        line = []
        # first neighbour must be opponent
        while _in_bounds(r, c) and board[r * BOARD_SIZE + c] == opp:
            line.append(r * BOARD_SIZE + c)
            r += dr
            c += dc
        # must be closed by own disc, with at least one opponent in between
        if line and _in_bounds(r, c) and board[r * BOARD_SIZE + c] == me:
            flips.extend(line)
    return flips


def _legal_cells(board, player):
    cells = []
    for cell in range(NUM_CELLS):
        if board[cell] is None and _flips_for_move(board, cell, player):
            cells.append(cell)
    return cells


def _next_to_move(board, mover):
    opp = 1 - mover
    if _legal_cells(board, opp):
        return opp
    if _legal_cells(board, mover):
        return mover  # opponent forced-passed
    return None  # neither can move: terminal


# ---------------------------------------------------------------------------
# Contract functions
# ---------------------------------------------------------------------------

def initial_state(config):
    board = [None] * NUM_CELLS
    # White on d4 (27) and e5 (36); Black on e4 (28) and d5 (35)
    board[27] = "W"
    board[28] = "B"
    board[35] = "B"
    board[36] = "W"
    return {"board": board, "to_move": 0}


def legal_actions(state, player):
    if state.get("to_move") is None:
        return []
    if player != state["to_move"]:
        return []
    board = state["board"]
    return [{"type": "place", "cell": c} for c in _legal_cells(board, player)]


def step(state, action):
    if state.get("to_move") is None:
        raise ValueError("Game is over; no actions allowed.")

    player = state["to_move"]

    if not isinstance(action, dict):
        raise ValueError("Action must be a dict.")
    if action.get("type") != "place":
        raise ValueError("Unsupported action type: %r" % (action.get("type"),))
    if "cell" not in action:
        raise ValueError("Place action requires a 'cell'.")

    cell = action["cell"]
    if not isinstance(cell, int) or not (0 <= cell < NUM_CELLS):
        raise ValueError("Invalid cell: %r" % (cell,))

    board = state["board"]
    flips = _flips_for_move(board, cell, player)
    if not flips:
        raise ValueError("Illegal move: no discs flipped at cell %d." % cell)

    new_board = list(board)
    me = _color(player)
    new_board[cell] = me
    for f in flips:
        new_board[f] = me

    nxt = _next_to_move(new_board, player)
    return {"board": new_board, "to_move": nxt}


def is_terminal(state):
    return state.get("to_move") is None


def score(state, player):
    board = state["board"]
    me = _color(player)
    opp = _color(1 - player)
    my_count = sum(1 for x in board if x == me)
    opp_count = sum(1 for x in board if x == opp)
    return float(my_count - opp_count)


def observation(state, player):
    # Perfect-information game: everyone (including omniscient None) sees all.
    return {"board": list(state["board"]), "to_move": state.get("to_move")}
