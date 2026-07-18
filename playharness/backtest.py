"""Certification: replay the Timeline through a world model, belief by belief.

The model is only trusted for planning while the backtest is green. A mismatch
produces a pointed counterexample — which transition, which fields — that goes
back to the theorize step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .model_api import WorldModel
from .timeline import Timeline


@dataclass
class Counterexample:
    seq: int                      # timeline seq of the mismatching entry
    action: dict | None           # action taken (None for the init entry)
    expected: Any                 # recorded observation (ground truth)
    predicted: Any                # what the model produced
    mismatched_paths: list[str]   # dotted paths of differing fields
    error: str | None = None      # set if the model raised instead of predicting

    def describe(self) -> str:
        if self.error is not None:
            return f"seq {self.seq}: model raised: {self.error}"
        return (
            f"seq {self.seq}: mismatch at {', '.join(self.mismatched_paths) or '<root>'}\n"
            f"  action:    {self.action}\n"
            f"  expected:  {self.expected}\n"
            f"  predicted: {self.predicted}"
        )


@dataclass
class BacktestResult:
    ok: bool
    checked: int                  # entries verified before stopping
    counterexample: Counterexample | None = None
    notes: list[str] = field(default_factory=list)

    def describe(self) -> str:
        if self.ok:
            return f"backtest GREEN: {self.checked}/{self.checked} entries match"
        assert self.counterexample is not None
        return f"backtest RED after {self.checked} matches\n{self.counterexample.describe()}"


def diff_paths(expected: Any, predicted: Any, prefix: str = "") -> list[str]:
    """Dotted paths where two JSON-like values differ."""
    if isinstance(expected, dict) and isinstance(predicted, dict):
        paths = []
        for key in sorted(set(expected) | set(predicted)):
            sub = f"{prefix}.{key}" if prefix else str(key)
            if key not in expected or key not in predicted:
                paths.append(sub)
            else:
                paths.extend(diff_paths(expected[key], predicted[key], sub))
        return paths
    if isinstance(expected, list) and isinstance(predicted, list):
        if len(expected) != len(predicted):
            return [f"{prefix}[len {len(expected)}!={len(predicted)}]"]
        paths = []
        for i, (e, p) in enumerate(zip(expected, predicted)):
            paths.extend(diff_paths(e, p, f"{prefix}[{i}]"))
        return paths
    return [] if expected == predicted else [prefix or "<root>"]


def run_backtest(model: WorldModel, timeline: Timeline, viewpoint: int | None = None) -> BacktestResult:
    """Replay every init/transition entry in ``timeline`` through ``model``.

    ``viewpoint`` is the observer whose recorded observations we compare
    against (None = omniscient, the right choice for perfect-information
    games).
    """
    state: dict | None = None
    checked = 0

    for entry in timeline:
        if entry["type"] == "init":
            try:
                state = model.initial_state(entry.get("config", {}))
                predicted = model.observation(state, viewpoint)
            except Exception as exc:  # model bugs are findings, not crashes
                return BacktestResult(False, checked, Counterexample(
                    entry["seq"], None, entry["observation"], None, [], error=repr(exc)))
            paths = diff_paths(entry["observation"], predicted)
            if paths:
                return BacktestResult(False, checked, Counterexample(
                    entry["seq"], None, entry["observation"], predicted, paths))
            checked += 1

        elif entry["type"] == "transition":
            if state is None:
                return BacktestResult(False, checked, Counterexample(
                    entry["seq"], entry["action"], entry["observation"], None, [],
                    error="transition before init entry"))
            try:
                state = model.step(state, entry["action"])
                predicted = model.observation(state, viewpoint)
            except Exception as exc:
                return BacktestResult(False, checked, Counterexample(
                    entry["seq"], entry["action"], entry["observation"], None, [],
                    error=repr(exc)))
            paths = diff_paths(entry["observation"], predicted)
            if paths:
                return BacktestResult(False, checked, Counterexample(
                    entry["seq"], entry["action"], entry["observation"], predicted, paths))
            checked += 1

    return BacktestResult(True, checked)
