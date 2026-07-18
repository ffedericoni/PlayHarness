"""Playwright browser session against BoardGameArena: launch, login, persistence.

The session state (cookies) is persisted to ``storage_state_path`` so repeated
runs don't re-authenticate — BGA rate-limits and flags frequent logins.

Compliance: this adapter is for research use against solo/training modes and
unrated tables only. Do not point it at ranked/arena play or tables with
non-consenting opponents (see IMPLEMENTATION_PLAN.md §3.3).
"""

from __future__ import annotations

import logging

from .config import BGAConfig

logger = logging.getLogger(__name__)


class LoginError(Exception):
    pass


class BGASession:
    """Owns the Playwright browser/context/page. Use as a context manager."""

    def __init__(self, config: BGAConfig | None = None):
        self.config = config or BGAConfig.from_env()
        self._playwright = None
        self.browser = None
        self.context = None
        self.page = None

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> "BGASession":
        from playwright.sync_api import sync_playwright  # lazy: offline tests don't need it

        self._playwright = sync_playwright().start()
        launch_kwargs: dict = {
            "headless": self.config.headless,
            "slow_mo": self.config.slow_mo_ms,
        }
        if self.config.chromium_path:
            launch_kwargs["executable_path"] = self.config.chromium_path
        self.browser = self._playwright.chromium.launch(**launch_kwargs)

        context_kwargs: dict = {}
        if self.config.storage_state_path.exists():
            context_kwargs["storage_state"] = str(self.config.storage_state_path)
        self.context = self.browser.new_context(**context_kwargs)
        self.page = self.context.new_page()
        return self

    def close(self) -> None:
        for closer in (self.context, self.browser):
            try:
                if closer:
                    closer.close()
            except Exception:
                pass
        if self._playwright:
            self._playwright.stop()
        self._playwright = self.browser = self.context = self.page = None

    def __enter__(self) -> "BGASession":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.close()

    def save_storage_state(self) -> None:
        assert self.context
        self.config.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.context.storage_state(path=str(self.config.storage_state_path))

    # -- auth ----------------------------------------------------------------

    def _first_visible(self, selectors: tuple[str, ...]):
        assert self.page
        for selector in selectors:
            locator = self.page.locator(selector).first
            try:
                if locator.is_visible():
                    return locator
            except Exception:
                continue
        return None

    def is_logged_in(self) -> bool:
        assert self.page
        self.page.goto(self.config.base_url + "/", wait_until="domcontentloaded")
        return self._first_visible(self.config.logged_in_selectors) is not None

    def ensure_logged_in(self) -> None:
        if self.is_logged_in():
            logger.info("already logged in (persisted session)")
            return
        self.login()

    def login(self) -> None:
        """Log in with BGA_EMAIL/BGA_PASSWORD, handling one- and two-step forms."""
        cfg = self.config
        if not cfg.email or not cfg.password:
            raise LoginError("BGA_EMAIL and BGA_PASSWORD must be set (no saved session found)")
        assert self.page
        page = self.page
        page.goto(cfg.base_url + cfg.login_url_path, wait_until="domcontentloaded")

        username = self._first_visible(cfg.username_selectors)
        if username is None:
            if self._first_visible(cfg.logged_in_selectors):
                return  # /account redirected: already authenticated
            raise LoginError(
                "could not find the login form; update BGAConfig.username_selectors "
                "(run `playharness bga-probe` with BGA_HEADLESS=0 to inspect the page)"
            )
        username.fill(cfg.email)

        password = self._first_visible(cfg.password_selectors)
        if password is None:
            # Two-step form: submit the email first, then the password appears.
            submit = self._first_visible(cfg.submit_selectors)
            if submit is None:
                raise LoginError("no password field and no submit/continue button found")
            submit.click()
            page.wait_for_timeout(1500)
            password = self._first_visible(cfg.password_selectors)
            if password is None:
                raise LoginError("password field did not appear after submitting email")
        password.fill(cfg.password)

        submit = self._first_visible(cfg.submit_selectors)
        if submit is None:
            raise LoginError("no submit button found on the login form")
        submit.click()
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(2000)

        if not self.is_logged_in():
            raise LoginError("login submitted but no logged-in marker found; check credentials")
        self.save_storage_state()
        logger.info("logged in and saved session to %s", cfg.storage_state_path)
