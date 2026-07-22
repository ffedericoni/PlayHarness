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

## Verified so far

- Login end-to-end; session persists and re-authenticates as the configured
  user with no re-login.
- With all BGA hosts allowlisted, the SPA boots and the realtime websocket
  connects — the earlier "Application loading…" hang is gone.
- Table create / cancel work through the harness's own code against live BGA.
- Remaining gap to a full game: a **second player** in the table's open seat
  (see Opponent above). Everything up to "start the game" is automated.
