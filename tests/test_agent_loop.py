"""The full Schema deliberation loop (Phase 3), exercised offline.

A scripted theorizer stands in for Claude: when the loop detects that reality
has indicted the model — misprediction, rejection, missing model — it "repairs"
by writing the correct tictactoe implementation. The tests verify the loop's
discipline: reality is recorded unconditionally, mispredictions void plans and
trigger repair with a pointed counterexample, rejections reach the theorizer
as live feedback, state is re-derived after mid-game repairs, and a clean game
ends the session as converged.
"""

from pathlib import Path

import pytest

from playharness.agent import GameReport, play_game, run_session
from playharness.env import ReferenceEnv
from playharness.modelgen import certify
from playharness.timeline import Timeline

TICTACTOE_PATH = Path(__file__).resolve().parent.parent / "games" / "tictactoe" / "world_model.py"
CORRECT_CODE = TICTACTOE_PATH.read_text(encoding="utf-8")

# Correct everywhere except the mark player 1 places: "0" (zero) instead of
# "O". Certifies green on an empty board, then mispredicts reality's first
# observed opponent move.
BUGGY_MARKS_CODE = CORRECT_CODE.replace('MARKS = {0: "X", 1: "O"}',
                                        'MARKS = {0: "X", 1: "0"}')
assert BUGGY_MARKS_CODE != CORRECT_CODE

# Correct dynamics, but legal_actions offers OCCUPIED cells first — invisible
# to the backtest (which never calls legal_actions), so only live rejection
# by reality can expose it.
BUGGY_LEGAL_CODE = CORRECT_CODE.replace(
    """    return [{"type": "place", "cell": i}
            for i, mark in enumerate(state["board"]) if mark is None]""",
    """    occupied = [i for i, mark in enumerate(state["board"]) if mark is not None]
    empty = [i for i, mark in enumerate(state["board"]) if mark is None]
    return [{"type": "place", "cell": i} for i in occupied + empty]""")
assert BUGGY_LEGAL_CODE != CORRECT_CODE


def first_action(model, state, player):
    """Deterministic plan: the first action the model offers."""
    return model.legal_actions(state, player)[0]


def first_empty(model, state, player):
    return model.legal_actions(state, player)[0]


class ScriptedTheorizer:
    """Stands in for Claude: records every deliberation, writes fixed code."""

    def __init__(self, code: str = CORRECT_CODE):
        self.code = code
        self.calls: list[tuple[str, str, str | None]] = []

    def __call__(self, game_dir, timeline_paths, start_code, trigger, detail):
        self.calls.append((trigger, detail, start_code))
        (Path(game_dir) / "world_model.py").write_text(self.code, encoding="utf-8")

    @property
    def triggers(self) -> list[str]:
        return [trigger for trigger, _, _ in self.calls]


def make_env(tictactoe, seat=0):
    return ReferenceEnv(tictactoe, agent_seat=seat, opponent_policy=first_empty)


def play(tmp_path, tictactoe, theorizer, seat=0, **kwargs) -> GameReport:
    return play_game(make_env(tictactoe, seat), tmp_path,
                     tmp_path / "game_000.jsonl", theorizer=theorizer,
                     policy=first_action, call_timeout=30.0, verbose=False,
                     **kwargs)


def test_bootstrap_without_model(tmp_path, tictactoe):
    theorizer = ScriptedTheorizer()
    report = play(tmp_path, tictactoe, theorizer)

    assert theorizer.triggers == ["no-model"]
    assert theorizer.calls[0][2] is None          # no start_code yet
    assert report.mispredictions == 0 and report.rejections == 0
    assert report.scores                          # game reached a result
    entries = Timeline(report.timeline_path).entries()
    assert entries[0]["type"] == "init"
    assert entries[-1]["type"] == "result"
    green, detail = certify(tmp_path / "world_model.py", [report.timeline_path])
    assert green, detail


def test_misprediction_voids_plan_and_repairs(tmp_path, tictactoe):
    (tmp_path / "world_model.py").write_text(BUGGY_MARKS_CODE, encoding="utf-8")
    theorizer = ScriptedTheorizer()
    report = play(tmp_path, tictactoe, theorizer)

    # The buggy model certified green on the opening (empty board), predicted
    # the agent's own X move, then mispredicted reality's first O move.
    assert report.mispredictions == 1
    assert theorizer.triggers == ["misprediction"]
    trigger, detail, start_code = theorizer.calls[0]
    assert "live misprediction" in detail and "board[1]" in detail
    assert start_code == BUGGY_MARKS_CODE         # repair starts from the indicted code
    # Reality was recorded before the check: the mismatching transition is in
    # the Timeline, so certification of the buggy code would now be red.
    assert report.scores
    green, _ = certify(tmp_path / "world_model.py", [report.timeline_path])
    assert green


def test_rejection_reaches_theorizer_as_live_feedback(tmp_path, tictactoe):
    (tmp_path / "world_model.py").write_text(BUGGY_LEGAL_CODE, encoding="utf-8")
    theorizer = ScriptedTheorizer()
    report = play(tmp_path, tictactoe, theorizer)

    # Move 1 (empty board): no occupied cells, the buggy ordering is harmless.
    # Move 2: legal_actions offers an occupied cell first, the plan commits
    # it, reality rejects it — a failure the backtest could never catch.
    assert report.rejections == 1
    assert theorizer.triggers == ["rejection"]
    _, detail, _ = theorizer.calls[0]
    assert "REJECTED" in detail
    log_entries = Timeline(report.timeline_path).entries("log")
    assert len(log_entries) == 1
    assert log_entries[0]["raw"]["rejected_action"] == {"type": "place", "cell": 0}
    # The rejection never entered the record as a transition: every recorded
    # agent transition corresponds to an action reality accepted.
    agent_moves = [e for e in Timeline(report.timeline_path).transitions()
                   if e["player"] == 0]
    assert len(agent_moves) == report.moves
    assert report.scores


def test_opponent_first_seat(tmp_path, tictactoe):
    theorizer = ScriptedTheorizer()
    report = play(tmp_path, tictactoe, theorizer, seat=1)

    assert theorizer.triggers == ["no-model"]
    entries = Timeline(report.timeline_path).entries()
    # Opponent's opening move was recorded before the agent ever planned.
    assert entries[1]["type"] == "transition" and entries[1]["player"] == 0
    assert report.scores


def test_refuses_to_reuse_a_recorded_timeline(tmp_path, tictactoe):
    path = tmp_path / "game_000.jsonl"
    Timeline(path).append("init", config={}, observation={})
    with pytest.raises(ValueError, match="already holds"):
        play_game(make_env(tictactoe), tmp_path, path,
                  theorizer=ScriptedTheorizer(), policy=first_action,
                  verbose=False)


def test_session_converges_after_clean_game(tmp_path, tictactoe):
    theorizer = ScriptedTheorizer()
    session = run_session(
        tmp_path,
        env_factory=lambda i: make_env(tictactoe, seat=i % 2),
        max_games=4,
        theorizer=theorizer,
        policy_factory=lambda i: first_action,
        session_dir=tmp_path / "sessions" / "s000",
        call_timeout=30.0,
        verbose=False)

    # Game 1 needs the no-model deliberation; game 2 runs clean on the
    # standing model -> converged.
    assert theorizer.triggers == ["no-model"]
    assert session.converged and session.converged_at == 2
    assert [r.clean for r in session.reports] == [False, True]
    # The final backtest is green over every game the session recorded.
    paths = [r.timeline_path for r in session.reports]
    green, detail = certify(tmp_path / "world_model.py", paths)
    assert green, detail
