"""End-to-end Phase 1 pipeline — needs ANTHROPIC_API_KEY and makes real API calls.

Run explicitly with:  pytest tests/test_pipeline_api.py -v -s
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — API pipeline test skipped",
)


def test_learn_reversi_end_to_end():
    from playharness.learn import learn

    # Small validation settings to keep runtime down; the CLI defaults are the
    # real exit-criterion run.
    exit_code = learn("reversi", num_timelines=5, val_games=6, val_depth=2)
    assert exit_code in (0, 2)  # 2 = certified but winrate below 95% at reduced depth

    from pathlib import Path
    game_dir = Path("games/reversi")
    assert (game_dir / "rules_spec.json").exists()
    assert (game_dir / "ambiguities.md").exists()
    assert (game_dir / "world_model.py").exists()
