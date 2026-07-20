"""Playwright browser session against BoardGameArena: launch, login, persistence.

The session state (cookies) is persisted to ``storage_state_path`` so repeated
runs don't re-authenticate — BGA rate-limits and flags frequent logins.

Compliance: this adapter is for research use against solo/training modes and
unrated tables only. Do not point it at ranked/arena play or tables with
non-consenting opponents (see IMPLEMENTATION_PLAN.md §3.3).
"""

from __future__ import annotations

import logging
import os

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
        args = []
        if os.geteuid() == 0:
            args.append("--no-sandbox")  # Chromium refuses its sandbox as root
        launch_kwargs: dict = {
            "headless": self.config.headless,
            "slow_mo": self.config.slow_mo_ms,
            "args": args,
        }
        if self.config.chromium_path:
            launch_kwargs["executable_path"] = self.config.chromium_path
        # Chromium does not reliably honor proxy env vars on its own; managed
        # environments (e.g. Claude Code remote) route egress through one.
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if proxy:
            launch_kwargs["proxy"] = {"server": proxy}
            # TLS-terminating egress gateways commonly reset Chrome's TLS 1.3
            # ClientHello (hybrid ML-KEM key share makes it multi-record);
            # capping at 1.2 for the proxy hop keeps the handshake accepted.
            args.append("--ssl-version-max=tls1.2")
        self.browser = self._playwright.chromium.launch(**launch_kwargs)

        context_kwargs: dict = {}
        if self.config.storage_state_path.exists():
            context_kwargs["storage_state"] = str(self.config.storage_state_path)
        self.context = self.browser.new_context(**context_kwargs)
        self._pin_language_host()
        self.page = self.context.new_page()
        return self

    def _pin_language_host(self) -> None:
        """Rewrite direct www/apex navigations onto the base_url subdomain.

        Note this cannot defeat BGA's own server-side canonical redirect (the
        logged-in site lives on the apex domain), so egress policies must
        allow ``boardgamearena.com`` itself — this rewrite only smooths over
        stray links when a subdomain base_url is configured.
        """
        from urllib.parse import urlsplit

        host = urlsplit(self.config.base_url).hostname or ""
        if not host.endswith("boardgamearena.com") or host == "boardgamearena.com":
            return

        def rewrite_request(route):
            new = route.request.url.replace("://www.boardgamearena.com", f"://{host}").replace(
                "://boardgamearena.com", f"://{host}"
            )
            if new != route.request.url:
                route.fulfill(status=302, headers={"location": new})
            else:
                route.fallback()

        for pattern in ("**://boardgamearena.com/**", "**://www.boardgamearena.com/**"):
            self.context.route(pattern, rewrite_request)

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
            if submit is not None:
                submit.click()
            else:
                username.press("Enter")
            page.wait_for_timeout(3000)
            password = self._first_visible(cfg.password_selectors)
            if password is None:
                raise LoginError("password field did not appear after submitting email")
        password.fill(cfg.password)

        submit = self._first_visible(cfg.submit_selectors)
        if submit is not None:
            submit.click()
        else:
            password.press("Enter")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(4000)

        if not self.is_logged_in():
            raise LoginError("login submitted but no logged-in marker found; check credentials")
        self.save_storage_state()
        logger.info("logged in and saved session to %s", cfg.storage_state_path)
