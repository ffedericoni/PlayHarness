"""Observation: turn a live BGA table page into a normalized Observation dict.

Primary source is BGA's own client state (``window.gameui.gamedatas``) — the
structured data the server sends the client — which is far more reliable than
scraping pixels or CSS. The page is reloaded before each authoritative
snapshot because ``gamedatas`` is only guaranteed fresh at page load; BGA
fully supports refresh mid-game. The game log text is captured for the
Timeline, and a screenshot is the fallback when the structured path fails.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..types import Observation

# Everything we pull out of the page in one JS evaluation.
SNAPSHOT_JS = """
() => {
  const g = window.gameui;
  if (!g || !g.gamedatas) return null;
  let active = null;
  try { if (g.getActivePlayerId) active = String(g.getActivePlayerId()); } catch (e) {}
  if (!active && g.gamedatas.gamestate && g.gamedatas.gamestate.active_player) {
    active = String(g.gamedatas.gamestate.active_player);
  }
  const logs = Array.from(document.querySelectorAll('#logs .log'))
    .slice(0, 60).map(e => (e.innerText || '').trim()).filter(t => t.length > 0);
  return {
    game_name: g.game_name || null,
    player_id: g.player_id != null ? String(g.player_id) : null,
    table_id: g.table_id != null ? String(g.table_id) : null,
    active_player: active,
    gamestate_name: (g.gamedatas.gamestate && g.gamedatas.gamestate.name) || null,
    gamedatas: g.gamedatas,
    logs: logs,
  };
}
"""

GAMEUI_READY_JS = "() => !!(window.gameui && window.gameui.gamedatas)"


class ObservationError(Exception):
    pass


def snapshot(page, reload: bool = True, timeout_ms: int = 30_000) -> dict[str, Any]:
    """Raw structured snapshot of the table page via ``window.gameui``."""
    if reload:
        page.reload(wait_until="domcontentloaded")
    page.wait_for_function(GAMEUI_READY_JS, timeout=timeout_ms)
    raw = page.evaluate(SNAPSHOT_JS)
    if raw is None:
        raise ObservationError("window.gameui.gamedatas not available on this page")
    return raw


def save_screenshot(page, directory: str | Path, label: str = "obs") -> str:
    """Vision fallback / debugging aid: full-page screenshot, path returned for the Timeline."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{label}_{int(time.time() * 1000)}.png"
    page.screenshot(path=str(path), full_page=True)
    return str(path)


# -- Reversi normalizer ------------------------------------------------------

_SIZE = 8


def _color_name(raw_color: str | None) -> str | None:
    if raw_color is None:
        return None
    c = str(raw_color).lstrip("#").lower()
    if c in ("000000", "000", "black"):
        return "black"
    if c in ("ffffff", "fff", "white"):
        return "white"
    return None


def _iter_board_cells(board_data: Any):
    """BGA ships the board as either a list of cells or a dict keyed by coordinate."""
    if isinstance(board_data, dict):
        yield from board_data.values()
    elif isinstance(board_data, list):
        yield from board_data
    else:
        raise ObservationError(f"unrecognized gamedatas.board shape: {type(board_data)}")


def normalize_reversi(raw: dict[str, Any]) -> Observation:
    """Normalize a raw snapshot of a BGA Reversi table into an Observation.

    Cell values follow the world model: 0 empty, 1 black, 2 white.
    """
    gamedatas = raw.get("gamedatas") or {}
    players = gamedatas.get("players") or {}

    color_by_pid: dict[str, str | None] = {
        str(pid): _color_name(p.get("color")) for pid, p in players.items()
    }
    scores = {
        color_by_pid[str(pid)]: int(p.get("score", 0))
        for pid, p in players.items()
        if color_by_pid.get(str(pid))
    }

    board = [[0] * _SIZE for _ in range(_SIZE)]
    for cell in _iter_board_cells(gamedatas.get("board") or []):
        pid = cell.get("player")
        if pid in (None, "", 0, "0"):
            continue
        color = color_by_pid.get(str(pid))
        if color is None:
            raise ObservationError(f"disc owned by unknown player {pid!r}")
        x, y = int(cell["x"]), int(cell["y"])
        board[y - 1][x - 1] = 1 if color == "black" else 2

    game_over = raw.get("gamestate_name") == "gameEnd"
    active_pid = raw.get("active_player")
    to_move = None if game_over else color_by_pid.get(str(active_pid)) if active_pid else None

    return {
        "game": "reversi",
        "board": board,
        "to_move": to_move,
        "game_over": game_over,
        "viewer_id": raw.get("player_id"),
        "viewer_color": color_by_pid.get(str(raw.get("player_id"))),
        "active_player": active_pid,
        "gamestate_name": raw.get("gamestate_name"),
        "table_id": raw.get("table_id"),
        "scores": scores,
        "logs": raw.get("logs", []),
    }


NORMALIZERS = {
    "reversi": normalize_reversi,
}


def normalize(game: str, raw: dict[str, Any]) -> Observation:
    try:
        normalizer = NORMALIZERS[game]
    except KeyError:
        raise ObservationError(f"no observation normalizer registered for game {game!r}")
    return normalizer(raw)
