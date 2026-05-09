import hashlib
import logging
from datetime import date, datetime
from typing import Literal
from uuid import uuid4

from playwright.sync_api import BrowserContext, Page

from ..etl.normalize import parse_clp_amount
from ..models import CanonicalTx
from ..secrets.vault import Vault
from .scraping_base import ScrapingBase, ScrapingLoginError, ScrapingStructureError

logger = logging.getLogger(__name__)


class BancoEstadoScraper(ScrapingBase):
    """Headful scraper for BancoEstado."""

    LOGIN_URL = "https://www.bancoestado.cl"
    DASHBOARD_INDICATOR = ".dashboard-main, .menu-principal, #btn-logout"
    MOVIMIENTOS_URL = "https://www.bancoestado.cl/movimientos"

    def __init__(self, vault: Vault | None = None) -> None:
        super().__init__(source_name="be", vault=vault)

    def scrape(self, since: date) -> list[CanonicalTx]:
        """Execute the scraping flow."""
        return self.run_headful(lambda p, c: self._execute_scrape(p, c, since))

    def _execute_scrape(
        self, page: Page, context: BrowserContext, since: date
    ) -> list[CanonicalTx]:
        page.goto(self.LOGIN_URL)
        self.abort_if_blocked(page)

        # Check if already logged in via storage state
        if not self._is_logged_in(page):
            logger.warning("Waiting for manual BancoEstado login in the browser")
            if not self.wait_for_user_login(
                page, self.LOGIN_URL, self.DASHBOARD_INDICATOR
            ):
                raise ScrapingLoginError(
                    "BancoEstado login was not completed",
                    details={"source": "be"},
                )

            # Save the fresh state
            self.save_storage_state(context)
        self.abort_if_blocked(page)

        logger.info("Navigating to movements section...")
        try:
            # Common patterns for Chilean bank menus
            page.get_by_role("link", name="Cuentas").click()
            page.get_by_role("link", name="Movimientos").click()
        except Exception as e:
            logger.warning(f"Standard navigation failed, trying alternative: {e}")

        # Wait for the movements table to appear
        table_selector = "table.movimientos, #tablaMovimientos, .cartola-table"
        try:
            page.wait_for_selector(table_selector, timeout=30000)
        except Exception as e:
            self.abort_if_blocked(page)
            raise ScrapingStructureError(
                "BancoEstado movements table not found",
                details={"source": "be", "selector": table_selector},
            ) from e

        # Parse the table
        rows = page.query_selector_all(f"{table_selector} tr")
        txs = []
        for row in rows:
            cells = row.query_selector_all("td")
            if not cells or len(cells) < 3:
                continue

            # Extract basic text from cells
            texts = [c.inner_text().strip() for c in cells]
            raw_text = "|".join(texts)
            content_sha256 = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

            try:
                tx = self._parse_row(texts, since, content_sha256)
                if tx:
                    txs.append(tx)
            except Exception as e:
                logger.warning(f"Failed to parse row {texts}: {e}")

        logger.info(f"Extracted {len(txs)} transactions from BancoEstado")
        return txs

    def _parse_row(
        self, cells: list[str], since: date, content_sha256: str
    ) -> CanonicalTx | None:
        """Parses a single row of the movements table."""
        if not cells or len(cells) < 3:
            return None

        raw_date = cells[0]
        raw_desc = cells[1]

        amount_str = ""
        if len(cells) >= 5:
            amount_str = cells[3]
        elif len(cells) >= 3:
            # Sometimes last column is amount
            amount_str = cells[-1]

        try:
            posted_date = self._parse_be_date(raw_date)
            if posted_date < since:
                return None

            # Fix: Check for sign BEFORE parse_clp_amount
            is_negative = "-" in amount_str or "(" in amount_str
            amount = parse_clp_amount(amount_str)
            direction: Literal["debit", "credit"] = (
                "debit" if is_negative else "credit"
            )
            abs_amount = abs(amount)

            return CanonicalTx(
                tx_uid=str(uuid4()),
                owner="ricardo",
                source_type="scraping",
                source_file=None,
                source_ref=f"be_scrape_{posted_date}_{raw_desc[:20]}",
                raw_text="|".join(cells),
                content_sha256=content_sha256,
                event_date=posted_date,
                posted_date=posted_date,
                amount=abs_amount,
                currency="CLP",
                direction=direction,
                account_alias="BE_Ricardo_RUT",
                merchant_raw=raw_desc,
                tx_type="purchase" if direction == "debit" else "transfer_in",
                parser_name="be_scraping_v1",
                parser_version="1.0",
                needs_review=False,
            )
        except Exception:
            return None

    def _parse_be_date(self, raw: str) -> date:
        today = date.today()
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue

        try:
            dt = datetime.strptime(f"{raw}/{today.year}", "%d/%m/%Y").date()
            if dt.month == 12 and today.month == 1:
                dt = dt.replace(year=today.year - 1)
            return dt
        except ValueError as exc:
            raise ValueError(f"Unknown date format: {raw}") from exc

    def _is_logged_in(self, page: Page) -> bool:
        try:
            page.wait_for_selector(self.DASHBOARD_INDICATOR, timeout=5000)
            return True
        except Exception:
            return False
