from playharness.timeline import Timeline


def test_append_and_iterate(tmp_path):
    tl = Timeline(tmp_path / "timeline.jsonl")
    tl.append("init", config={}, observation={"board": []})
    tl.append("transition", player=0, action={"cell": 4}, observation={"board": ["X"]})
    tl.append("log", raw="player X placed at center")

    entries = list(tl)
    assert [e["type"] for e in entries] == ["init", "transition", "log"]
    assert [e["seq"] for e in entries] == [0, 1, 2]
    assert all("ts" in e for e in entries)
    assert entries[1]["action"] == {"cell": 4}


def test_reopen_continues_sequence(tmp_path):
    path = tmp_path / "timeline.jsonl"
    Timeline(path).append("init", config={}, observation={})

    reopened = Timeline(path)
    entry = reopened.append("transition", player=0, action={}, observation={})
    assert entry["seq"] == 1
    assert len(reopened) == 2
    assert [e["seq"] for e in reopened] == [0, 1]


def test_transitions_filter(tmp_path):
    tl = Timeline(tmp_path / "timeline.jsonl")
    tl.append("init", config={}, observation={})
    tl.append("transition", player=0, action={}, observation={})
    tl.append("log", raw="x")
    tl.append("transition", player=1, action={}, observation={})

    assert len(tl.transitions()) == 2
    assert len(tl.entries("log")) == 1


def test_append_only_no_mutation_api(tmp_path):
    tl = Timeline(tmp_path / "timeline.jsonl")
    assert not hasattr(tl, "remove")
    assert not hasattr(tl, "rewrite")
    assert not hasattr(tl, "clear")
