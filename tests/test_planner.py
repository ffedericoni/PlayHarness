import random

from playharness.model_api import load_model
from playharness.plan import simple

model = load_model("reversi")


def play(black_policy, white_policy, rng):
    state = model.initial_state(None)
    while not model.is_terminal(state):
        policy = black_policy if state["to_move"] == "black" else white_policy
        state = model.step(state, policy(state, state["to_move"], rng))
    return state


def search_policy(depth):
    return lambda state, player, rng: simple.choose_action(model, state, player, depth=depth, rng=rng)


def random_policy(state, player, rng):
    return simple.random_action(model, state, player, rng=rng)


def test_search_beats_random():
    rng = random.Random(1234)
    wins = 0
    games = 10
    for game_index in range(games):
        search_color = "black" if game_index % 2 == 0 else "white"
        other = "white" if search_color == "black" else "black"
        policies = {search_color: search_policy(2), other: random_policy}
        final = play(policies["black"], policies["white"], rng)
        if model.score(final, search_color) > model.score(final, other):
            wins += 1
    assert wins >= 8, f"search won only {wins}/{games} vs random"


def test_choose_action_returns_none_when_not_to_move():
    state = model.initial_state(None)
    assert simple.choose_action(model, state, "white", depth=2) is None
