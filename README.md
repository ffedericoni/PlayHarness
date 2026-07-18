# PlayHarness

A harness that uses Claude models to learn and play boardgames on
[BoardGameArena](https://www.boardgamearena.com): it reads a game's rulebook,
compiles it into an executable world model, certifies that model against real
play, and plans inside it. Architecture inspired by
[Schema](https://schema-harness.github.io/) — see
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the full design.

## Status: Phase 1 complete — rulebook → certified model (offline)

**Exit criteria met for Reversi** (2026-07-18): starting from only
`rulebook.md`, the pipeline extracted the spec, generated `world_model.py`,
repaired it from backtest counterexamples (2 dynamics iterations + 1 score
repair once the backtest began certifying recorded final scores), generated a
strategy-layer `heuristic()`, and finished with a green backtest over all 310
recorded entries and a **40/0/0 (100%)** win rate for depth-3 alpha-beta vs a
random player. The learning curve is the git history of
`games/reversi/world_model.py`.

| Piece | Where | Role |
|---|---|---|
| World-model contract | `playharness/model_api.py` | The six functions every game model exposes |
| Timeline | `playharness/timeline.py` | Append-only JSONL ground truth of real play |
| Backtest | `playharness/backtest.py` | Replays the Timeline through a model; green or a pointed counterexample |
| Sandbox | `playharness/sandbox.py` | Runs generated model code in a restricted subprocess |
| Planner | `playharness/planner.py` | Memoized minimax + depth-limited alpha-beta |
| Self-play | `playharness/selfplay.py` | Offline simulator mode; records Timelines in adapter format |
| Ground truth | `playharness/ground_truth.py` | Records timelines from a trusted reference model (BGA stand-in) |
| Ingestion | `playharness/ingest.py` | Rulebook (PDF/MD/TXT) → structured `RulesSpec` + ambiguity log |
| Model generation | `playharness/modelgen.py` | Claude compiles the spec into `world_model.py`; backtest-driven repair loop |
| Pipeline | `playharness/learn.py` | `python -m playharness.learn reversi` runs everything end to end |
| Reference models | `games/tictactoe/`, `games/reversi/` | Hand-written models validating the interfaces |

## Running the Phase 1 pipeline

```bash
pip install -e .          # anthropic + pydantic
export ANTHROPIC_API_KEY=...   # or `ant auth login`
python -m playharness.learn reversi
```

Steps: record ground-truth timelines from the reference Reversi model →
extract `rules_spec.json` + `ambiguities.md` from `games/reversi/rulebook.md`
→ Claude generates `world_model.py`, repaired until the backtest is green
across every recorded game → alpha-beta planner (inside the certified model,
via the sandbox) must beat a random player >95% of games. The generator never
sees the reference implementation — only the rulebook, the spec, and recorded
observations, exactly as it will only see the rulebook and BGA's behavior in
live play.

## Running the tests

```bash
pip install pytest
pytest                    # offline suite; API pipeline test skipped without a key
```

The suite covers Timeline semantics, backtest certification and
counterexample reporting, sandbox restrictions (import whitelist, no
filesystem, call timeouts), both hand-written game models, the planners, and
the offline halves of ingestion/generation.

## Layout

```
playharness/          the harness library
games/<game>/         per-game persistent memory (rulebook, spec, model, timelines, ...)
tests/                test suite
```

Next: Phase 2 — the Playwright BGA adapter (observe / act / record against
real tables), replacing the reference-model ground truth with recorded BGA
play.
