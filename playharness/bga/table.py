"""Getting to a running game table.

Tables can be created by the harness itself (``create_table``) or joined by id
/ URL. ``goto_table`` handles the pre-game lobby: it clicks through accept/start
buttons until the page carries a live ``window.gameui``. Table lifecycle actions
(create / start / cancel) go through BGA's request-token endpoints — the same
calls the site's own JS makes — via ``call_bga``.
"""

from __future__ import annotations

import json
import logging
import re
import time

logger = logging.getLogger(__name__)

GAMEUI_READY_JS = "() => !!(window.gameui && window.gameui.gamedatas)"

# BGA numeric game ids (the value passed as ?game=<id> to createnew). The game
# panel also accepts the string name, but table creation needs the id.
GAME_IDS = {
    "reversi": 35,
    "tictactoe": 1,
}

# Buttons that may stand between us and a started game, in the pre-game lobby.
LOBBY_BUTTON_SELECTORS = (
    "#ag_new_table_accept",       # accept a table invite / open seat
    "#joingame_accept_button",
    "#startgame_button",
    "#ags_start_game_accept",     # "express start" confirmation
)


class TableError(Exception):
    pass


def table_url(base_url: str, table_ref: str) -> str:
    """Accept a full table URL or a bare numeric table id."""
    if re.fullmatch(r"\d+", str(table_ref)):
        return f"{base_url}/table?table={table_ref}"
    return str(table_ref)


def call_bga(page, path: str, params: dict | None = None) -> dict:
    """Call a BGA action endpoint from within the page (cookies + request token).

    BGA rejects state-changing calls that lack ``bgaRequestToken`` (error 806).
    Running the fetch inside the page applies the site's cookies and origin
    exactly as its own JS would. Returns the parsed JSON ``data`` on success;
    raises ``TableError`` with BGA's message otherwise.
    """
    result = page.evaluate(
        """async ({path, params}) => {
            const token = window.bgaConfig && window.bgaConfig.requestToken;
            const qs = new URLSearchParams({...params, 'dojo.preventCache': String(Date.now())});
            if (token) qs.set('bgaRequestToken', token);
            const r = await fetch(path + '?' + qs.toString(), {
                headers: token ? {'X-Request-Token': token} : {},
                credentials: 'include',
            });
            return {status: r.status, body: await r.text()};
        }""",
        {"path": path, "params": {k: str(v) for k, v in (params or {}).items()}},
    )
    try:
        payload = json.loads(result["body"])
    except (json.JSONDecodeError, TypeError):
        raise TableError(f"{path}: non-JSON response (HTTP {result.get('status')}): {result.get('body', '')[:200]}")
    # BGA uses status "1"/1 for success, "0"/0 for a handled error.
    if str(payload.get("status")) != "1":
        raise TableError(f"{path}: {payload.get('error') or payload.get('exception') or payload}")
    return payload.get("data", {})


def create_table(page, game: str, mode: str = "realtime", force_manual: bool = True) -> str:
    """Create a new table for ``game`` and return its id.

    ``force_manual`` keeps the table from auto-starting, so it never begins a
    game against a random opponent — the harness (or you) starts it explicitly
    once the intended second player is seated. Requires a logged-in page.
    """
    game_id = GAME_IDS.get(game)
    if game_id is None:
        raise TableError(f"no BGA game id registered for {game!r}; add it to GAME_IDS")
    data = call_bga(page, "/table/table/createnew.html", {
        "game": game_id,
        "gamemode": mode,
        "forceManual": "true" if force_manual else "false",
    })
    table_id = data.get("table")
    if not table_id:
        raise TableError(f"createnew returned no table id: {data}")
    logger.info("created %s table %s (mode=%s, manual=%s)", game, table_id, mode, force_manual)
    return str(table_id)


def cancel_table(page, table_id: str) -> None:
    """Quit/cancel a table the harness created (cleanup)."""
    call_bga(page, "/table/table/quitgame.html", {"table": table_id})
    logger.info("cancelled table %s", table_id)


def start_table(page, table_id: str) -> None:
    """Explicitly start a manual table once the second seat is filled."""
    call_bga(page, "/table/table/startgame.html", {"table": table_id})
    logger.info("started table %s", table_id)


def goto_table(page, base_url: str, table_ref: str, timeout_s: float = 180.0, poll_s: float = 2.0) -> None:
    """Navigate to a table and wait until the game is running (``gameui`` present).

    Clicks any lobby accept/start buttons that appear along the way. Times out
    if the game hasn't started within ``timeout_s`` (e.g. waiting on an
    opponent who never sits down).
    """
    url = table_url(base_url, table_ref)
    logger.info("navigating to table: %s", url)
    page.goto(url, wait_until="domcontentloaded")

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if page.evaluate(GAMEUI_READY_JS):
                logger.info("game is running at %s", page.url)
                return
        except Exception:
            pass
        for selector in LOBBY_BUTTON_SELECTORS:
            try:
                button = page.locator(selector).first
                if button.is_visible():
                    logger.info("clicking lobby button %s", selector)
                    button.click()
                    page.wait_for_timeout(1000)
                    break
            except Exception:
                continue
        page.wait_for_timeout(int(poll_s * 1000))
    raise TableError(f"game did not start within {timeout_s:.0f}s at {url}")
