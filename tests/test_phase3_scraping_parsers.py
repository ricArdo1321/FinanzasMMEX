from html.parser import HTMLParser
from pathlib import Path

from finanzasmmex.adapters.be_scraping import BancoEstadoScraper
from finanzasmmex.adapters.cmr_scraping import CMRScraper

ROOT = Path(__file__).resolve().parents[1]


class _CellParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tr":
            self._current_row = []
        elif tag == "td":
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._current_cell is not None:
            if self._current_row is not None:
                self._current_row.append("".join(self._current_cell).strip())
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None:
            if self._current_row:
                self.rows.append(self._current_row)
            self._current_row = None


def _first_fixture_row(path: Path) -> list[str]:
    parser = _CellParser()
    parser.feed(path.read_text(encoding="utf-8"))
    assert parser.rows
    return parser.rows[0]


def test_be_scraping_fixture_populates_canonical_fields() -> None:
    row = _first_fixture_row(
        ROOT / "tests" / "fixtures" / "scraping" / "be_movements_anonymized.html"
    )

    tx = BancoEstadoScraper(vault=None)._parse_row(
        row,
        since=__import__("datetime").date(2026, 1, 1),
        content_sha256="a" * 64,
    )

    assert tx is not None
    assert tx.amount.is_signed() is False
    assert tx.direction == "debit"
    assert tx.account_alias == "BE_Ricardo_RUT"
    assert tx.parser_name == "be_scraping_v1"
    assert tx.parser_version == "1.0"
    assert tx.posted_date is not None


def test_cmr_scraping_fixture_populates_canonical_fields() -> None:
    row = _first_fixture_row(
        ROOT / "tests" / "fixtures" / "scraping" / "cmr_movements_anonymized.html"
    )

    tx = CMRScraper(vault=None)._parse_row(
        row,
        since=__import__("datetime").date(2026, 1, 1),
        content_sha256="b" * 64,
    )

    assert tx is not None
    assert tx.amount.is_signed() is False
    assert tx.direction == "debit"
    assert tx.account_alias == "CMR_Ricardo"
    assert tx.parser_name == "cmr_scraping_v1"
    assert tx.parser_version == "1.0"
    assert tx.posted_date is not None
