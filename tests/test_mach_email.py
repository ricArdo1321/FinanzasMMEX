from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from finanzasmmex.adapters.mach_email import (
    MachEmailParseError,
    parse_purchase_email,
)

ROOT = Path(__file__).resolve().parents[1]


def test_parse_mach_purchase_fixture() -> None:
    fixture = (
        ROOT / "tests" / "fixtures" / "gmail" / "mach" / "mach_purchase_anonymized.txt"
    )
    raw_text = fixture.read_text(encoding="utf-8")

    tx = parse_purchase_email(raw_text, source_file=str(fixture))

    assert tx.owner == "ricardo"
    assert tx.source_type == "email"
    assert tx.source_file == str(fixture)
    assert tx.source_ref == "MCH-9988"
    assert tx.content_sha256
    assert tx.raw_text == raw_text
    assert tx.event_date == date(2026, 5, 1)
    assert tx.posted_date == date(2026, 5, 1)
    assert tx.amount == Decimal("7500.00")
    assert tx.currency == "CLP"
    assert tx.direction == "debit"
    assert tx.card_last4 == "4242"
    assert tx.account_alias == "MACH_Ricardo_4242"
    assert tx.merchant_raw == "COMERCIO MACH DEMO"
    assert tx.merchant_norm == "COMERCIO MACH DEMO"
    assert tx.tx_type == "purchase"
    assert tx.parser_name == "mach_email_v1"
    assert tx.parser_version == "1.0"
    assert tx.fitid_synthetic is None
    assert tx.needs_review is False
    assert tx.review_reason is None


def test_owner_changes_account_alias() -> None:
    raw_text = (
        "Pagaste CLP $7.500 en COMERCIO MACH DEMO.\n"
        "Fecha: 01/05/2026 09:15.\n"
        "Tarjeta Mach **** 4242.\n"
        "ID transaccion: MCH-9988.\n"
    )
    tx = parse_purchase_email(raw_text, owner="laura")
    assert tx.account_alias == "MACH_Laura_4242"


def test_implicit_currency_marks_review() -> None:
    raw_text = (
        "Pagaste $7.500 en COMERCIO MACH DEMO.\n"
        "Fecha: 01/05/2026 09:15.\n"
        "Tarjeta Mach **** 4242.\n"
        "ID transaccion: MCH-9988.\n"
    )
    tx = parse_purchase_email(raw_text)
    assert tx.needs_review is True
    assert "currency_implicit" in str(tx.review_reason)


def test_merchant_with_period_in_name_keeps_full_name() -> None:
    raw_text = (
        "Pagaste CLP $7.500 en SERVICIOS S.A. DEMO.\n"
        "Fecha: 01/05/2026 09:15.\n"
        "Tarjeta Mach **** 4242.\n"
        "ID transaccion: MCH-9988.\n"
    )
    tx = parse_purchase_email(raw_text)
    assert tx.merchant_raw == "SERVICIOS S.A. DEMO"


def test_missing_amount_raises_parse_error() -> None:
    raw_text = (
        "Compraste en COMERCIO MACH DEMO.\n"
        "Fecha: 01/05/2026 09:15.\n"
        "Tarjeta Mach **** 4242.\n"
    )
    with pytest.raises(MachEmailParseError):
        parse_purchase_email(raw_text)


def test_missing_card_last4_raises_parse_error() -> None:
    raw_text = "Pagaste $7.500 en COMERCIO MACH DEMO.\n" "Fecha: 01/05/2026 09:15.\n"
    with pytest.raises(MachEmailParseError):
        parse_purchase_email(raw_text)


def test_missing_tx_id_marks_partial_extraction() -> None:
    raw_text = (
        "Pagaste CLP $7.500 en COMERCIO MACH DEMO.\n"
        "Fecha: 01/05/2026 09:15.\n"
        "Tarjeta Mach **** 4242.\n"
    )
    tx = parse_purchase_email(raw_text)
    assert tx.needs_review is True
    assert "partial_extraction:tx_id" in str(tx.review_reason)


def test_alternate_date_format_iso_supported() -> None:
    raw_text = (
        "Pagaste CLP $7.500 en COMERCIO MACH DEMO.\n"
        "Fecha: 2026-05-01 09:15.\n"
        "Tarjeta Mach **** 4242.\n"
        "ID transaccion: MCH-9988.\n"
    )
    tx = parse_purchase_email(raw_text)
    assert tx.event_date == date(2026, 5, 1)


def test_multiple_distinct_cards_marks_review() -> None:
    raw_text = (
        "Pagaste CLP $7.500 en COMERCIO MACH DEMO.\n"
        "Fecha: 01/05/2026 09:15.\n"
        "Tarjeta Mach **** 9876.\n"
        "Referencia tarjeta Mach **** 1234.\n"
        "ID transaccion: MCH-9988.\n"
    )

    tx = parse_purchase_email(raw_text)

    assert tx.account_alias == "MACH_Ricardo_9876"
    assert tx.needs_review is True
    assert "card_ambiguous" in str(tx.review_reason)
