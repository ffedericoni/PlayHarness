"""Exercise the observe → predict → act → check → record loop with a fake page."""

import pytest

from playharness.bga.adapter import BGAAdapter
from playharness.bga.ui_map import UIMap
from playharness.model_api import games_dir, load_model
from playharness.timeline import Timeline
from playharness.types import PredictionMismatch

model = load_model("reversi")

PIDS = {1: "101", 2: "202"}  # black, white


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
        from pathlib import Path

        Path(path).write_bytes(b"fake-png")


def board_to_cells(board):
    return [
        {"x": x, "y": y, "player": PIDS[board[y - 1][x - 1]]}
        for y in range(1, 9)
        for x in range(1, 9)
        if board[y - 1][x - 1] != 0
    ]


def make_raw(board, active_pid, gamestate="playerTurn", logs=()):
    return {
        "game_name": "reversi",
        "player_id": "101",
        "table_id": "555",
        "active_player": active_pid,
        "gamestate_name": gamestate,
        "gamedatas": {
            "players": {
                "101": {"color": "000000", "score": "2"},
                "202": {"color": "ffffff", "score": "2"},
            },
            "board": board_to_cells(board),
        },
        "logs": list(logs),
    }


def make_adapter(page, tmp_path):
    return BGAAdapter(
        page=page,
        game="reversi",
        model=model,
        ui_map=UIMap.load(games_dir() / "reversi" / "ui_map.json"),
        timeline=Timeline(tmp_path / "timeline.jsonl"),
        screenshots_dir=tmp_path / "screenshots",
        poll_s=0.0,
        act_timeout_s=1.0,
    )


ACTION = {"type": "play_disc", "x": 4, "y": 3}


def test_green_prediction_check(tmp_path):
    state0 = model.initial_state(None)
    state1 = model.step(state0, ACTION)  # black plays, white to move
    page = FakePage(
        [
            make_raw(state0["board"], "101", logs=["game starts"]),
            make_raw(state1["board"], "202", logs=["Black plays (4,3)", "game starts"]),
        ]
    )
    adapter = make_adapter(page, tmp_path)

    obs = adapter.observe()
    assert obs["to_move"] == "black" and obs["viewer_color"] == "black"

    obs_after = adapter.commit_action(ACTION, obs)
    assert page.clicks == ["#square_4_3"]
    assert obs_after["to_move"] == "white"
    assert obs_after["board"] == state1["board"]

    [transition] = list(adapter.timeline.transitions())
    assert transition["match"] is True
    assert transition["action"] == ACTION
    assert transition["new_logs"] == ["Black plays (4,3)"]


def test_mismatch_halts_and_records_counterexample(tmp_path):
    state0 = model.initial_state(None)
    wrong = model.step(state0, ACTION)
    wrong_board = [row[:] for row in wrong["board"]]
    wrong_board[3][3] = 2  # BGA "forgot" to flip (4,4): reality diverges from model
    page = FakePage(
        [
            make_raw(state0["board"], "101"),
            make_raw(wrong_board, "202"),
        ]
    )
    adapter = make_adapter(page, tmp_path)
    obs = adapter.observe()

    with pytest.raises(PredictionMismatch) as excinfo:
        adapter.commit_action(ACTION, obs)
    assert any("board(4,4)" in m for m in excinfo.value.mismatches)

    # reality is recorded even though the model was wrong
    [transition] = list(adapter.timeline.transitions())
    assert transition["match"] is False
    assert transition["mismatches"]
    assert transition["obs_after"]["board"] == wrong_board
    # mismatch screenshot captured for the deliberation loop
    assert list((tmp_path / "screenshots").glob("mismatch_*.png"))


def test_rejected_action_times_out(tmp_path):
    from playharness.bga.adapter import ActionRejected

    state0 = model.initial_state(None)
    # click does not change the board (both snapshots identical)
    page = FakePage([make_raw(state0["board"], "101"), make_raw(state0["board"], "101")])
    adapter = make_adapter(page, tmp_path)
    adapter.act_timeout_s = 0.2
    obs = adapter.observe()
    with pytest.raises(ActionRejected):
        adapter.commit_action(ACTION, obs)
