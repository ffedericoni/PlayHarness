# PlayHarness

A harness that uses Claude models to learn and play boardgames on
[BoardGameArena](https://www.boardgamearena.com): it reads a game's rulebook,
compiles it into an executable world model, certifies that model against real
play, and plans inside it. Architecture inspired by
[Schema](https://schema-harness.github.io/) — see
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the full design.

## Status: Phase 3 loop wired — full Schema deliberation cycle (offline env)

**Phase 3 (2026-07-23)**: the deliberation cycle runs end to end against an
`Environment` interface (`playharness/env.py`) that the Phase 2 BGA adapter
will later implement — for now an offline `ReferenceEnv` stands in for BGA.
The agent loop (`playharness/agent.py`) enforces the Schema discipline live:
the backtest gates planning; every committed action and every observed
opponent move is checked against `step()`'s prediction; one misprediction
voids the plan and re-enters deliberation with a recorded counterexample;
illegal-action rejections (invisible to the backtest, which never calls
`legal_actions`) reach the repair prompt as live feedback; an exploration mix
probes off the planner's line while the model is still being falsified.
Convergence = a full game with zero deliberations plus a green backtest over
every recorded game.

Validated on Reversi with the Phase 1–certified model resumed: clean games
from both seats (60 transitions, 0 mispredictions, 0 rejections), and the
whole loop is covered by offline tests using scripted theorizers (a buggy
model is caught mid-game by a live misprediction, repaired, and the game
recovers its position by replaying the Timeline). The from-rulebook-only
games-to-green measurement (`python -m playharness.live reversi --fresh`)
needs an `ANTHROPIC_API_KEY`.

## Phase 1 (2026-07-18): rulebook → certified model (offline)

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
| Environment | `playharness/env.py` | What reality looks like to the agent: observe/act/reject; `ReferenceEnv` is the offline BGA stand-in |
| Agent loop | `playharness/agent.py` | The Schema cycle live: certify-gated planning, per-move prediction checks, counterexample-driven repair |
| Live pipeline | `playharness/live.py` | `python -m playharness.live reversi --fresh` plays real games until convergence |

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
filesystem, call timeouts), both hand-written game models, the planners, the
offline halves of ingestion/generation, the environment contract, and the
full Phase 3 deliberation loop (scripted theorizers stand in for Claude, so
misprediction/rejection/repair/convergence paths all run offline).

## Layout

```
playharness/          the harness library
games/<game>/         per-game persistent memory (rulebook, spec, model, timelines, ...)
tests/                test suite
```

Next: the deferred Phase 2 — the Playwright BGA adapter, implementing the
`Environment` interface against real tables (observe / act / record), so the
Phase 3 loop drives BGA unchanged; then Phase 4 — chance and
hidden-information games (expectimax, determinized MCTS).
