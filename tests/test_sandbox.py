import textwrap

import pytest

from playharness.backtest import run_backtest
from playharness.sandbox import ModelTimeout, SandboxedModel, SandboxError


def write_model(tmp_path, body):
    path = tmp_path / "world_model.py"
    path.write_text(textwrap.dedent(body))
    return path


def test_proxies_full_interface(tictactoe_path):
    with SandboxedModel(tictactoe_path) as model:
        state = model.initial_state({})
        assert state == {"board": [None] * 9, "to_move": 0}
        actions = model.legal_actions(state, 0)
        assert len(actions) == 9
        state = model.step(state, {"type": "place", "cell": 4})
        assert state["board"][4] == "X"
        assert state["to_move"] == 1
        assert model.is_terminal(state) is False
        assert model.score(state, 0) == 0.0
        assert model.observation(state, None) == state


def test_model_exceptions_surface_as_sandbox_errors(tictactoe_path):
    with SandboxedModel(tictactoe_path) as model:
        state = model.initial_state({})
        with pytest.raises(SandboxError, match="already occupied"):
            state = model.step(state, {"type": "place", "cell": 4})
            model.step(state, {"type": "place", "cell": 4})


def test_backtest_runs_through_sandbox(tictactoe, tictactoe_path, tmp_path):
    # Certification path end to end: record in-process, replay in the sandbox.
    from tests.test_backtest import record_random_game

    timeline = record_random_game(tictactoe, tmp_path / "timeline.jsonl")
    with SandboxedModel(tictactoe_path) as model:
        result = run_backtest(model, timeline)
    assert result.ok, result.describe()


def test_disallowed_import_is_blocked(tmp_path):
    path = write_model(tmp_path, """
        import os
        def initial_state(config): return {}
    """)
    with pytest.raises(SandboxError, match="not allowed|closed stdout|died"):
        SandboxedModel(path)


def test_disallowed_import_inside_function_is_blocked(tmp_path):
    path = write_model(tmp_path, """
        def initial_state(config):
            import socket
            return {}
    """)
    with SandboxedModel(path) as model:
        with pytest.raises(SandboxError, match="not allowed"):
            model.initial_state({})


def test_open_is_blocked(tmp_path):
    path = write_model(tmp_path, """
        def initial_state(config):
            return {"secrets": open("/etc/passwd").read()}
    """)
    with SandboxedModel(path) as model:
        with pytest.raises(SandboxError, match="open"):
            model.initial_state({})


def test_allowed_stdlib_imports_work(tmp_path):
    path = write_model(tmp_path, """
        import math, random, itertools
        def initial_state(config):
            return {"pi": math.pi}
    """)
    with SandboxedModel(path) as model:
        assert model.initial_state({})["pi"] == pytest.approx(3.14159, abs=1e-4)


def test_infinite_loop_times_out(tmp_path):
    path = write_model(tmp_path, """
        def initial_state(config):
            while True:
                pass
    """)
    with SandboxedModel(path, call_timeout=2.0) as model:
        with pytest.raises(ModelTimeout):
            model.initial_state({})
