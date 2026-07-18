import json

from playharness.timeline import Timeline


def test_append_and_read(tmp_path):
    tl = Timeline(tmp_path / "timeline.jsonl")
    tl.append({"type": "session_start", "game": "reversi"})
    tl.append({"type": "transition", "action": {"type": "play_disc", "x": 4, "y": 3}})
    records = list(tl.read())
    assert [r["seq"] for r in records] == [0, 1]
    assert all("ts" in r for r in records)
    assert list(tl.transitions())[0]["action"]["x"] == 4


def test_reopen_continues_sequence(tmp_path):
    path = tmp_path / "timeline.jsonl"
    Timeline(path).append({"type": "a"})
    tl2 = Timeline(path)
    assert tl2.seq == 1
    tl2.append({"type": "b"})
    assert [r["seq"] for r in tl2.read()] == [0, 1]


def test_append_only_no_mutation_api(tmp_path):
    tl = Timeline(tmp_path / "t.jsonl")
    tl.append({"type": "a"})
    before = tl.path.read_text()
    tl.append({"type": "b"})
    after = tl.path.read_text()
    assert after.startswith(before)  # earlier records never rewritten
    assert not hasattr(tl, "delete") and not hasattr(tl, "rewrite")


def test_records_are_json_lines(tmp_path):
    tl = Timeline(tmp_path / "t.jsonl")
    tl.append({"type": "x", "payload": {"nested": [1, 2]}})
    line = tl.path.read_text().strip()
    assert json.loads(line)["payload"]["nested"] == [1, 2]
