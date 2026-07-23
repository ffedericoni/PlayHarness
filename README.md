# PlayHarness

A harness that uses Claude models to learn and play boardgames on
[BoardGameArena](https://www.boardgamearena.com): it reads a game's rulebook,
compiles it into an executable world model, certifies that model against real
play, and plans inside it. Architecture inspired by
[Schema](https://schema-harness.github.io/) — see
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the full design.

## Status: Phase 2 — BGA adapter (one game: Reversi)

Phase 2 adds the Playwright layer (`playharness/bga/`) that points the
certified world model at real BoardGameArena tables: login with a persisted
browser session, table navigation, observation via BGA's structured client
state (`window.gameui.gamedatas`, with a screenshot fallback), a data-driven
UI map (model action → DOM selector), and per-step prediction checks. See
"Playing on BGA" below.

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

Next: Phase 3 — the full deliberation loop: mispredictions void plans,
counterexamples drive model repair, backtest gates planning.
