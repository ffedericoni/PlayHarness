"""Record ground-truth timelines by playing a trusted reference model.

Offline substitute for the BGA adapter: the recorded ``timeline.jsonl`` files
play the role that real observed BGA games will play in Phase 2+ — the
append-only reality the generated world model must reproduce exactly.
"""

from __future__ import annotations

import random
from pathlib import Path

from .model_api import WorldModel, load_model
from .planner import random_policy
from .selfplay import play_game
from .timeline import Timeline


def record_games(model: WorldModel, out_dir: str | Path, num_games: int = 5,
                 base_seed: int = 1000) -> list[Path]:
    """Record ``num_games`` seeded random-vs-random games as timelines.

    Existing files are never overwritten or appended to — a timeline is the
    record of one real game. Returns the paths of all timelines in the dir.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for game in range(num_games):
        path = out_dir / f"game_{game:03d}.jsonl"
        if path.exists():
            continue
        rng = random.Random(base_seed + game)
        policy = lambda m, s, p: random_policy(m, s, p, rng)
        play_game(model, {0: policy, 1: policy}, timeline=Timeline(path))
    return sorted(out_dir.glob("game_*.jsonl"))


def ensure_ground_truth(game_dir: str | Path, num_games: int = 5) -> list[Path]:
    """Ensure ``games/<game>/timelines/`` has recorded games; return paths.

    Records from ``reference_model.py`` in the game dir when timelines are
    missing. Once the BGA adapter exists, real recorded games take this role
    and the reference model is no longer needed.
    """
    game_dir = Path(game_dir)
    timelines_dir = game_dir / "timelines"
    existing = sorted(timelines_dir.glob("game_*.jsonl"))
    if len(existing) >= num_games:
        return existing
    reference = load_model(str(game_dir / "reference_model.py"),
                           module_name=f"{game_dir.name}_reference_model")
    return record_games(reference, timelines_dir, num_games=num_games)
