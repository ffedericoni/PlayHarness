"""Getting to a running game table.

The dependable path is joining a table by URL or id (create it in the BGA UI —
training mode, no clock — or have the harness accept an invite). ``goto_table``
handles the pre-game lobby: it clicks through accept/start buttons until the
page carries a live ``window.gameui``.
"""

from __future__ import annotations

import logging
import re
import time

logger = logging.getLogger(__name__)

GAMEUI_READY_JS = "() => !!(window.gameui && window.gameui.gamedatas)"

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
    if re.fullmatch(r"\d+", table_ref):
        return f"{base_url}/table?table={table_ref}"
    return table_ref


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
