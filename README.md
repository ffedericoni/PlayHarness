# PlayHarness

A harness that uses Claude models to learn and play boardgames on
[BoardGameArena](https://www.boardgamearena.com): it reads a game's rulebook,
compiles it into an executable world model, certifies that model against real
play, and plans inside it. Architecture inspired by
[Schema](https://schema-harness.github.io/) — see
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the full design.

## Status: Phase 0 — offline scaffold

What exists today (no Claude calls, no BGA):

| Piece | Where | Role |
|---|---|---|
| World-model contract | `playharness/model_api.py` | The six functions every game model exposes |
| Timeline | `playharness/timeline.py` | Append-only JSONL ground truth of real play |
| Backtest | `playharness/backtest.py` | Replays the Timeline through a model; green or a pointed counterexample |
| Sandbox | `playharness/sandbox.py` | Runs generated model code in a restricted subprocess |
| Planner | `playharness/planner.py` | Memoized minimax for perfect-information games |
| Self-play | `playharness/selfplay.py` | Offline simulator mode; records Timelines in adapter format |
| Reference model | `games/tictactoe/world_model.py` | Hand-written Tic-tac-toe validating all interfaces |

## Running the tests

```bash
pip install pytest   # only dependency for Phase 0
pytest
```

The suite records self-play games to Timelines, certifies models via backtest
(both in-process and through the sandbox), verifies counterexample reporting
against deliberately broken models, exercises the sandbox restrictions
(import whitelist, no filesystem, call timeouts), and checks the planner
plays Tic-tac-toe perfectly.

## Layout

```
playharness/          the harness library
games/<game>/         per-game persistent memory (model, timeline, notes, ...)
tests/                offline test suite
```

Next: Phase 1 — rulebook → `RulesSpec` → generated `world_model.py` for
Reversi, certified against recorded transcripts.
