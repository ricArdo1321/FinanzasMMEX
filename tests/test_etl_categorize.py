from datetime import date
from decimal import Decimal

from finanzasmmex.etl.categorize import CategoryRule, categorize_tx
from finanzasmmex.models import CanonicalTx


def _tx(merchant: str = "Cafe Demo Nunoa") -> CanonicalTx:
    return CanonicalTx(
        owner="ricardo",
        source_type="email",
        content_sha256="abc",
        event_date=date(2026, 5, 2),
        amount=Decimal("12340.00"),
        direction="debit",
        account_alias="BE_Ricardo_1234",
        merchant_raw=merchant,
        merchant_norm=merchant.upper(),
        tx_type="purchase",
        parser_name="be_email_v1",
    )


def test_categorize_substring_match_sets_canonical_merchant() -> None:
    rules = [
        CategoryRule(
            rule_id=1,
            pattern="CAFE",
            pattern_type="substr",
            merchant_norm="Cafe Demo",
            category_name="Comida",
            subcategory_name="Cafeterias",
            tags=["personal"],
            priority=10,
        )
    ]
    out = categorize_tx(_tx(), rules)
    assert out.merchant_norm == "Cafe Demo"
    assert out.category_guess == "Comida"
    assert out.subcategory_guess == "Cafeterias"
    assert "personal" in out.tags


def test_categorize_priority_substr_before_regex() -> None:
    rules = [
        CategoryRule(
            rule_id=1,
            pattern=r"CAFE.*NUNOA",
            pattern_type="regex",
            merchant_norm="Cafe Regex",
            category_name="RegexCat",
            priority=20,
        ),
        CategoryRule(
            rule_id=2,
            pattern="CAFE",
            pattern_type="substr",
            merchant_norm="Cafe Substr",
            category_name="SubstrCat",
            priority=10,
        ),
    ]
    out = categorize_tx(_tx(), rules)
    assert out.category_guess == "SubstrCat"
    assert out.merchant_norm == "Cafe Substr"


def test_categorize_fuzzy_above_threshold_matches() -> None:
    rules = [
        CategoryRule(
            rule_id=1,
            pattern="CAFE DEMO NUNOA",
            pattern_type="fuzzy",
            merchant_norm="Cafe Demo",
            category_name="Comida",
            fuzzy_threshold=85,
            priority=10,
        )
    ]
    tx = _tx(merchant="Cafe Dmo Nunoa")
    out = categorize_tx(tx, rules)
    assert out.category_guess == "Comida"


def test_categorize_fuzzy_below_threshold_skips() -> None:
    rules = [
        CategoryRule(
            rule_id=1,
            pattern="ESTACION SERVICIO",
            pattern_type="fuzzy",
            merchant_norm="Combustible",
            category_name="Auto",
            fuzzy_threshold=95,
            priority=10,
        )
    ]
    out = categorize_tx(_tx(), rules)
    assert out.category_guess is None


def test_categorize_no_match_leaves_tx_unchanged() -> None:
    out = categorize_tx(_tx(), [])
    assert out.category_guess is None
    assert out.subcategory_guess is None
    assert out.merchant_norm == "CAFE DEMO NUNOA"


def test_categorize_skips_inactive_rules() -> None:
    rules = [
        CategoryRule(
            rule_id=1,
            pattern="CAFE",
            pattern_type="substr",
            merchant_norm="Cafe Demo",
            category_name="Comida",
            priority=10,
            active=False,
        )
    ]
    out = categorize_tx(_tx(), rules)
    assert out.category_guess is None
