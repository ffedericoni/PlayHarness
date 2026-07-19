"""UI map: the per-game association between model-level actions and DOM selectors.

Stored at ``games/<game>/ui_map.json`` and reused across sessions. Selector
templates contain ``{field}`` placeholders filled from the action dict, e.g.
``"#square_{x}_{y}"`` with ``{"type": "play_disc", "x": 4, "y": 3}`` becomes
``#square_4_3``. Keeping the mapping in data (not code) is what lets the agent
build and repair it interactively when a game's UI drifts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typing import Any

Action = dict[str, Any]


class UIMapError(Exception):
    pass


class UIMap:
    def __init__(self, data: dict[str, Any]):
        self.data = data

    @classmethod
    def load(cls, path: str | Path) -> "UIMap":
        path = Path(path)
        if not path.exists():
            raise UIMapError(f"UI map not found: {path}")
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.data, indent=2) + "\n", encoding="utf-8")

    @property
    def game(self) -> str:
        return self.data.get("game", "?")

    def selector_for(self, action: Action, extra_vars: dict[str, Any] | None = None) -> tuple[str, str]:
        """Resolve an action to ``(selector, method)``. Raises UIMapError if unmapped.

        ``extra_vars`` supplies derived template variables the action itself
        doesn't carry (e.g. Reversi's flat ``cell`` index expanded to the
        ``x``/``y`` BGA uses in its square ids).
        """
        action_type = action.get("type")
        spec = (self.data.get("actions") or {}).get(action_type)
        if spec is None:
            raise UIMapError(f"no UI mapping for action type {action_type!r} in game {self.game!r}")
        template_vars = {**action, **(extra_vars or {})}
        try:
            selector = spec["selector"].format(**template_vars)
        except KeyError as e:
            raise UIMapError(f"action {action} missing field {e} required by selector template")
        return selector, spec.get("method", "click")

    def confirm_selectors(self) -> list[str]:
        """Selectors for post-action confirmation dialogs ("Are you sure?"), if any."""
        return list((self.data.get("confirm") or {}).get("selectors", []))
