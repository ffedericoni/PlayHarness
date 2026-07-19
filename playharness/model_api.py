"""The world-model contract.

A world model is a Python module (``games/<game>/world_model.py``) exposing six
module-level functions. All states, observations, actions, and configs must be
JSON-serializable (dicts/lists/str/int/float/bool/None) so they can be recorded
verbatim in the Timeline and compared exactly by the backtest.

Contract:

    initial_state(config: dict) -> dict
        Build the starting state. ``config`` carries game options
        (player count, variants, ...); ``{}`` must be accepted.

    legal_actions(state: dict, player: int) -> list[dict]
        Actions ``player`` may take in ``state``. Empty if it is not
        that player's turn or the game is over.

    step(state: dict, action: dict) -> dict
        Apply ``action`` and return the successor state. Must not mutate
        ``state``. Raises ``ValueError`` for illegal actions.

    is_terminal(state: dict) -> bool

    score(state: dict, player: int) -> float
        Final result from ``player``'s viewpoint (zero-sum games should
        return symmetric values; draws 0). When the game defines a graded
        result (point or disc differential), return that margin — not just
        the win/loss sign: planners use score() as the evaluation at search
        cutoffs, and recorded games certify its exact values. Must not raise
        on non-terminal states.

    observation(state: dict, player: int | None) -> dict
        What ``player`` can see of ``state``. ``player=None`` means the
        omniscient observer (used by the recorder/backtest for
        perfect-information games).

Additionally, every non-terminal state must carry a ``"to_move"`` key naming
the player whose turn it is (an int); terminal states set it to ``None``. The
harness (backtest, planner, self-play) relies on this key.
"""

from __future__ import annotations

import importlib.util
import sys
from typing import Any, Protocol

REQUIRED_FUNCTIONS = (
    "initial_state",
    "legal_actions",
    "step",
    "is_terminal",
    "score",
    "observation",
)


class WorldModel(Protocol):
    """Anything exposing the six contract functions (module, proxy, wrapper)."""

    def initial_state(self, config: dict) -> dict: ...
    def legal_actions(self, state: dict, player: int) -> list: ...
    def step(self, state: dict, action: dict) -> dict: ...
    def is_terminal(self, state: dict) -> bool: ...
    def score(self, state: dict, player: int) -> float: ...
    def observation(self, state: dict, player: int | None) -> dict: ...


def validate_model(model: Any) -> None:
    """Raise TypeError if ``model`` is missing any contract function."""
    missing = [name for name in REQUIRED_FUNCTIONS if not callable(getattr(model, name, None))]
    if missing:
        raise TypeError(f"world model is missing required functions: {', '.join(missing)}")


def load_model(path: str, module_name: str = "world_model") -> WorldModel:
    """Import a world-model module from a file path, in-process.

    Only for trusted (hand-written) models; model-generated code must go
    through :mod:`playharness.sandbox` instead.
    """
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load world model from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    validate_model(module)
    return module
