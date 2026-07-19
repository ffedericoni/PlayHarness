"""Exercise the observe → sync → predict → act → check → record loop with a
fake table page, including replaying a recorded fake game through the backtest."""

from pathlib import Path

import pytest

from playharness.backtest import run_backtest
from playharness.bga.adapter import (
    ActionRejected,
    BGAAdapter,
    PredictionMismatch,
    infer_action_path,
    project,
)
from playharness.bga.ui_map import UIMap
from playharness.timeline import Timeline
from tests.conftest import REPO_ROOT

PIDS = {"B": "101", "W": "202"}


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    @property
    def first(self):
        return self

    def click(self, timeout=None):
        self.page.clicks.append(self.selector)
        self.page.index = min(self.page.index + 1, len(self.page.snapshots) - 1)

    def is_visible(self):
        return False


class FakePage:
    """Serves a scripted sequence of raw snapshots; a click advances the script."""

    def __init__(self, snapshots):
        self.snapshots = snapshots
        self.index = 0
        self.clicks = []

    def reload(self, wait_until=None):
        pass

    def wait_for_function(self, js, timeout=None):
        pass

    def evaluate(self, js):
        return self.snapshots[self.index]

    def locator(self, selector):
        return FakeLocator(self, selector)

    def screenshot(self, path=None, full_page=False):
        Path(path).write_bytes(b"fake-png")

    def advance(self):
        self.index = min(self.index + 1, len(self.snapshots) - 1)


def board_to_cells(board):
    return [
        {"x": i % 8 + 1, "y": i // 8 + 1, "player": PIDS[board[i]]}
        for i in range(64)
        if board[i] is not None
    ]


def make_raw(state, viewer="101", logs=(), game_over=None):
    over = state["to_move"] is None if game_over is None else game_over
    return {
        "game_name": "reversi",
        "player_id": viewer,
        "table_id": "555",
        "active_player": None if over else PIDS["B" if state["to_move"] == 0 else "W"],
        "gamestate_name": "gameEnd" if over else "playerTurn",
        "gamedatas": {
            "players": {
                "101": {"color": "000000", "score": "2"},
                "202": {"color": "ffffff", "score": "2"},
            },
            "board": board_to_cells(state["board"]),
        },
        "logs": list(logs),
    }


def make_adapter(page, tmp_path, reversi):
    return BGAAdapter(
        page=page,
        game="reversi",
        model=reversi,
        ui_map=UIMap.load(REPO_ROOT / "games" / "reversi" / "ui_map.json"),
        timeline=Timeline(tmp_path / "timeline.jsonl"),
        screenshots_dir=tmp_path / "screenshots",
        poll_s=0.0,
        act_timeout_s=1.0,
    )


def first_action(model, state):
    return model.legal_actions(state, state["to_move"])[0]


def test_sync_records_init_from_starting_position(tmp_path, reversi):
    state0 = reversi.initial_state({})
    page = FakePage([make_raw(state0, logs=["game starts"])])
    adapter = make_adapter(page, tmp_path, reversi)

    obs = adapter.sync()
    assert obs["to_move"] == 0 and obs["viewer_player"] == 0
    entries = list(adapter.timeline)
    assert [e["type"] for e in entries] == ["init", "log"]
    assert entries[0]["observation"] == reversi.observation(state0, None)
    assert entries[1]["raw"] == "game starts"


def test_green_commit_records_observed_transition(tmp_path, reversi):
    state0 = reversi.initial_state({})
    action = first_action(reversi, state0)
    state1 = reversi.step(state0, action)
    page = FakePage([make_raw(state0), make_raw(state1, logs=["Black plays"])])
    adapter = make_adapter(page, tmp_path, reversi)

    adapter.sync()
    obs_after = adapter.commit_action(action)
    assert page.clicks  # UI was driven
    assert obs_after["to_move"] == 1
    [transition] = adapter.timeline.transitions()
    assert transition["player"] == 0
    assert transition["action"] == action
    assert transition["observation"] == project(obs_after)
    assert "inferred" not in transition


def test_sync_infers_opponent_move(tmp_path, reversi):
    state0 = reversi.initial_state({})
    our = first_action(reversi, state0)
    state1 = reversi.step(state0, our)
    their = first_action(reversi, state1)
    state2 = reversi.step(state1, their)

    page = FakePage([make_raw(state0), make_raw(state1), make_raw(state2)])
    adapter = make_adapter(page, tmp_path, reversi)
    adapter.sync()
    adapter.commit_action(our)

    page.advance()  # opponent moves while we poll
    adapter.sync()

    transitions = adapter.timeline.transitions()
    assert len(transitions) == 2
    assert transitions[1]["player"] == 1
    assert transitions[1]["action"] == their
    assert transitions[1]["inferred"] is True
    assert transitions[1]["observation"] == reversi.observation(state2, None)


def test_fast_opponent_reply_is_reconciled_not_mismatched(tmp_path, reversi):
    state0 = reversi.initial_state({})
    our = first_action(reversi, state0)
    state1 = reversi.step(state0, our)
    their = first_action(reversi, state1)
    state2 = reversi.step(state1, their)

    # After our click the page already shows the state *after* the opponent's
    # reply — the intermediate state is never observed.
    page = FakePage([make_raw(state0), make_raw(state2)])
    adapter = make_adapter(page, tmp_path, reversi)
    adapter.sync()
    adapter.commit_action(our)

    transitions = adapter.timeline.transitions()
    assert len(transitions) == 2
    assert transitions[0]["player"] == 0
    assert transitions[0]["observation_inferred"] is True
    assert transitions[1]["player"] == 1
    assert transitions[1]["observation"] == reversi.observation(state2, None)
    assert adapter.state == state2


def test_unexplainable_state_halts_with_counterexample(tmp_path, reversi):
    state0 = reversi.initial_state({})
    action = first_action(reversi, state0)
    impossible = reversi.step(state0, action)
    impossible = {"board": list(impossible["board"]), "to_move": impossible["to_move"]}
    impossible["board"][27] = None  # a disc vanished: no legal explanation

    page = FakePage([make_raw(state0), make_raw(impossible)])
    adapter = make_adapter(page, tmp_path, reversi)
    adapter.sync()

    with pytest.raises(PredictionMismatch):
        adapter.commit_action(action)

    counterexamples = [e for e in adapter.timeline.entries("log") if e.get("mismatched_paths")]
    assert len(counterexamples) == 1
    assert counterexamples[0]["action"] == action
    assert list((tmp_path / "screenshots").glob("mismatch_*.png"))


def test_rejected_action_times_out(tmp_path, reversi):
    state0 = reversi.initial_state({})
    # click does not change the served state
    page = FakePage([make_raw(state0), make_raw(state0)])
    adapter = make_adapter(page, tmp_path, reversi)
    adapter.sync()
    adapter.act_timeout_s = 0.2
    with pytest.raises(ActionRejected):
        adapter.commit_action(first_action(reversi, state0))


def test_infer_action_path_depth_two(reversi):
    state0 = reversi.initial_state({})
    a = first_action(reversi, state0)
    s1 = reversi.step(state0, a)
    b = first_action(reversi, s1)
    s2 = reversi.step(s1, b)
    path = infer_action_path(reversi, state0, project(reversi.observation(s2, None)))
    assert [step[1] for step in path] == [a, b]


def test_recorded_fake_game_replays_green_through_backtest(tmp_path, reversi):
    """The Phase 2 exit-shaped property: a game recorded from the (fake) table
    is exactly the ground truth run_backtest certifies against."""
    state = reversi.initial_state({})
    snapshots = [make_raw(state)]
    states = [state]
    while state["to_move"] is not None:
        state = reversi.step(state, first_action(reversi, state))
        snapshots.append(make_raw(state))
        states.append(state)

    page = FakePage(snapshots)
    adapter = make_adapter(page, tmp_path, reversi)

    while True:
        obs = adapter.sync()
        if obs["game_over"]:
            break
        if obs["to_move"] == obs["viewer_player"]:
            adapter.commit_action(first_action(reversi, adapter.state))
        else:
            page.advance()  # opponent moves

    entries = list(adapter.timeline)
    assert entries[0]["type"] == "init"
    assert entries[-1]["type"] == "result"
    final = states[-1]
    assert entries[-1]["scores"] == {
        "0": reversi.score(final, 0), "1": reversi.score(final, 1)
    }

    result = run_backtest(reversi, adapter.timeline)
    assert result.ok, result.describe()
