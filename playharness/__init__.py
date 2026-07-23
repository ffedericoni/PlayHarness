"""PlayHarness — a Schema-inspired harness for learning and playing boardgames.

Phases 0-1: Timeline (append-only ground truth), sandboxed executor for
generated world models, backtest runner, planners, and the rulebook ->
certified-model pipeline. Phase 2: the Playwright BGA adapter
(:mod:`playharness.bga`) — observe / act / record against real tables with
per-step prediction checks.
"""

__version__ = "0.2.0"
