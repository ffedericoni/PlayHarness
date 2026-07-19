import random

import pytest

from playharness.model_api import validate_model
from playharness.planner import random_policy
from playharness.selfplay import play_game


def place(cell):
    return {"type": "place", "cell": cell}


def cells_of(actions):
    return sorted(a["cell"] for a in actions)


def test_satisfies_contract(reversi):
    validate_model(reversi)


def test_initial_state(reversi):
    state = reversi.initial_state({})
    board = state["board"]
    assert board[27] == "W" and board[36] == "W"   # d4, e5
    assert board[28] == "B" and board[35] == "B"   # e4, d5
    assert sum(m is not None for m in board) == 4
    assert state["to_move"] == 0  # Black first
    assert not reversi.is_terminal(state)


def test_black_opening_moves(reversi):
    state = reversi.initial_state({})
    # The four standard Black openings: d3, c4, f5, e6
    assert cells_of(reversi.legal_actions(state, 0)) == [19, 26, 37, 44]
    assert reversi.legal_actions(state, 1) == []


def test_placement_flips_flanked_line(reversi):
    state = reversi.initial_state({})
    state = reversi.step(state, place(19))  # Black d3 flanks d4
    assert state["board"][19] == "B"
    assert state["board"][27] == "B"  # d4 flipped
    assert state["board"][36] == "W"  # e5 untouched
    assert state["to_move"] == 1
    assert sum(m == "B" for m in state["board"]) == 4
    assert sum(m == "W" for m in state["board"]) == 1


def test_step_does_not_mutate(reversi):
    state = reversi.initial_state({})
    reversi.step(state, place(19))
    assert state["board"][19] is None
    assert state["board"][27] == "W"


def test_illegal_moves_raise(reversi):
    state = reversi.initial_state({})
    with pytest.raises(ValueError):
        reversi.step(state, place(27))  # occupied
    with pytest.raises(ValueError):
        reversi.step(state, place(0))   # flips nothing
    with pytest.raises(ValueError):
        reversi.step(state, place(64))  # out of range
    with pytest.raises(ValueError):
        reversi.step(state, {"type": "pass"})  # no pass action in this encoding


def test_turn_skip_when_opponent_cannot_move(reversi):
    # Two independent B-W pairs against the left edge. Black plays cell 2,
    # flipping cell 1; White then has no legal placement anywhere, so the
    # turn reverts to Black (auto-skip, no pass action recorded).
    board = [None] * 64
    board[0], board[1] = "B", "W"
    board[16], board[17] = "B", "W"
    state = {"board": board, "to_move": 0}

    state = reversi.step(state, place(2))
    assert state["board"][1] == "B"
    assert state["to_move"] == 0  # White skipped

    # Black finishes: flipping the last White disc ends the game.
    state = reversi.step(state, place(18))
    assert state["board"][17] == "B"
    assert state["to_move"] is None
    assert reversi.is_terminal(state)
    assert reversi.score(state, 0) == 6.0
    assert reversi.score(state, 1) == -6.0


def test_random_games_terminate_with_consistent_scores(reversi):
    for seed in range(3):
        rng = random.Random(seed)
        policy = lambda m, s, p: random_policy(m, s, p, rng)
        result = play_game(reversi, {0: policy, 1: policy}, max_moves=200)
        board = result.final_state["board"]
        blacks = sum(m == "B" for m in board)
        whites = sum(m == "W" for m in board)
        assert blacks + whites <= 64 and blacks + whites >= 4
        assert result.scores[0] == float(blacks - whites)
        assert result.scores[0] == -result.scores[1]
