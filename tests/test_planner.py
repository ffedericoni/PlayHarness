import random

from playharness.planner import minimax_policy, minimax_value, random_policy
from playharness.selfplay import play_game


def test_tictactoe_is_a_draw_under_perfect_play(tictactoe):
    state = tictactoe.initial_state({})
    assert minimax_value(tictactoe, state, 0) == 0.0
    assert minimax_value(tictactoe, state, 1) == 0.0


def test_minimax_takes_immediate_win(tictactoe):
    # X has 0, 1 and it's X's turn: cell 2 completes the top row.
    state = {"board": ["X", "X", None, "O", "O", None, None, None, None], "to_move": 0}
    assert minimax_policy(tictactoe, state, 0) == {"type": "place", "cell": 2}


def test_minimax_blocks_immediate_loss(tictactoe):
    # O threatens 3, 4, 5; X must block at 5 (X has no win of its own).
    state = {"board": ["X", None, None, "O", "O", None, "X", None, None], "to_move": 0}
    assert minimax_policy(tictactoe, state, 0) == {"type": "place", "cell": 5}


def test_perfect_play_never_loses_to_random(tictactoe):
    rng = random.Random(42)
    rand = lambda m, s, p: random_policy(m, s, p, rng)
    losses = wins = 0
    for game in range(30):
        # Alternate which side the planner takes.
        planner_seat = game % 2
        policies = {planner_seat: minimax_policy, 1 - planner_seat: rand}
        result = play_game(tictactoe, policies)
        if result.scores[planner_seat] < 0:
            losses += 1
        elif result.scores[planner_seat] > 0:
            wins += 1
    assert losses == 0
    assert wins > 0  # random play should get punished at least sometimes


def test_selfplay_between_perfect_players_draws(tictactoe):
    result = play_game(tictactoe, {0: minimax_policy, 1: minimax_policy})
    assert result.scores == {0: 0.0, 1: 0.0}
    assert result.num_moves == 9
