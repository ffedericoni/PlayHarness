# PlayHarness

A harness that uses Claude models to learn and play boardgames on
[BoardGameArena](https://boardgamearena.com) (BGA) by building an **executable
world model** of each game, verifying it against real play, and planning inside
it. See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the full design.

**Status: Phase 2 — BGA adapter (one game: Reversi).** Includes the minimal
Phase 0/1 substrate the adapter depends on: an append-only Timeline, a
hand-written Reversi world model, and an alpha-beta planner.

## Layout

```
playharness/
  types.py          # State/Action/Observation conventions, prediction diffing
  timeline.py       # append-only JSONL ground-truth record
  model_api.py      # world-model contract + loader
  plan/simple.py    # alpha-beta search over any world model
  bga/
    config.py       # env-driven configuration (credentials, selectors)
    session.py      # Playwright login + persisted browser session
    table.py        # navigate to a table, click through the lobby
    observe.py      # gamedatas -> normalized Observation (+ screenshot fallback)
    ui_map.py       # model action -> DOM selector mapping (data, not code)
    adapter.py      # observe/act/record with per-step prediction checks
  cli.py
games/reversi/
  world_model.py    # the executable theory (agent-owned from Phase 3 on)
  ui_map.json       # action -> selector templates for BGA's Reversi UI
  timeline.jsonl    # created at play time; never rewritten
tests/              # fully offline; no network or browser needed
```

## Setup

```bash
pip install -e ".[dev]"
python -m playwright install chromium   # skip if Chromium is already provisioned
python -m pytest tests/                 # offline test suite
```

## Offline self-play (no BGA needed)

```bash
python -m playharness selfplay reversi --games 10 --depth 3 --opponent random
```

## Playing on BGA

Credentials come from the environment; the browser session is persisted to
`~/.playharness/bga_storage_state.json` so you only authenticate once.

```bash
export BGA_EMAIL=... BGA_PASSWORD=...
python -m playharness bga-login

# Inspect a table's raw gamedatas + screenshot (useful for building UI maps):
python -m playharness bga-probe --table <table-id-or-url>

# Play. Create the table in the BGA UI first (training mode, no clock),
# then hand the harness its id or URL:
python -m playharness bga-play reversi --table <table-id-or-url>
```

Set `BGA_HEADLESS=0` to watch the browser.

Every move goes through the Schema-style per-step check: the world model
predicts the outcome, the action is committed through the UI map, the table is
re-observed, and the transition — predicted vs. actual — is appended to
`games/reversi/timeline.jsonl`. On any divergence the harness halts with the
counterexample (exit code 2); Phase 3 turns that halt into automated model
repair.

## Known limitations (Phase 2)

- Observation reads `window.gameui.gamedatas` after a page reload — reliable,
  but selector/shape drift in BGA's UI may require updating
  `games/reversi/ui_map.json` or `BGAConfig` selector candidates. Use
  `bga-probe` to inspect what the page actually serves.
- If the opponent replies within the post-action polling window, the check
  compares our prediction against a state that already includes their move and
  flags a mismatch. Rare at human/turn-based pace; handled properly by the
  Phase 3 deliberation loop.
- Table *creation* is manual (the lobby flow is bespoke per BGA redesign);
  joining/starting an existing table is automated.

## Compliance

Automated play may violate BGA's Terms of Use. Use this harness only against
solo/training modes and unrated tables, with an account clearly used for
research — never in ranked/arena play or against non-consenting opponents.
Prefer the offline simulator (`selfplay`) for development.
