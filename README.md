# PlayHarness

A harness that uses Claude models to learn and play boardgames on
[BoardGameArena](https://www.boardgamearena.com): it reads a game's rulebook,
compiles it into an executable world model, certifies that model against real
play, and plans inside it. Architecture inspired by
[Schema](https://schema-harness.github.io/) — see
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the full design.

## Status: Phases 2 & 3 integrated — live BGA adapter + full Schema loop

Both halves of the harness now live on `master`. **Phase 2** (`playharness/bga/`)
is the Playwright layer that points a certified world model at real
BoardGameArena tables; **Phase 3** (`playharness/agent.py`, `playharness/env.py`)
is the full Schema deliberation loop that certifies, plans, checks every
prediction, and repairs the model from counterexamples.

They are merged but not yet fused: the Phase 3 loop runs against the abstract
`Environment` interface (`playharness/env.py`), which the offline `ReferenceEnv`
satisfies; the Phase 2 `BGAAdapter` currently exposes its own self-contained
observe/sync/commit loop with its own per-step check. The remaining work is a
thin `BGAEnv` bridge so the Phase 3 deliberation loop drives live tables
directly (see "Next").

**Phase 3 exit criterion (2026-07-24)**: starting from *only* the Reversi
rulebook spec — `world_model.py` deleted, `python -m playharness.live reversi
--fresh` — the full Schema loop reached a green backtest and convergence in
**2 games** (1 deliberation, 0 mispredictions, 0 rejections, 120 recorded
transitions; session `games/reversi/sessions/s002/`). The first generation
certified green on iteration 1 because the interface now declares its action
wire format (`Environment.action_spec`): the encoding belongs to the interface
(on BGA the UI map fixes it and the table shows the legal opening moves), so
declaring it is observation, not leaked dynamics — the preconditions and
effects of actions are still learned from recorded play. Game 2 ran clean on
the standing model → converged.

**Phase 3 (2026-07-23)**: the deliberation cycle runs end to end against the
`Environment` interface. The agent loop enforces the Schema discipline live:
the backtest gates planning; every committed action and every observed
opponent move is checked against `step()`'s prediction; one misprediction
voids the plan and re-enters deliberation with a recorded counterexample;
illegal-action rejections (invisible to the backtest, which never calls
`legal_actions`) reach the repair prompt as live feedback; an exploration mix
probes off the planner's line while the model is still being falsified.
Convergence = a full game with zero deliberations plus a green backtest over
every recorded game.

**Phase 2 (BGA adapter)**: the Playwright layer that points the certified
world model at real BoardGameArena tables — login with a persisted browser
session, table navigation, observation via BGA's structured client state
(`window.gameui.gamedatas`, with a screenshot fallback), a data-driven UI map
(model action → DOM selector), and per-step prediction checks. Live BGA play
confirmed on Reversi. See "Playing on BGA" below.

## Phase 1 complete — rulebook → certified model (offline)

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

## Playing on BGA (Phase 2)

Credentials come from the environment; the browser session is persisted to
`~/.playharness/bga_storage_state.json` so you only authenticate once.

```bash
pip install -e .                        # adds playwright
python -m playwright install chromium   # skip if Chromium is already provisioned

export BGA_USERID=... BGA_PASSWORD=...   # BGA_EMAIL / BGA_USERNAME also accepted
python -m playharness bga-login

# Inspect a table's raw gamedatas + screenshot (useful for building UI maps):
python -m playharness bga-probe --table <table-id-or-url>

# Create a table (turn-based, manual start — never auto-starts vs a random):
python -m playharness bga-create reversi          # prints the table id + URL

# Play. Seat a second player in the table's open seat, then:
python -m playharness bga-play reversi --table <table-id-or-url>

# Offline self-play with the same planner, no BGA needed:
python -m playharness selfplay reversi --games 10 --depth 3
```

Set `BGA_HEADLESS=0` to watch the browser.

Every move goes through the Schema-style per-step check: the world model
predicts the outcome, the action is committed through the UI map
(`games/reversi/ui_map.json`), the table is re-observed, and the transition is
appended to `games/reversi/timelines/bga_<ts>.jsonl` — in exactly the entry
format `run_backtest` replays, so recorded BGA games certify the model
directly. Opponent moves (and auto-skip chains) are reconstructed by searching
the model for the legal action sequence that explains the observed board and
recorded with `"inferred": true`. Any divergence the model cannot explain
halts the harness with a recorded counterexample and a screenshot (exit code
2); Phase 3 turns that halt into automated model repair.

Phase 2 known limitations: BGA selector/shape drift may require updating
`ui_map.json` or `BGAConfig` selector candidates (use `bga-probe` to see what
the page serves). Running against live BGA also has environment requirements
(all BGA hosts reachable incl. the `ws-x*` realtime servers, a TLS-1.2 proxy
cap) and needs a second player, since Reversi has no bot — see
[docs/LIVE_BGA.md](docs/LIVE_BGA.md).

### Compliance

Automated play may violate BGA's Terms of Use. Use this harness only against
solo/training modes and unrated tables, with an account clearly used for
research — never in ranked/arena play or against non-consenting opponents.
Prefer the offline simulator (`selfplay`) for development.

## Layout

```
playharness/          the harness library
playharness/bga/      the Playwright BGA adapter (observe / act / record)
games/<game>/         per-game persistent memory (rulebook, spec, model, timelines, ...)
tests/                test suite
```

Next: drive the Phase 3 deliberation loop against the live BGA adapter (the
`BGAEnv` bridge that adapts the adapter to the `Environment` interface), so
model repair happens automatically during real play; then Phase 4 — chance and
hidden-information games (expectimax, determinized MCTS).
