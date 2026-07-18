import random

from playharness.planner import alphabeta_policy, alphabeta_value, random_policy
from playharness.selfplay import play_game


def test_alphabeta_matches_exact_value_on_tictactoe(tictactoe):
    # Depth 9 covers the whole game tree: perfect play is a draw.
    state = tictactoe.initial_state({})
    assert alphabeta_value(tictactoe, state, 0, depth=9) == 0.0

    # Immediate win detection: X to move with 0,1 -> cell 2 wins.
    state = {"board": ["X", "X", None, "O", "O", None, None, None, None], "to_move": 0}
    assert alphabeta_policy(9)(tictactoe, state, 0) == {"type": "place", "cell": 2}


def test_alphabeta_beats_random_at_reversi(reversi):
    planner = alphabeta_policy(depth=2)
    wins = losses = 0
    num_games = 6
    for game in range(num_games):
        rng = random.Random(100 + game)
        rand = lambda m, s, p: random_policy(m, s, p, rng)
        seat = game % 2
        result = play_game(reversi, {seat: planner, 1 - seat: rand}, max_moves=200)
        if result.scores[seat] > 0:
            wins += 1
        elif result.scores[seat] < 0:
            losses += 1
    assert wins >= 5, f"alpha-beta won only {wins}/{num_games} vs random"
