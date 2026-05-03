from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from finanzasmmex.etl.fitid import compute_fitid, ensure_fitid
from finanzasmmex.etl.normalize import normalize_merchant, parse_clp_amount
from finanzasmmex.models import CanonicalTx


def test_parse_clp_amount_normalizes_common_formats() -> None:
    assert parse_clp_amount("$12.340") == Decimal("12340.00")
    assert parse_clp_amount("CLP 1 234") == Decimal("1234.00")
    assert parse_clp_amount(500) == Decimal("500.00")


def test_parse_clp_amount_rejects_invalid_or_zero() -> None:
    with pytest.raises(ValueError):
        parse_clp_amount("sin monto")
    with pytest.raises(ValueError):
        parse_clp_amount("$0")


def test_normalize_merchant_is_ascii_uppercase() -> None:
    assert normalize_merchant("Café Demo   Ñuñoa") == "CAFE DEMO NUNOA"


def test_fitid_is_stable_and_uses_canonical_fields() -> None:
    tx = CanonicalTx(
        owner="ricardo",
        source_type="email",
        content_sha256="abc",
        event_date=date(2026, 5, 2),
        amount=Decimal("12340.00"),
        direction="debit",
        account_alias="BE_Ricardo_1234",
        merchant_raw="Comercio Demo",
        merchant_norm="COMERCIO DEMO",
        tx_type="purchase",
        parser_name="be_email_v1",
        parser_version="1.0",
    )

    assert compute_fitid(tx) == compute_fitid(replace(tx, raw_text="changed"))
    assert compute_fitid(tx) != compute_fitid(replace(tx, amount=Decimal("999.00")))

    enriched = ensure_fitid(tx)
    assert enriched.fitid_synthetic == compute_fitid(tx)
    assert tx.fitid_synthetic is None
