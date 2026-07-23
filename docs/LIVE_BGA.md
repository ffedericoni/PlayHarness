# Running against live BoardGameArena

This note records what a real BGA session needs, based on driving the adapter
against the live site. The offline path (`selfplay`, the full test suite) needs
none of this.

## Credentials

Supply via environment only (never commit them):

```bash
export BGA_USERID=<username-or-email>   # BGA_EMAIL / BGA_USERNAME also accepted
export BGA_PASSWORD=<password>
python -m playharness bga-login          # persists a session, then reuses it
```

The login is a two-step Svelte form (username → password); the adapter submits
each step with Enter (the visible "Next"/"Log in" control is overlay-blocked on
click) and detects success via `window.globalUserInfos` (an anonymous session
reports name `Visitor`).

## Browser

- **Chromium**: point at a provisioned build if Playwright's managed download is
  unavailable: `export BGA_CHROMIUM_PATH=/opt/pw-browsers/chromium`.
- **Root**: the session passes `--no-sandbox` automatically when running as root.

## Network (egress-restricted environments)

BGA is spread across several hosts. Behind a filtering/TLS-terminating proxy,
**all** of these must be reachable, not just the main domain:

| Host | Purpose | Needed for |
|---|---|---|
| `boardgamearena.com`, `www.`, `en.` (or your lang) | main site + API | login, page loads |
| `x.boardgamearena.net` | static assets (JS, CSS, images) | the SPA to boot |
| `ws-x3.boardgamearena.com`, `ws-x4.boardgamearena.com` | realtime notification stream (`/connection/http_stream`) | matchmaking, table start, live move push |

Once all three host groups are allowlisted, the SPA boots normally and its
realtime channel connects (`wss://ws-x3.boardgamearena.com/connection/websocket`);
the "Application loading…" hang clears. Confirmed working in this environment.

Two proxy-specific issues observed:

1. **TLS reset on the ClientHello.** A TLS-terminating gateway may reset
   Chromium's TLS 1.3 hybrid-ML-KEM handshake. The session caps the proxy hop
   at TLS 1.2 (`--ssl-version-max=tls1.2`) when `HTTPS_PROXY` is set, and passes
   the proxy to Chromium explicitly (it ignores proxy env vars). Import the
   proxy CA into Chromium's NSS store so certificates verify.
2. **Realtime stream.** `ws-x*.boardgamearena.com/connection/http_stream` is a
   long-lived HTTP stream (BGA's websocket-equivalent). Many proxies neither
   allowlist these subdomains nor carry streaming/WebSocket upgrades. When this
   channel is down, BGA's SPA hangs at "Application loading…" and matchmaking /
   table start never complete.

   The adapter's **observation** deliberately does not depend on this push
   channel — it reloads the page and reads `window.gameui.gamedatas` from the
   initial payload — so reload-based observe/act can work even with the push
   channel degraded, *provided the in-game client still boots*. This has not yet
   been confirmable here because table start itself needs the SPA.

## Tables

The harness creates and manages tables itself through BGA's request-token
endpoints (verified live):

```bash
python -m playharness bga-create reversi   # prints a table id + URL
```

`bga-create` makes a turn-based (`async`) table with **manual start**, so it
never begins a game against a random opponent — the game starts only once the
intended second player is seated and start is triggered. Turn-based suits the
harness's reload-based observe/act (players need not be online at the same
time). `create_table` / `start_table` / `cancel_table` in
`playharness/bga/table.py` wrap the endpoints.

## Opponent

BGA Reversi has **no bot / solo / training-vs-AI mode** — a complete game needs
a second player. Options, in order of preference for research use:

1. A second BGA account the harness (or you) seats at a private **Simple game**
   (unranked) table — a genuine unassisted game, no third parties.
2. You play the opposing side by hand at a private table; the harness drives its
   own side and records the game.

Public matchmaking pairs you with a random, non-consenting human and is **out of
scope** for this harness (see the Compliance note in the README).

## Phase 2 exit criterion — MET

On 2026-07-23 the harness played a **complete, legal game of Reversi on live
BGA, unassisted**, on an unranked turn-based table (PlayHarness as White vs a
consenting human, Caronte, as Black). Record:
`games/reversi/timelines/bga_887637116.jsonl`.

- **Result: PlayHarness won 42–22** (29 of our moves committed).
- **Every per-step prediction check was green** — for all 29 of our moves the
  world model's predicted successor matched BGA's observed board exactly; no
  mismatch ever fired.
- **Offline certification**: replaying the recorded real-board observations,
  the world model reproduces **59/59** board-to-board transitions as legal
  model transitions, and `score()` reproduces BGA's final panel to the disc
  (Black 22 / White 42 → margin ∓20). The model is certified against real
  BGA play, not just self-play.

The one navigation bug live testing surfaced — the game client lives at
`/<gameserver>/<game>?table=<id>`, not `/table?table=<id>` — is fixed in
`table.py::game_client_url`. The observation normalizer, the `#square_{x}_{y}`
UI map, and the world model all matched BGA's real Reversi `gamedatas`
first try.

Known refinement: because the harness joined after Black's opening move, the
recorded timeline starts mid-game (no `init` entry) rather than as one clean
`init → … → result` chain, so `run_backtest` can't replay it from the top as-is
— certification above walks the observed boards directly. A future pass should
seed the timeline from `initial_state` and infer the opening move so recorded
BGA games are `run_backtest`-clean end to end.

## Verified

- Login end-to-end; session persists and re-authenticates with no re-login.
- With all BGA hosts allowlisted, the SPA boots and the realtime websocket
  connects — the earlier "Application loading…" hang is gone.
- Table create / cancel / enter (via gameserver URL) all work through the
  harness's own code against live BGA.
- A full game plays end to end with live per-step certification (above).
