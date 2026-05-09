import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, TypeVar

from playwright.sync_api import BrowserContext, Page, sync_playwright

from ..models import CanonicalTx
from ..secrets.vault import Vault

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(frozen=True)
class ScrapingResult:
    transactions: list[CanonicalTx]
    period_start: date | None = None
    period_end: date | None = None
    balances: dict[str, tuple[Decimal, Decimal]] = field(default_factory=dict)


class ScrapingError(RuntimeError):
    error_code = "SCRAPING_ERROR"
    exit_code = 5

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class ScrapingLoginError(ScrapingError):
    error_code = "CREDENTIALS_REQUIRED"
    exit_code = 3


class ScrapingChallengeError(ScrapingError):
    error_code = "SCRAPING_CHALLENGE"


class ScrapingStructureError(ScrapingError):
    error_code = "SCRAPING_STRUCTURE_CHANGED"


class ScrapingTemporaryError(ScrapingError):
    error_code = "TEMPORARY_FAILURE"


class ScrapingBase:
    """Base class for headful scrapers using Playwright."""

    CHALLENGE_KEYWORDS = (
        "captcha",
        "recaptcha",
        "challenge",
        "desafio",
        "desafío",
        "verifica que no eres",
        "validacion adicional",
        "validación adicional",
    )

    def __init__(self, source_name: str, vault: Vault | None = None) -> None:
        self.source_name = source_name
        self.vault = vault or Vault()
        self.vault_key = f"storage_state_{source_name}"

    def get_storage_state(self) -> dict[str, Any] | None:
        """Retrieve storage state from vault."""
        return self.vault.get_json_secret(self.vault_key)

    def save_storage_state(self, context: BrowserContext) -> None:
        """Save storage state to vault."""
        state = context.storage_state()
        self.vault.set_secret(self.vault_key, state)
        logger.info(f"Storage state saved for {self.source_name}")

    def run_headful(self, action_fn: Callable[[Page, BrowserContext], T]) -> T:
        """Run a headful browser session and execute action_fn."""
        with sync_playwright() as p:
            # We enforce headless=False for transparency and anti-bot.
            browser = p.chromium.launch(headless=False)

            storage_state = self.get_storage_state()
            context_args: dict[str, Any] = {}
            if storage_state:
                context_args["storage_state"] = storage_state

            context = browser.new_context(**context_args)
            page = context.new_page()

            try:
                result = action_fn(page, context)
                # After action, we might want to save the state if it changed.
                # However, some scrapers might want to save it only on successful login.
                return result
            finally:
                browser.close()

    def wait_for_user_login(
        self,
        page: Page,
        login_url: str,
        success_indicator_selector: str,
        timeout_ms: int = 300000,
    ) -> bool:
        """
        Open login page and wait for user to complete login manually.
        Default timeout is 5 minutes.
        """
        if page.url != login_url:
            page.goto(login_url)

        logger.info(f"Waiting for manual login at {login_url}...")
        try:
            self.abort_if_blocked(page)
            page.wait_for_selector(success_indicator_selector, timeout=timeout_ms)
            self.abort_if_blocked(page)
            logger.info("Login detected!")
            return True
        except Exception as e:
            logger.error(f"Timeout waiting for login: {e}")
            return False

    def abort_if_blocked(self, page: Page) -> None:
        url = str(getattr(page, "url", ""))
        try:
            content = page.content()
        except Exception:
            content = ""
        haystack = f"{url}\n{content}".lower()
        if any(keyword in haystack for keyword in self.CHALLENGE_KEYWORDS):
            raise ScrapingChallengeError(
                f"{self.source_name} CAPTCHA or security challenge detected",
                details={"source": self.source_name},
            )
