"""Shared types for the harness.

Observations, states, and actions are plain JSON-serializable dicts so they can
be appended verbatim to the Timeline and replayed by the backtest. Conventions:

- **State** (model-facing): ``{"board": [[int]], "to_move": "black"|"white"|None}``
- **Action**: ``{"type": str, ...fields}`` e.g. ``{"type": "play_disc", "x": 4, "y": 3}``
- **Observation**: superset of State with viewer/table metadata
  (``viewer_color``, ``game_over``, ``scores``, ``active_player``, ...)
"""

from __future__ import annotations

from typing import Any

State = dict[str, Any]
Action = dict[str, Any]
Observation = dict[str, Any]

# Fields of an observation that the world model predicts. Everything else
# (viewer identity, scores, log text) is metadata the prediction check ignores.
PREDICTED_FIELDS: tuple[str, ...] = ("board", "to_move")


class HarnessError(Exception):
    """Base class for harness errors."""


class IllegalAction(HarnessError):
    """An action was not legal in the given state."""


class PredictionMismatch(HarnessError):
    """The observed transition diverged from the world model's prediction.

    Reality outranks the model: whoever catches this must void the current
    plan and return to deliberation with the counterexample.
    """

    def __init__(self, action: Action, mismatches: list[str], predicted: Observation, actual: Observation):
        self.action = action
        self.mismatches = mismatches
        self.predicted = predicted
        self.actual = actual
        super().__init__(
            f"model prediction diverged from BGA after {action}: " + "; ".join(mismatches)
        )


def state_from_observation(obs: Observation) -> State:
    """Project an observation down to the model-facing state."""
    return {"board": obs["board"], "to_move": obs.get("to_move")}


def compare_observations(
    predicted: Observation,
    actual: Observation,
    fields: tuple[str, ...] = PREDICTED_FIELDS,
) -> list[str]:
    """Field-by-field diff between a predicted and an observed state.

    Returns a list of human-readable mismatch descriptions; empty means the
    prediction held. Board diffs are reported per-cell so a counterexample
    points at exactly which squares disagree.
    """
    mismatches: list[str] = []
    for field in fields:
        pred, act = predicted.get(field), actual.get(field)
        if field == "board" and isinstance(pred, list) and isinstance(act, list):
            for y, (prow, arow) in enumerate(zip(pred, act), start=1):
                for x, (p, a) in enumerate(zip(prow, arow), start=1):
                    if p != a:
                        mismatches.append(f"board({x},{y}): predicted {p}, observed {a}")
        elif pred != act:
            mismatches.append(f"{field}: predicted {pred!r}, observed {act!r}")
    return mismatches
