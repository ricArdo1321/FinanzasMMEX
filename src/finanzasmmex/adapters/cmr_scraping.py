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


class CMRScraper(ScrapingBase):
    """Headful scraper for CMR Falabella."""

    LOGIN_URL = "https://www.bancofalabella.cl"
    DASHBOARD_INDICATOR = ".bienvenida, .resumen-cuentas, #btn-cerrar-sesion"

    def __init__(self, vault: Vault | None = None) -> None:
        super().__init__(source_name="cmr", vault=vault)

    def scrape(self, since: date) -> list[CanonicalTx]:
        """Execute the scraping flow."""
        return self.run_headful(lambda p, c: self._execute_scrape(p, c, since))

    def _execute_scrape(
        self, page: Page, context: BrowserContext, since: date
    ) -> list[CanonicalTx]:
        page.goto(self.LOGIN_URL)
        self.abort_if_blocked(page)

        if not self._is_logged_in(page):
            logger.warning("Waiting for manual CMR login in the browser")
            if not self.wait_for_user_login(
                page, self.LOGIN_URL, self.DASHBOARD_INDICATOR
            ):
                raise ScrapingLoginError(
                    "CMR login was not completed",
                    details={"source": "cmr"},
                )

            self.save_storage_state(context)
        self.abort_if_blocked(page)

        logger.info("Navigating to CMR movements...")
        try:
            page.get_by_role("link", name="Tarjetas").click()
            page.get_by_role("link", name="Movimientos").click()
        except Exception as e:
            logger.warning(f"Standard CMR navigation failed: {e}")

        table_selector = ".tabla-movimientos, table.movimientos, #movimientos-cmr"
        try:
            page.wait_for_selector(table_selector, timeout=30000)
        except Exception as e:
            self.abort_if_blocked(page)
            raise ScrapingStructureError(
                "CMR movements table not found",
                details={"source": "cmr", "selector": table_selector},
            ) from e

        rows = page.query_selector_all(f"{table_selector} tr")
        txs = []
        for row in rows:
            cells = row.query_selector_all("td")
            if not cells or len(cells) < 3:
                continue

            texts = [c.inner_text().strip() for c in cells]
            raw_text = "|".join(texts)
            content_sha256 = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

            try:
                tx = self._parse_row(texts, since, content_sha256)
                if tx:
                    txs.append(tx)
            except Exception as e:
                logger.warning(f"Failed to parse CMR row {texts}: {e}")

        logger.info(f"Extracted {len(txs)} transactions from CMR Falabella")
        return txs

    def _parse_row(
        self, cells: list[str], since: date, content_sha256: str
    ) -> CanonicalTx | None:
        """Parses a CMR row."""
        if not cells or len(cells) < 3:
            return None

        raw_date = cells[0]
        raw_desc = cells[1]

        amount_str = cells[2]
        direction: Literal["debit", "credit"] = "debit"

        try:
            posted_date = self._parse_cmr_date(raw_date)
            if posted_date < since:
                return None

            # Check for separate Abono column
            if len(cells) >= 4 and cells[3].strip():
                abono_str = cells[3]
                is_abono = any(c.isdigit() for c in abono_str)
                if is_abono:
                    amount = parse_clp_amount(abono_str)
                    direction = "credit"
                else:
                    amount = parse_clp_amount(amount_str)
            else:
                amount = parse_clp_amount(amount_str)
                # If negative sign present in single column
                if "-" in amount_str or "(" in amount_str:
                    direction = "debit"

            abs_amount = abs(amount)

            return CanonicalTx(
                tx_uid=str(uuid4()),
                owner="ricardo",
                source_type="scraping",
                source_file=None,
                source_ref=f"cmr_scrape_{posted_date}_{raw_desc[:20]}",
                raw_text="|".join(cells),
                content_sha256=content_sha256,
                event_date=posted_date,
                posted_date=posted_date,
                amount=abs_amount,
                currency="CLP",
                direction=direction,
                account_alias="CMR_Ricardo",
                merchant_raw=raw_desc,
                tx_type="purchase" if direction == "debit" else "refund",
                parser_name="cmr_scraping_v1",
                parser_version="1.0",
                needs_review=False,
            )
        except Exception:
            return None

    def _parse_cmr_date(self, raw: str) -> date:
        for fmt in ("%d/%m/%Y", "%d %b %Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Unknown CMR date format: {raw}")

    def _is_logged_in(self, page: Page) -> bool:
        try:
            page.wait_for_selector(self.DASHBOARD_INDICATOR, timeout=5000)
            return True
        except Exception:
            return False
