import json

from playharness.backtest import run_backtest
from playharness.ground_truth import ensure_ground_truth, record_games
from playharness.timeline import Timeline


def test_record_games_is_deterministic_and_certifiable(reversi, tmp_path):
    paths = record_games(reversi, tmp_path / "a", num_games=2, base_seed=99)
    assert [p.name for p in paths] == ["game_000.jsonl", "game_001.jsonl"]

    # Same seed elsewhere -> byte-identical game content (modulo timestamps)
    paths_b = record_games(reversi, tmp_path / "b", num_games=2, base_seed=99)
    for a, b in zip(paths, paths_b):
        actions_a = [e["action"] for e in Timeline(a).transitions()]
        actions_b = [e["action"] for e in Timeline(b).transitions()]
        assert actions_a == actions_b

    # The reference model trivially certifies against its own recordings
    for path in paths:
        result = run_backtest(reversi, Timeline(path))
        assert result.ok, result.describe()


def test_record_games_never_overwrites(reversi, tmp_path):
    paths = record_games(reversi, tmp_path, num_games=1, base_seed=5)
    original = paths[0].read_text()
    record_games(reversi, tmp_path, num_games=1, base_seed=5)
    assert paths[0].read_text() == original


def test_ensure_ground_truth_uses_reference_model(tmp_path):
    # Build a fake game dir whose "reference model" is tic-tac-toe
    game_dir = tmp_path / "faketoe"
    game_dir.mkdir()
    source = (Timeline.__module__, )  # noqa: F841 — just to keep imports honest
    from tests.conftest import TICTACTOE_PATH
    (game_dir / "reference_model.py").write_text(TICTACTOE_PATH.read_text())

    paths = ensure_ground_truth(game_dir, num_games=3)
    assert len(paths) == 3
    # idempotent: second call records nothing new
    assert ensure_ground_truth(game_dir, num_games=3) == paths

    entries = list(Timeline(paths[0]))
    assert entries[0]["type"] == "init"
    assert entries[-1]["type"] == "result"
    assert json.dumps(entries[0]["observation"])  # JSON-serializable
