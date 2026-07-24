"""BGAEnv: the live table as a Phase 3 Environment, exercised with a fake page.

The bridge's point is that BGAEnv holds no model — it reports the opponent's move
as a raw board and the deliberation loop names it. So these tests drive the whole
``play_game`` loop against a scripted fake table and assert the recorded timeline
replays green through the backtest, exactly as a real BGA game would.
"""

from pathlib import Path

import pytest

from playharness.agent import play_game
from playharness.backtest import run_backtest
from playharness.bga.env import BGAEnv, project
from playharness.bga.ui_map import UIMap
from playharness.env import IllegalActionError
from playharness.timeline import Timeline
from tests.conftest import REPO_ROOT, REVERSI_REFERENCE_PATH
from tests.test_adapter import make_raw

UI_MAP_PATH = REPO_ROOT / "games" / "reversi" / "ui_map.json"


class SeqLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    @property
    def first(self):
        return self

    def click(self, timeout=None):
        self.page.clicks.append(self.selector)

    def is_visible(self):
        return False


class SeqPage:
    """Serves a scripted sequence of raw snapshots; each authoritative observe
    (a reload) advances to the next — modelling time passing on the table, so a
    poll can see the opponent's reply. Clicks are recorded but do not advance."""

    def __init__(self, snapshots):
        self.snapshots = snapshots
        self.index = -1  # first reload advances to snapshot 0
        self.clicks = []

    def reload(self, wait_until=None):
        self.index = min(self.index + 1, len(self.snapshots) - 1)

    def wait_for_function(self, js, timeout=None):
        pass

    def evaluate(self, js):
        return self.snapshots[max(self.index, 0)]

    def locator(self, selector):
        return SeqLocator(self, selector)

    def screenshot(self, path=None, full_page=False):
        Path(path).write_bytes(b"fake-png")


def first_action(model, state, player):
    return model.legal_actions(state, player)[0]


def make_env(page, tmp_path, **kwargs):
    opts = dict(poll_s=0.0, act_timeout_s=1.0, move_timeout_s=1.0)
    opts.update(kwargs)
    return BGAEnv(page, "reversi", UIMap.load(UI_MAP_PATH),
                  tmp_path / "screenshots", **opts)


def test_action_spec_declares_wire_format(tmp_path):
    env = make_env(SeqPage([make_raw({"board": [None] * 64, "to_move": 0})]), tmp_path)
    spec = env.action_spec()
    assert "place" in spec and "cell" in spec


def test_reset_detects_seat_and_reports_opponent_opening(tmp_path, reversi):
    # Viewer is White (seat 1); Black opens, so reset must surface Black's move
    # as a raw observation for the loop to name.
    state0 = reversi.initial_state({})
    black_move = first_action(reversi, state0, 0)
    state1 = reversi.step(state0, black_move)
    page = SeqPage([make_raw(state0, viewer="202"), make_raw(state1, viewer="202")])
    env = make_env(page, tmp_path)

    config, initial_obs, events = env.reset()
    assert env.agent_seat == 1
    assert config == {} and initial_obs == project(reversi.observation(state0, None))
    assert len(events) == 1
    assert events[0].action is None and events[0].player is None
    assert events[0].observation == project(reversi.observation(state1, None))


def test_reset_agent_first_has_no_events(tmp_path, reversi):
    state0 = reversi.initial_state({})
    page = SeqPage([make_raw(state0, viewer="101")])  # viewer Black, Black to move
    env = make_env(page, tmp_path)
    _, _, events = env.reset()
    assert env.agent_seat == 0 and events == []


def test_act_reports_named_move_and_rejects_unchanged_board(tmp_path, reversi):
    state0 = reversi.initial_state({})
    our = first_action(reversi, state0, 0)
    state1 = reversi.step(state0, our)
    their = first_action(reversi, state1, 1)
    state2 = reversi.step(state1, their)          # opponent replied; our turn again
    # The table already shows the post-reply board when we re-read (a fast table):
    # our own move is reported named, with the collapsed board as its observation.
    page = SeqPage([make_raw(state0), make_raw(state2)])
    env = make_env(page, tmp_path)
    env.reset()

    events = env.act(our)
    assert env.page.clicks                         # the UI was driven
    assert events[0].player == 0 and events[0].action == our
    assert events[0].observation == project(reversi.observation(state2, None))

    # A move reality never applies (board unchanged) is a rejection.
    stuck = SeqPage([make_raw(state0), make_raw(state0), make_raw(state0)])
    env2 = make_env(stuck, tmp_path)
    env2.reset()
    with pytest.raises(IllegalActionError):
        env2.act(our)


def test_scores_only_after_terminal(tmp_path, reversi):
    state0 = reversi.initial_state({})
    env = make_env(SeqPage([make_raw(state0)]), tmp_path)
    env.reset()
    with pytest.raises(RuntimeError):
        env.scores()


def _finished_game_snapshots(reversi):
    """Play a full game (first-action for both seats), one snapshot per our-turn
    checkpoint — each already reflecting the opponent's reply (a fast table)."""
    state = reversi.initial_state({})
    snaps = [make_raw(state)]
    while state["to_move"] is not None:
        state = reversi.step(state, first_action(reversi, state, state["to_move"]))
        while state["to_move"] is not None and state["to_move"] != 0:
            state = reversi.step(state, first_action(reversi, state, state["to_move"]))
        snaps.append(make_raw(state))
    return snaps, state


def test_full_live_game_records_a_green_backtestable_timeline(tmp_path, reversi):
    """End-to-end bridge: the Phase 3 loop drives a (fake) live table with a
    model-free BGAEnv, naming every opponent move by inference, and the recorded
    game is exactly the ground truth run_backtest certifies against."""
    # A certified model is already on disk, so the game runs clean (no repairs).
    game_dir = tmp_path
    (game_dir / "world_model.py").write_text(
        REVERSI_REFERENCE_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    snaps, final = _finished_game_snapshots(reversi)
    env = make_env(SeqPage(snaps), game_dir, move_timeout_s=1.0)
    timeline_path = game_dir / "sessions" / "live" / "game_000.jsonl"
    timeline_path.parent.mkdir(parents=True, exist_ok=True)

    report = play_game(
        env, game_dir, timeline_path,
        policy=lambda m, s, p: m.legal_actions(s, p)[0],
        call_timeout=30.0, verbose=False)

    assert report.clean, report.summary()          # never repaired the model
    assert report.deliberations == []
    assert report.scores == {0: reversi.score(final, 0), 1: reversi.score(final, 1)}

    timeline = Timeline(timeline_path)
    entries = list(timeline)
    assert entries[0]["type"] == "init" and entries[-1]["type"] == "result"
    # Opponent moves were named by the loop, not the environment.
    assert any(t.get("inferred") for t in timeline.transitions())

    result = run_backtest(reversi, timeline)
    assert result.ok, result.describe()
