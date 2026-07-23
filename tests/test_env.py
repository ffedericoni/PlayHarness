"""ReferenceEnv: the offline reality the Phase 3 agent loop plays against."""

import pytest

from playharness.env import IllegalActionError, ReferenceEnv


def first_empty(model, state, player):
    """Deterministic opponent: place in the lowest-indexed empty cell."""
    return model.legal_actions(state, player)[0]


def test_reset_agent_moves_first(tictactoe):
    env = ReferenceEnv(tictactoe, agent_seat=0)
    config, obs, events = env.reset()
    assert config == {}
    assert obs == {"board": [None] * 9, "to_move": 0}
    assert events == []
    assert not env.is_terminal()


def test_reset_opponent_moves_first(tictactoe):
    env = ReferenceEnv(tictactoe, agent_seat=1, opponent_policy=first_empty)
    _, obs, events = env.reset()
    assert obs["board"] == [None] * 9          # init obs precedes opponent play
    assert len(events) == 1
    assert events[0].player == 0
    assert events[0].action == {"type": "place", "cell": 0}
    assert events[0].observation["board"][0] == "X"
    assert events[0].observation["to_move"] == 1


def test_act_returns_own_then_opponent_events(tictactoe):
    env = ReferenceEnv(tictactoe, agent_seat=0, opponent_policy=first_empty)
    env.reset()
    events = env.act({"type": "place", "cell": 4})
    assert [e.player for e in events] == [0, 1]
    assert events[0].observation["board"][4] == "X"
    assert events[1].observation["board"][0] == "O"   # first empty cell


def test_illegal_action_rejected_without_advancing(tictactoe):
    env = ReferenceEnv(tictactoe, agent_seat=0, opponent_policy=first_empty)
    env.reset()
    env.act({"type": "place", "cell": 4})
    with pytest.raises(IllegalActionError):
        env.act({"type": "place", "cell": 4})       # occupied
    # reality did not move: a legal action still works from the same position
    events = env.act({"type": "place", "cell": 8})
    assert events[0].observation["board"][8] == "X"


def test_act_before_reset_and_out_of_turn(tictactoe):
    env = ReferenceEnv(tictactoe, agent_seat=0)
    with pytest.raises(RuntimeError):
        env.act({"type": "place", "cell": 0})
    env2 = ReferenceEnv(tictactoe, agent_seat=1, opponent_policy=first_empty)
    env2.reset()
    # after reset it IS the agent's turn; acting twice in a row must fail on
    # the second because the env advances the opponent in between only once
    env2.act({"type": "place", "cell": 4})
    with pytest.raises(IllegalActionError):
        env2.act({"type": "place", "cell": 4})


def test_full_game_terminal_and_scores(tictactoe):
    env = ReferenceEnv(tictactoe, agent_seat=0, opponent_policy=first_empty)
    env.reset()
    # X takes 2, 4, 6 (a diagonal); O (first-empty) takes 0, 1
    for cell in (2, 4, 6):
        env.act({"type": "place", "cell": cell})
    assert env.is_terminal()
    assert env.scores() == {0: 1.0, 1: -1.0}
    with pytest.raises(IllegalActionError):
        env.act({"type": "place", "cell": 8})


def test_scores_before_terminal_raises(tictactoe):
    env = ReferenceEnv(tictactoe, agent_seat=0, opponent_policy=first_empty)
    env.reset()
    with pytest.raises(RuntimeError):
        env.scores()
