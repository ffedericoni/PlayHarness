"""Observation: turn a live BGA table page into a normalized Observation dict.

Primary source is BGA's own client state (``window.gameui.gamedatas``) — the
structured data the server sends the client — which is far more reliable than
scraping pixels or CSS. The page is reloaded before each authoritative
snapshot because ``gamedatas`` is only guaranteed fresh at page load; BGA
fully supports refresh mid-game. The game log text is captured for the
Timeline, and a screenshot is the fallback when the structured path fails.

Normalized observations use the world-model conventions from
:mod:`playharness.model_api` (for Reversi: flat 64-cell board of
``"B"|"W"|None``, players 0=Black / 1=White) plus table metadata. The
model-facing projection is exactly ``model.observation(state, None)`` so BGA
timelines are replayable by the backtest.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

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


# -- Reversi glue ------------------------------------------------------------
#
# BGA's Reversi serves board cells as {x, y, player} with x = column 1..8 and
# y = row 1..8 from the top; player colors are hex ("000000" black, "ffffff"
# white). The world model's flat index is (y-1)*8 + (x-1), Black = player 0.


def _player_index(raw_color: str | None) -> int | None:
    if raw_color is None:
        return None
    color = str(raw_color).lstrip("#").lower()
    if color in ("000000", "000", "black"):
        return 0
    if color in ("ffffff", "fff", "white"):
        return 1
    return None


def _iter_board_cells(board_data: Any):
    """BGA ships the board as either a list of cells or a dict keyed by coordinate."""
    if isinstance(board_data, dict):
        yield from board_data.values()
    elif isinstance(board_data, list):
        yield from board_data
    else:
        raise ObservationError(f"unrecognized gamedatas.board shape: {type(board_data)}")


def normalize_reversi(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw snapshot of a BGA Reversi table into an Observation."""
    gamedatas = raw.get("gamedatas") or {}
    players = gamedatas.get("players") or {}

    index_by_pid: dict[str, int | None] = {
        str(pid): _player_index(p.get("color")) for pid, p in players.items()
    }
    scores_raw = {
        str(index_by_pid[str(pid)]): int(p.get("score", 0))
        for pid, p in players.items()
        if index_by_pid.get(str(pid)) is not None
    }

    board: list[str | None] = [None] * 64
    for cell in _iter_board_cells(gamedatas.get("board") or []):
        pid = cell.get("player")
        if pid in (None, "", 0, "0"):
            continue
        player = index_by_pid.get(str(pid))
        if player is None:
            raise ObservationError(f"disc owned by unknown player {pid!r}")
        x, y = int(cell["x"]), int(cell["y"])
        board[(y - 1) * 8 + (x - 1)] = "B" if player == 0 else "W"

    game_over = raw.get("gamestate_name") == "gameEnd"
    active_pid = raw.get("active_player")
    to_move = None if game_over else index_by_pid.get(str(active_pid)) if active_pid else None

    observation: dict[str, Any] = {
        "game": "reversi",
        "board": board,
        "to_move": to_move,
        "game_over": game_over,
        "viewer_id": raw.get("player_id"),
        "viewer_player": index_by_pid.get(str(raw.get("player_id"))),
        "active_player": active_pid,
        "gamestate_name": raw.get("gamestate_name"),
        "table_id": raw.get("table_id"),
        "scores_raw": scores_raw,  # BGA panel scores (disc counts)
        "logs": raw.get("logs", []),
    }
    if game_over:
        # Ground-truth final result in world-model terms (signed disc
        # differential), derived from the observed board — this is what a
        # Timeline "result" entry certifies score() against.
        black = sum(1 for v in board if v == "B")
        white = sum(1 for v in board if v == "W")
        observation["final_scores"] = {"0": float(black - white), "1": float(white - black)}
    return observation


def reversi_action_ui_vars(action: dict[str, Any]) -> dict[str, Any]:
    """Extra selector-template variables for a Reversi action (cell -> x/y)."""
    if action.get("type") == "place" and isinstance(action.get("cell"), int):
        cell = action["cell"]
        return {"x": cell % 8 + 1, "y": cell // 8 + 1}
    return {}


NORMALIZERS = {"reversi": normalize_reversi}
ACTION_UI_VARS = {"reversi": reversi_action_ui_vars}


def normalize(game: str, raw: dict[str, Any]) -> dict[str, Any]:
    try:
        normalizer = NORMALIZERS[game]
    except KeyError:
        raise ObservationError(f"no observation normalizer registered for game {game!r}")
    return normalizer(raw)


def action_ui_vars(game: str, action: dict[str, Any]) -> dict[str, Any]:
    return ACTION_UI_VARS.get(game, lambda a: {})(action)
