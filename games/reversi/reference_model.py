"""Reversi (Othello) reference model — hand-written, trusted.

Offline stand-in for BGA: ground-truth timelines are recorded from this
implementation, and the Claude-generated ``world_model.py`` is certified
against those recordings. The generator never sees this source — only the
rulebook, the RulesSpec, and recorded observations, exactly as it will only
see the rulebook and BGA's behavior in live play.

Conventions (these define the observation format the generated model must
reproduce):
- Board: 64-element row-major list, cells "B" / "W" / None. Cell index
  ``r * 8 + c``; a1 is index 0, h8 is index 63.
- Players: 0 = Black ("B", moves first), 1 = White ("W").
- Actions: {"type": "place", "cell": <0-63>} only. There is no pass action:
  if the player to move has no legal placement, the turn reverts to the
  opponent automatically; when neither side can place, the game ends.
"""

MARKS = {0: "B", 1: "W"}

DIRECTIONS = ((-1, -1), (-1, 0), (-1, 1),
              (0, -1),           (0, 1),
              (1, -1),  (1, 0),  (1, 1))


def _flips(board, cell, mark):
    """Cells that would be flipped by placing ``mark`` at ``cell`` (may be [])."""
    if board[cell] is not None:
        return []
    r, c = divmod(cell, 8)
    other = "W" if mark == "B" else "B"
    flips = []
    for dr, dc in DIRECTIONS:
        line = []
        rr, cc = r + dr, c + dc
        while 0 <= rr < 8 and 0 <= cc < 8 and board[rr * 8 + cc] == other:
            line.append(rr * 8 + cc)
            rr, cc = rr + dr, cc + dc
        if line and 0 <= rr < 8 and 0 <= cc < 8 and board[rr * 8 + cc] == mark:
            flips.extend(line)
    return flips


def _placements(board, mark):
    return [i for i in range(64) if _flips(board, i, mark)]


def initial_state(config):
    board = [None] * 64
    board[3 * 8 + 3] = "W"   # d4
    board[4 * 8 + 4] = "W"   # e5
    board[3 * 8 + 4] = "B"   # e4
    board[4 * 8 + 3] = "B"   # d5
    return {"board": board, "to_move": 0}


def legal_actions(state, player):
    if state["to_move"] != player:
        return []
    return [{"type": "place", "cell": i}
            for i in _placements(state["board"], MARKS[player])]


def step(state, action):
    player = state["to_move"]
    if player is None:
        raise ValueError("game is over")
    if action.get("type") != "place":
        raise ValueError(f"unknown action type: {action!r}")
    cell = action.get("cell")
    if not isinstance(cell, int) or not 0 <= cell <= 63:
        raise ValueError(f"cell must be an int in 0..63, got {cell!r}")

    mark = MARKS[player]
    flips = _flips(state["board"], cell, mark)
    if not flips:
        raise ValueError(f"cell {cell} is not a legal placement for {mark}")

    board = list(state["board"])
    board[cell] = mark
    for i in flips:
        board[i] = mark

    # Turn passes to the opponent; reverts if they cannot move; game ends
    # when neither side can.
    opponent = 1 - player
    if _placements(board, MARKS[opponent]):
        to_move = opponent
    elif _placements(board, mark):
        to_move = player
    else:
        to_move = None
    return {"board": board, "to_move": to_move}


def is_terminal(state):
    return state["to_move"] is None


def score(state, player):
    mine = state["board"].count(MARKS[player])
    theirs = state["board"].count(MARKS[1 - player])
    return float(mine - theirs)


def observation(state, player):
    # Perfect information: every observer sees the full state.
    return {"board": list(state["board"]), "to_move": state["to_move"]}
