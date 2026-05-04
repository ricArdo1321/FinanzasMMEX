from datetime import date
from decimal import Decimal
from pathlib import Path

from finanzasmmex.adapters.be_email import parse_purchase_email

ROOT = Path(__file__).resolve().parents[1]


def test_parse_bancoestado_purchase_fixture() -> None:
    fixture = ROOT / "tests" / "fixtures" / "gmail" / "be_purchase_anonymized.txt"
    raw_text = fixture.read_text(encoding="utf-8")

    tx = parse_purchase_email(raw_text, source_file=str(fixture))

    assert tx.owner == "ricardo"
    assert tx.source_type == "email"
    assert tx.source_file == str(fixture)
    assert tx.source_ref == "TEST-A1"
    assert tx.content_sha256
    assert tx.raw_text == raw_text
    assert tx.event_date == date(2026, 5, 2)
    assert tx.posted_date == date(2026, 5, 2)
    assert tx.amount == Decimal("12340.00")
    assert tx.currency == "CLP"
    assert tx.direction == "debit"
    assert tx.account_alias == "BE_Ricardo_1234"
    assert tx.merchant_raw == "COMERCIO DEMO"
    assert tx.merchant_norm == "COMERCIO DEMO"
    assert tx.tx_type == "purchase"
    assert tx.parser_name == "be_email_v1"
    assert tx.parser_version == "1.0"
    assert tx.needs_review is True
    assert tx.review_reason == "currency_implicit"
    assert tx.fitid_synthetic is None


def test_explicit_clp_currency_does_not_need_currency_review() -> None:
    raw_text = (
        "Se ha realizado una compra por CLP $12.340 en COMERCIO DEMO "
        "con cargo a la cuenta ****1234.\n"
        "Fecha de la operacion: 2026-05-02.\n"
        "Codigo de autorizacion: TEST-A1."
    )

    tx = parse_purchase_email(raw_text)

    assert tx.needs_review is False
    assert tx.review_reason is None


def test_owner_controls_account_alias() -> None:
    raw_text = (
        "Se ha realizado una compra por CLP $12.340 en COMERCIO DEMO "
        "con cargo a la cuenta ****1234.\n"
        "Fecha de la operacion: 2026-05-02.\n"
        "Codigo de autorizacion: TEST-A1."
    )

    tx = parse_purchase_email(raw_text, owner="laura")

    assert tx.account_alias == "BE_Laura_1234"


def test_tarjeta_reference_controls_account_alias() -> None:
    raw_text = (
        "Se ha realizado una compra por CLP $12.340 en COMERCIO DEMO "
        "con cargo a la tarjeta ****1234.\n"
        "Fecha de la operacion: 2026-05-02.\n"
        "Codigo de autorizacion: TEST-A1."
    )

    tx = parse_purchase_email(raw_text)

    assert tx.account_alias == "BE_Ricardo_1234"
    assert tx.needs_review is False


def test_multiple_distinct_accounts_requires_review() -> None:
    raw_text = (
        "Se ha realizado una compra por CLP $12.340 en COMERCIO DEMO "
        "con cargo a la cuenta ****9876 y referencia cuenta ****1234.\n"
        "Fecha de la operacion: 2026-05-02.\n"
        "Codigo de autorizacion: TEST-A1."
    )

    tx = parse_purchase_email(raw_text)

    assert tx.account_alias == "BE_Ricardo_9876"
    assert tx.needs_review is True
    assert "account_ambiguous" in str(tx.review_reason)
