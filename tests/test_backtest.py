import random
from types import SimpleNamespace

from playharness.backtest import diff_paths, run_backtest
from playharness.planner import random_policy
from playharness.selfplay import play_game
from playharness.timeline import Timeline


def record_random_game(model, path, seed=0):
    rng = random.Random(seed)
    timeline = Timeline(path)
    policy = lambda m, s, p: random_policy(m, s, p, rng)
    play_game(model, {0: policy, 1: policy}, timeline=timeline)
    return timeline


def test_green_on_faithful_replay(tictactoe, tmp_path):
    timeline = record_random_game(tictactoe, tmp_path / "timeline.jsonl")
    result = run_backtest(tictactoe, timeline)
    assert result.ok, result.describe()
    # init + every transition was verified
    assert result.checked == 1 + len(timeline.transitions())
    assert "GREEN" in result.describe()


def test_counterexample_on_wrong_transition_rule(tictactoe, tmp_path):
    timeline = record_random_game(tictactoe, tmp_path / "timeline.jsonl")

    # A broken theory: places the wrong mark (always X). The backtest must
    # pinpoint the first transition where reality diverges — O's first move.
    def broken_step(state, action):
        nxt = tictactoe.step(state, action)
        board = ["X" if m is not None else None for m in nxt["board"]]
        return {"board": board, "to_move": nxt["to_move"]}

    broken = SimpleNamespace(
        initial_state=tictactoe.initial_state,
        legal_actions=tictactoe.legal_actions,
        step=broken_step,
        is_terminal=tictactoe.is_terminal,
        score=tictactoe.score,
        observation=tictactoe.observation,
    )

    result = run_backtest(broken, timeline)
    assert not result.ok
    assert result.checked == 2  # init + X's first move match; O's first move doesn't
    ce = result.counterexample
    assert ce.seq == timeline.transitions()[1]["seq"]
    assert any(path.startswith("board[") for path in ce.mismatched_paths)
    assert "mismatch" in result.describe()


def test_counterexample_on_model_exception(tictactoe, tmp_path):
    timeline = record_random_game(tictactoe, tmp_path / "timeline.jsonl")

    def exploding_step(state, action):
        raise KeyError("missing rule")

    broken = SimpleNamespace(
        initial_state=tictactoe.initial_state,
        legal_actions=tictactoe.legal_actions,
        step=exploding_step,
        is_terminal=tictactoe.is_terminal,
        score=tictactoe.score,
        observation=tictactoe.observation,
    )

    result = run_backtest(broken, timeline)
    assert not result.ok
    assert result.counterexample.error is not None
    assert "KeyError" in result.counterexample.error


def test_counterexample_on_wrong_initial_state(tictactoe, tmp_path):
    timeline = record_random_game(tictactoe, tmp_path / "timeline.jsonl")

    broken = SimpleNamespace(
        initial_state=lambda config: {"board": [None] * 9, "to_move": 1},
        legal_actions=tictactoe.legal_actions,
        step=tictactoe.step,
        is_terminal=tictactoe.is_terminal,
        score=tictactoe.score,
        observation=tictactoe.observation,
    )

    result = run_backtest(broken, timeline)
    assert not result.ok
    assert result.checked == 0
    assert result.counterexample.mismatched_paths == ["to_move"]


def test_diff_paths():
    assert diff_paths({"a": 1}, {"a": 1}) == []
    assert diff_paths({"a": 1}, {"a": 2}) == ["a"]
    assert diff_paths({"a": {"b": [1, 2]}}, {"a": {"b": [1, 3]}}) == ["a.b[1]"]
    assert diff_paths({"a": 1}, {"b": 1}) == ["a", "b"]
    assert diff_paths([1], [1, 2]) == ["[len 1!=2]"]
    assert diff_paths(1, "1") == ["<root>"]
