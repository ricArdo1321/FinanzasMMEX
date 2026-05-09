from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.finanzasmmex.etl.merge import merge_scraped_txs
from src.finanzasmmex.models import CanonicalTx
from src.finanzasmmex.staging.repo import StagingRepo


@pytest.fixture
def repo():
    return MagicMock(spec=StagingRepo)

def test_merge_scraped_txs_exact_match(repo):
    # Transaction already in staging (from email)
    existing_tx = CanonicalTx(
        tx_uid="uuid-email",
        owner="ricardo",
        source_type="email",
        source_file="msg-1",
        source_ref="12345",
        raw_text="email content",
        content_sha256="sha1",
        event_date=date(2026, 5, 1),
        posted_date=date(2026, 5, 2),
        amount=Decimal("1000.00"),
        currency="CLP",
        direction="debit",
        account_alias="BE_RUT",
        merchant_raw="SUPERMERCADO LIDER",
        merchant_norm="SUPERMERCADO LIDER",
        tx_type="purchase",
        parser_name="be_email",
        parser_version="1.0",
        needs_review=False,
    )

    repo.list_txs.return_value = [existing_tx]

    # Transaction from scraping (same amount, exact name)
    scraped_tx = CanonicalTx(
        tx_uid="uuid-scrape",
        owner="ricardo",
        source_type="scraping",
        source_file=None,
        source_ref="scrape-ref",
        raw_text="row content",
        content_sha256="sha2",
        event_date=date(2026, 5, 1),
        posted_date=date(2026, 5, 1), # Different posted date
        amount=Decimal("1000.00"),
        currency="CLP",
        direction="debit",
        account_alias="BE_RUT",
        merchant_raw="SUPERMERCADO LIDER",
        merchant_norm=None,
        tx_type="purchase",
        parser_name="be_scraper",
        parser_version="1.0",
        needs_review=False,
    )

    results = merge_scraped_txs(repo, [scraped_tx])

    assert len(results) == 1
    merged = results[0]
    assert merged.tx_uid == "uuid-email"  # Kept existing identity
    assert merged.posted_date == date(2026, 5, 1) # Updated from scrape
    assert "scrape-ref" in merged.source_ref # Enriched

def test_merge_scraped_txs_no_match(repo):
    repo.list_txs.return_value = []

    scraped_tx = CanonicalTx(
        tx_uid="uuid-scrape",
        owner="ricardo",
        source_type="scraping",
        source_file=None,
        source_ref="scrape-ref",
        raw_text="row content",
        content_sha256="sha2",
        event_date=date(2026, 5, 1),
        posted_date=date(2026, 5, 1),
        amount=Decimal("5000.00"),
        currency="CLP",
        direction="debit",
        account_alias="BE_RUT",
        merchant_raw="NUEVO COMERCIO",
        merchant_norm=None,
        tx_type="purchase",
        parser_name="be_scraper",
        parser_version="1.0",
        needs_review=False,
    )

    results = merge_scraped_txs(repo, [scraped_tx])

    assert len(results) == 1
    assert results[0].tx_uid == "uuid-scrape" # New identity
