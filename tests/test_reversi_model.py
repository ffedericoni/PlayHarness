import random

import pytest

from playharness.model_api import load_model

model = load_model("reversi")


def test_initial_state():
    state = model.initial_state(None)
    board = state["board"]
    assert state["to_move"] == "black"
    assert sum(cell != 0 for row in board for cell in row) == 4
    assert board[3][3] == 2 and board[4][4] == 2  # white (4,4),(5,5)
    assert board[3][4] == 1 and board[4][3] == 1  # black (5,4),(4,5)


def test_initial_legal_actions():
    state = model.initial_state(None)
    moves = {(a["x"], a["y"]) for a in model.legal_actions(state, "black")}
    assert moves == {(3, 4), (4, 3), (5, 6), (6, 5)}
    assert model.legal_actions(state, "white") == []  # not white's turn


def test_step_flips_discs():
    state = model.initial_state(None)
    nxt = model.step(state, {"type": "play_disc", "x": 4, "y": 3})
    assert nxt["board"][2][3] == 1  # placed at (4,3)
    assert nxt["board"][3][3] == 1  # (4,4) flipped black
    assert nxt["to_move"] == "white"
    assert model.score(nxt, "black") == 4.0
    assert model.score(nxt, "white") == 1.0
    # original state untouched
    assert state["board"][3][3] == 2


def test_illegal_actions_raise():
    state = model.initial_state(None)
    with pytest.raises(Exception):
        model.step(state, {"type": "play_disc", "x": 1, "y": 1})  # no captures
    with pytest.raises(Exception):
        model.step(state, {"type": "play_disc", "x": 4, "y": 4})  # occupied
    with pytest.raises(Exception):
        model.step(state, {"type": "quux"})


def test_auto_skip_when_opponent_blocked():
    # Construct a position where white has no reply: black row capture leaves
    # white with zero legal moves, so black moves again.
    board = [[0] * 8 for _ in range(8)]
    board[0][0] = 1  # black (1,1)
    board[0][1] = 2  # white (2,1)
    state = {"board": board, "to_move": "black"}
    nxt = model.step(state, {"type": "play_disc", "x": 3, "y": 1})
    assert nxt["board"][0][1] == 1
    # white has no discs left at all -> no moves -> black plays again or game ends
    assert nxt["to_move"] in ("black", None)
    assert model.score(nxt, "white") == 0.0


def test_random_game_terminates_with_full_accounting():
    rng = random.Random(7)
    state = model.initial_state(None)
    for _ in range(200):
        if model.is_terminal(state):
            break
        actions = model.legal_actions(state, state["to_move"])
        assert actions, "to_move player must always have a legal action"
        state = model.step(state, rng.choice(actions))
    assert model.is_terminal(state)
    total = model.score(state, "black") + model.score(state, "white")
    empties = sum(cell == 0 for row in state["board"] for cell in row)
    assert total + empties == 64
