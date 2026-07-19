import pytest

from playharness.model_api import validate_model


def place(cell):
    return {"type": "place", "cell": cell}


def play(model, cells):
    state = model.initial_state({})
    for cell in cells:
        state = model.step(state, place(cell))
    return state


def test_satisfies_contract(tictactoe):
    validate_model(tictactoe)


def test_initial_state(tictactoe):
    state = tictactoe.initial_state({})
    assert state["board"] == [None] * 9
    assert state["to_move"] == 0
    assert not tictactoe.is_terminal(state)
    assert len(tictactoe.legal_actions(state, 0)) == 9
    assert tictactoe.legal_actions(state, 1) == []


def test_step_does_not_mutate(tictactoe):
    state = tictactoe.initial_state({})
    tictactoe.step(state, place(4))
    assert state["board"] == [None] * 9
    assert state["to_move"] == 0


def test_x_wins_row(tictactoe):
    # X: 0, 1, 2 wins; O: 3, 4
    state = play(tictactoe, [0, 3, 1, 4, 2])
    assert tictactoe.is_terminal(state)
    assert state["to_move"] is None
    assert tictactoe.score(state, 0) == 1.0
    assert tictactoe.score(state, 1) == -1.0


def test_o_wins_column(tictactoe):
    # O takes the right column (2, 5, 8); X scatters on 0, 1, 3
    state = play(tictactoe, [0, 2, 1, 5, 3, 8])
    assert tictactoe.is_terminal(state)
    assert tictactoe.score(state, 1) == 1.0
    assert tictactoe.score(state, 0) == -1.0


def test_draw(tictactoe):
    # X O X / X O O / O X X — no line
    state = play(tictactoe, [0, 1, 2, 4, 3, 5, 7, 6, 8])
    assert tictactoe.is_terminal(state)
    assert all(m is not None for m in state["board"])
    assert tictactoe.score(state, 0) == 0.0
    assert tictactoe.score(state, 1) == 0.0


def test_illegal_moves_raise(tictactoe):
    state = tictactoe.initial_state({})
    state = tictactoe.step(state, place(4))
    with pytest.raises(ValueError):
        tictactoe.step(state, place(4))  # occupied
    with pytest.raises(ValueError):
        tictactoe.step(state, place(9))  # out of range
    with pytest.raises(ValueError):
        tictactoe.step(state, {"type": "flip_table"})

    finished = play(tictactoe, [0, 3, 1, 4, 2])
    with pytest.raises(ValueError):
        tictactoe.step(finished, place(8))  # game over


def test_observation_is_full_state_copy(tictactoe):
    state = play(tictactoe, [4])
    obs = tictactoe.observation(state, 0)
    assert obs == {"board": state["board"], "to_move": state["to_move"]}
    obs["board"][0] = "corrupted"
    assert state["board"][0] is None
