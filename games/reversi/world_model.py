"""World model for Othello (Reversi).

State/observation format (JSON-serializable):
    {"board": [<64 entries, each "B" | "W" | null>], "to_move": <int | None>}

Player numbering:
    0 -> Black ("B"), moves first.
    1 -> White ("W").

Board indexing: flat list of 64 cells, index = row * 8 + col, row 0 = top
(rank 8 ... actually rank labelled 1 at top), col 0 = column 'a'.
The recorded initial position is:
    d4 = White (index 27), e4 = Black (index 28),
    d5 = Black (index 35), e5 = White (index 36).

Actions:
    {"cell": <int>, "type": "place"}   -- place a disc of the mover's colour.
    {"type": "pass"}                   -- forfeit turn (only when no placement is legal).

The mover is always ``state["to_move"]``; actions do not carry a player field.

Turn handling: after a move, the turn passes to the opponent only if the
opponent has at least one legal placement.  If the opponent has no legal move
they are skipped automatically and the turn returns to the mover.  If neither
player can move, the game is over (``to_move`` is None).  This matches the
recorded ground-truth encoding, in which a player who cannot move is skipped
directly rather than taking an explicit "pass" turn.
"""

import copy

# Eight directions: (drow, dcol)
_DIRECTIONS = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
)


def _color(player):
    """Colour string for a player index."""
    return "B" if player == 0 else "W"


def _flips_for(board, cell, color, opp):
    """Return the list of cell indices that would be flipped by placing
    a disc of ``color`` at ``cell`` on ``board`` (empty list if illegal)."""
    r, c = divmod(cell, 8)
    flips = []
    for dr, dc in _DIRECTIONS:
        line = []
        rr, cc = r + dr, c + dc
        while 0 <= rr < 8 and 0 <= cc < 8:
            idx = rr * 8 + cc
            v = board[idx]
            if v == opp:
                line.append(idx)
                rr += dr
                cc += dc
            elif v == color:
                # Closing bracket of our own colour: flip the run in between.
                if line:
                    flips.extend(line)
                break
            else:
                # Empty square: no bracket in this direction.
                break
    return flips


def _legal_cells(board, player):
    """Sorted list of cell indices where ``player`` may legally place."""
    color = _color(player)
    opp = _color(1 - player)
    result = []
    for i in range(64):
        if board[i] is None:
            if _flips_for(board, i, color, opp):
                result.append(i)
    return result


def _has_moves(board, player):
    color = _color(player)
    opp = _color(1 - player)
    for i in range(64):
        if board[i] is None and _flips_for(board, i, color, opp):
            return True
    return False


def _next_to_move(board, mover):
    """Compute the ``to_move`` value after an action taken by ``mover``.

    The turn passes to the opponent only if the opponent has a legal move.
    If the opponent cannot move, they are skipped and the turn returns to the
    mover (provided the mover can still move).  If neither player has any legal
    move the game is over and ``None`` is returned.
    """
    opponent = 1 - mover
    if _has_moves(board, opponent):
        return opponent
    if _has_moves(board, mover):
        return mover
    return None


def initial_state(config):
    """Build the starting Othello position. ``config`` is accepted but unused."""
    board = [None] * 64
    board[27] = "W"  # d4
    board[28] = "B"  # e4
    board[35] = "B"  # d5
    board[36] = "W"  # e5
    return {"board": board, "to_move": 0}


def legal_actions(state, player):
    """Actions ``player`` may take in ``state``."""
    to_move = state.get("to_move")
    if to_move is None:
        return []
    if player != to_move:
        return []
    board = state["board"]
    cells = _legal_cells(board, player)
    if cells:
        return [{"cell": c, "type": "place"} for c in cells]
    # With automatic skipping, ``to_move`` always points to a player who can
    # move (otherwise it would be the opponent or None).  Should we ever reach
    # a state where the mover has no placement but the game is not over, the
    # only legal action is to pass.
    return [{"type": "pass"}]


def step(state, action):
    """Apply ``action`` and return the successor state (no mutation)."""
    to_move = state.get("to_move")
    if to_move is None:
        raise ValueError("Game is over; no actions are legal.")

    board = state["board"]
    if not isinstance(action, dict):
        raise ValueError("Action must be a dict.")
    atype = action.get("type")

    new_board = list(board)

    if atype == "pass":
        # Legal only when the mover has no placement available.
        if _legal_cells(board, to_move):
            raise ValueError("Cannot pass: a legal placement exists.")
        # Board unchanged.

    elif atype == "place":
        cell = action.get("cell")
        if not isinstance(cell, int) or not (0 <= cell < 64):
            raise ValueError("Invalid cell index.")
        if board[cell] is not None:
            raise ValueError("Square is not empty.")
        color = _color(to_move)
        opp = _color(1 - to_move)
        flips = _flips_for(board, cell, color, opp)
        if not flips:
            raise ValueError("Illegal move: flips no opposing disc.")
        new_board[cell] = color
        for idx in flips:
            new_board[idx] = color

    else:
        raise ValueError("Unknown action type: %r" % (atype,))

    next_player = _next_to_move(new_board, to_move)
    return {"board": new_board, "to_move": next_player}


def is_terminal(state):
    """A state is terminal when no player can move (``to_move`` is None)."""
    return state.get("to_move") is None


def score(state, player):
    """Final result from ``player``'s viewpoint: the signed disc differential
    (own discs minus opponent's discs).  A positive value is a win margin, a
    negative value a loss margin, and zero a draw.  This matches the recorded
    ground-truth encoding, which reports the final disc margin rather than a
    normalized +1/-1/0 outcome."""
    board = state["board"]
    black = sum(1 for v in board if v == "B")
    white = sum(1 for v in board if v == "W")
    my = black if player == 0 else white
    opp = white if player == 0 else black
    return float(my - opp)


def observation(state, player):
    """Perfect-information game: everyone (and the omniscient observer) sees
    the full state."""
    return {"board": list(state["board"]), "to_move": state.get("to_move")}
