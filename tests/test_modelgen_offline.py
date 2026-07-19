"""Offline pieces of the ingestion + generation pipeline (no API calls)."""

import json

import pytest

from playharness.ground_truth import record_games
from playharness.ingest import RulesSpec, _rulebook_content
from playharness.modelgen import build_generation_prompt, certify, extract_code

SAMPLE_SPEC = {
    "game_name": "Reversi",
    "players": {"min": 2, "max": 2},
    "setup": "8x8 board, four central discs, Black moves first",
    "turn_structure": "Alternate; a player with no legal move is skipped",
    "actions": [{"name": "place_disc",
                 "preconditions": "empty square that outflanks at least one line",
                 "effects": "place disc, flip all outflanked discs",
                 "forced": True}],
    "objective": "Most discs of your colour when neither player can move",
    "randomness": "none",
    "hidden_information": "none — perfect information",
    "edge_cases": ["a player with no discs left loses"],
}


def test_rules_spec_schema_roundtrip():
    spec = RulesSpec.model_validate(SAMPLE_SPEC)
    assert spec.game_name == "Reversi"
    assert spec.players.min == 2
    assert json.loads(spec.model_dump_json())["actions"][0]["forced"] is True


def test_rulebook_content_text_and_pdf(tmp_path):
    md = tmp_path / "rules.md"
    md.write_text("# Rules\nPlace discs.")
    [block] = _rulebook_content(md)
    assert block["type"] == "text" and "Place discs" in block["text"]

    pdf = tmp_path / "rules.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    [block] = _rulebook_content(pdf)
    assert block["type"] == "document"
    assert block["source"]["media_type"] == "application/pdf"


def test_extract_code():
    text = "Here is the model:\n```python\ndef initial_state(config):\n    return {}\n```\nDone."
    assert extract_code(text) == "def initial_state(config):\n    return {}\n"
    with pytest.raises(ValueError):
        extract_code("no code here")


def test_generation_prompt_contains_spec_contract_and_examples(reversi, tmp_path):
    game_dir = tmp_path / "reversi"
    game_dir.mkdir()
    (game_dir / "rules_spec.json").write_text(json.dumps(SAMPLE_SPEC))
    timelines = record_games(reversi, game_dir / "timelines", num_games=1)

    prompt = build_generation_prompt(game_dir, timelines)
    assert "initial_state(config" in prompt          # the contract
    assert "outflanks at least one line" in prompt   # the spec
    assert "Initial observation" in prompt           # recorded examples
    assert '"to_move": 0' in prompt                  # encoding visible
    assert "reference_model" not in prompt           # never leak the reference


def test_certify_green_for_reference_source(reversi, tmp_path):
    from tests.conftest import REVERSI_REFERENCE_PATH

    timelines = record_games(reversi, tmp_path / "timelines", num_games=2)
    # A "generated" model that happens to be correct certifies green via sandbox
    candidate = tmp_path / "world_model.py"
    candidate.write_text(REVERSI_REFERENCE_PATH.read_text())
    green, detail = certify(candidate, timelines)
    assert green, detail
    assert "GREEN" in detail


def test_certify_red_produces_pointed_failure(reversi, tmp_path):
    timelines = record_games(reversi, tmp_path / "timelines", num_games=1)
    candidate = tmp_path / "world_model.py"
    # A wrong theory: never flips anything
    candidate.write_text(
        "def initial_state(config):\n"
        "    board = [None] * 64\n"
        "    board[27] = 'W'; board[36] = 'W'; board[28] = 'B'; board[35] = 'B'\n"
        "    return {'board': board, 'to_move': 0}\n"
        "def legal_actions(state, player):\n"
        "    return [{'type': 'place', 'cell': i} for i, m in enumerate(state['board']) if m is None]\n"
        "def step(state, action):\n"
        "    board = list(state['board'])\n"
        "    board[action['cell']] = 'B' if state['to_move'] == 0 else 'W'\n"
        "    return {'board': board, 'to_move': 1 - state['to_move']}\n"
        "def is_terminal(state):\n"
        "    return all(m is not None for m in state['board'])\n"
        "def score(state, player):\n"
        "    return 0.0\n"
        "def observation(state, player):\n"
        "    return {'board': list(state['board']), 'to_move': state['to_move']}\n"
    )
    green, detail = certify(candidate, timelines)
    assert not green
    assert "mismatch" in detail or "model raised" in detail
    assert "game_000" in detail  # names the timeline with the counterexample
