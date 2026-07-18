"""Loader and interface contract for per-game world models.

A world model is a plain Python module (``games/<game>/world_model.py``) that
exposes the functions below. In later phases Claude writes and repairs these
files; in Phase 2 the Reversi model is hand-written. Loading by file path keeps
the contract identical either way.

Required functions::

    initial_state(config) -> State
    legal_actions(state, player) -> list[Action]
    step(state, action) -> State
    is_terminal(state) -> bool
    score(state, player) -> float
    observation(state, player) -> Observation
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REQUIRED_FUNCTIONS = (
    "initial_state",
    "legal_actions",
    "step",
    "is_terminal",
    "score",
    "observation",
)


def games_dir() -> Path:
    """Root of the per-game persistent memory (``games/``)."""
    return Path(__file__).resolve().parent.parent / "games"


def load_model(game: str, path: str | Path | None = None) -> ModuleType:
    """Load a game's world model module from disk.

    ``path`` overrides the default ``games/<game>/world_model.py`` location.
    Raises ``FileNotFoundError`` if the file is missing and ``AttributeError``
    if the module does not implement the full contract.
    """
    model_path = Path(path) if path else games_dir() / game / "world_model.py"
    if not model_path.exists():
        raise FileNotFoundError(f"world model not found: {model_path}")

    module_name = f"playharness_world_model_{game}"
    spec = importlib.util.spec_from_file_location(module_name, model_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    missing = [fn for fn in REQUIRED_FUNCTIONS if not callable(getattr(module, fn, None))]
    if missing:
        raise AttributeError(f"world model {model_path} missing functions: {missing}")
    return module
