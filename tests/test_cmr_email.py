from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from finanzasmmex.adapters.cmr_email import (
    CmrEmailParseError,
    parse_purchase_email,
)

ROOT = Path(__file__).resolve().parents[1]


def test_parse_cmr_purchase_fixture() -> None:
    fixture = (
        ROOT / "tests" / "fixtures" / "gmail" / "cmr" / "cmr_purchase_anonymized.txt"
    )
    raw_text = fixture.read_text(encoding="utf-8")

    tx = parse_purchase_email(raw_text, source_file=str(fixture))

    assert tx.owner == "ricardo"
    assert tx.source_type == "email"
    assert tx.source_file == str(fixture)
    assert tx.source_ref == "OP-998877"
    assert tx.content_sha256
    assert tx.raw_text == raw_text
    assert tx.event_date == date(2026, 5, 2)
    assert tx.posted_date == date(2026, 5, 2)
    assert tx.amount == Decimal("25990.00")
    assert tx.currency == "CLP"
    assert tx.direction == "debit"
    assert tx.card_last4 == "5678"
    assert tx.account_alias == "CMR_Ricardo_5678"
    assert tx.merchant_raw == "TIENDA DEMO"
    assert tx.merchant_norm == "TIENDA DEMO"
    assert tx.tx_type == "purchase"
    assert tx.parser_name == "cmr_email_v1"
    assert tx.parser_version == "1.0"
    assert tx.fitid_synthetic is None
    assert tx.needs_review is False
    assert tx.review_reason is None


def test_owner_changes_account_alias() -> None:
    raw_text = (
        "Compra por CLP $25.990 en TIENDA DEMO el 02/05/2026 14:25.\n"
        "Tarjeta CMR terminada en 5678.\n"
        "Cuotas: 1 sin interes.\n"
        "Numero de operacion: OP-998877.\n"
    )
    tx = parse_purchase_email(raw_text, owner="laura")
    assert tx.account_alias == "CMR_Laura_5678"


def test_implicit_currency_marks_review() -> None:
    raw_text = (
        "Compra por $25.990 en TIENDA DEMO el 02/05/2026 14:25.\n"
        "Tarjeta CMR terminada en 5678.\n"
        "Cuotas: 1 sin interes.\n"
        "Numero de operacion: OP-998877.\n"
    )
    tx = parse_purchase_email(raw_text)
    assert tx.needs_review is True
    assert "currency_implicit" in str(tx.review_reason)


def test_installment_purchase_flags_needs_review() -> None:
    raw_text = (
        "Compra por CLP $120.000 en TIENDA DEMO el 02/05/2026 14:25.\n"
        "Tarjeta CMR terminada en 5678.\n"
        "Cuotas: 6 sin interes.\n"
        "Numero de operacion: OP-998877.\n"
    )
    tx = parse_purchase_email(raw_text)
    assert tx.needs_review is True
    assert "installments" in str(tx.review_reason)


def test_missing_amount_raises_parse_error() -> None:
    raw_text = (
        "Compra realizada en TIENDA DEMO el 02/05/2026.\n"
        "Tarjeta CMR terminada en 5678.\n"
    )
    with pytest.raises(CmrEmailParseError):
        parse_purchase_email(raw_text)


def test_missing_card_last4_raises_parse_error() -> None:
    raw_text = (
        "Compra por $25.990 en TIENDA DEMO el 02/05/2026 14:25.\n"
        "Numero de operacion: OP-998877.\n"
    )
    with pytest.raises(CmrEmailParseError):
        parse_purchase_email(raw_text)


def test_missing_operation_number_marks_partial_extraction() -> None:
    raw_text = (
        "Compra por CLP $25.990 en TIENDA DEMO el 02/05/2026 14:25.\n"
        "Tarjeta CMR terminada en 5678.\n"
        "Cuotas: 1 sin interes.\n"
    )
    tx = parse_purchase_email(raw_text)
    assert tx.needs_review is True
    assert "partial_extraction:operation_number" in str(tx.review_reason)
