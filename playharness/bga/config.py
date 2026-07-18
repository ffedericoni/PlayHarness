"""Configuration for the BGA adapter. Credentials come from the environment only.

Environment variables:
- ``BGA_EMAIL`` / ``BGA_PASSWORD`` — account credentials (never stored in the repo)
- ``BGA_BASE_URL`` — defaults to https://boardgamearena.com
- ``BGA_STORAGE_STATE`` — path for the persisted browser session
  (defaults to ~/.playharness/bga_storage_state.json)
- ``BGA_HEADLESS`` — "0" to watch the browser (default headless)
- ``BGA_CHROMIUM_PATH`` — explicit Chromium executable, for environments where
  Playwright's managed download is unavailable
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BGAConfig:
    base_url: str = "https://boardgamearena.com"
    email: str | None = None
    password: str | None = None
    storage_state_path: Path = field(
        default_factory=lambda: Path.home() / ".playharness" / "bga_storage_state.json"
    )
    headless: bool = True
    slow_mo_ms: int = 0
    chromium_path: str | None = None
    # Candidate selectors, first visible wins. BGA redesigns its login page
    # periodically; adjust here rather than in code.
    login_url_path: str = "/account"
    username_selectors: tuple[str, ...] = (
        "#username_input",
        "input[name='email']",
        "input[type='email']",
        "input[name='username']",
    )
    password_selectors: tuple[str, ...] = (
        "#password_input",
        "input[name='password']",
        "input[type='password']",
    )
    submit_selectors: tuple[str, ...] = (
        "#login_button",
        "#submit_login_button",
        "button[type='submit']",
        "input[type='submit']",
    )
    logged_in_selectors: tuple[str, ...] = (
        "a[href*='logout']",
        "#connected_username",
        ".connected_username",
    )

    @classmethod
    def from_env(cls) -> "BGAConfig":
        cfg = cls()
        cfg.base_url = os.environ.get("BGA_BASE_URL", cfg.base_url).rstrip("/")
        cfg.email = os.environ.get("BGA_EMAIL")
        cfg.password = os.environ.get("BGA_PASSWORD")
        if os.environ.get("BGA_STORAGE_STATE"):
            cfg.storage_state_path = Path(os.environ["BGA_STORAGE_STATE"])
        cfg.headless = os.environ.get("BGA_HEADLESS", "1") != "0"
        cfg.chromium_path = os.environ.get("BGA_CHROMIUM_PATH")
        return cfg
