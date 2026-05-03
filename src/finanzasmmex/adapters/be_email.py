import hashlib
import re
from datetime import date
from typing import Literal

from ..etl.normalize import normalize_merchant, parse_clp_amount
from ..models import CanonicalTx

PARSER_NAME = "be_email_v1"
PARSER_VERSION = "1.0"

_AMOUNT_RE = re.compile(
    r"compra\s+por\s+(?:(?P<currency>CLP)\s*)?\$?\s*(?P<amount>[0-9][0-9.\s]*)",
    re.IGNORECASE,
)
_MERCHANT_RE = re.compile(
    r"compra\s+por\s+(?:CLP\s*)?\$?\s*[0-9][0-9.\s]*\s+en\s+(.+?)"
    r"\s+con\s+cargo\s+(?:a\s+)?(?:la\s+)?(?:cuenta|tarjeta)\s+\*+",
    re.IGNORECASE | re.DOTALL,
)
_ACCOUNT_RE = re.compile(r"cuenta\s+\*+(\d{4})", re.IGNORECASE)
_DATE_RE = re.compile(
    r"Fecha\s+de\s+la\s+operaci[oó]n:\s*(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
_AUTH_RE = re.compile(
    r"C[oó]digo\s+de\s+autorizaci[oó]n:\s*([A-Z0-9-]+)",
    re.IGNORECASE,
)


class BancoEstadoEmailParseError(ValueError):
    pass


def parse_purchase_email(
    raw_text: str,
    *,
    source_file: str | None = None,
    owner: Literal["ricardo", "laura", "joint"] = "ricardo",
) -> CanonicalTx:
    content_sha256 = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

    amount_match = _required_search(_AMOUNT_RE, raw_text, "amount")
    amount = _clean_text(amount_match.group("amount"))
    currency_explicit = amount_match.group("currency") is not None
    merchant = _required_match(_MERCHANT_RE, raw_text, "merchant")
    account_last4, account_ambiguous = _account_last4(raw_text)
    event_date_raw = _required_match(_DATE_RE, raw_text, "event_date")
    auth_code = _optional_match(_AUTH_RE, raw_text)

    event_date = date.fromisoformat(event_date_raw)
    amount_value = parse_clp_amount(amount)
    merchant_raw = _clean_text(merchant)
    review_reasons = _review_reasons(
        currency_explicit=currency_explicit,
        account_ambiguous=account_ambiguous,
        auth_code=auth_code,
    )

    return CanonicalTx(
        owner=owner,
        source_type="email",
        source_file=source_file,
        source_ref=auth_code,
        raw_text=raw_text,
        content_sha256=content_sha256,
        event_date=event_date,
        posted_date=event_date,
        amount=amount_value,
        currency="CLP",
        direction="debit",
        account_alias=f"BE_{_owner_label(owner)}_{account_last4}",
        merchant_raw=merchant_raw,
        merchant_norm=normalize_merchant(merchant_raw),
        tx_type="purchase",
        parser_name=PARSER_NAME,
        parser_version=PARSER_VERSION,
        needs_review=bool(review_reasons),
        review_reason=";".join(review_reasons) if review_reasons else None,
    )


def _required_search(
    pattern: re.Pattern[str],
    text: str,
    field_name: str,
) -> re.Match[str]:
    match = pattern.search(text)
    if not match:
        raise BancoEstadoEmailParseError(f"Missing BancoEstado field: {field_name}")
    return match


def _required_match(pattern: re.Pattern[str], text: str, field_name: str) -> str:
    return _clean_text(_required_search(pattern, text, field_name).group(1))


def _optional_match(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    return _clean_text(match.group(1))


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _account_last4(text: str) -> tuple[str, bool]:
    matches = sorted(set(_ACCOUNT_RE.findall(text)))
    if not matches:
        raise BancoEstadoEmailParseError("Missing BancoEstado field: account")
    return matches[0], len(matches) != 1


def _owner_label(owner: Literal["ricardo", "laura", "joint"]) -> str:
    return {
        "ricardo": "Ricardo",
        "laura": "Laura",
        "joint": "Joint",
    }[owner]


def _review_reasons(
    *,
    currency_explicit: bool,
    account_ambiguous: bool,
    auth_code: str | None,
) -> list[str]:
    reasons: list[str] = []
    if not currency_explicit:
        reasons.append("currency_implicit")
    if account_ambiguous:
        reasons.append("account_ambiguous")
    if auth_code is None:
        reasons.append("partial_extraction:auth_code")
    return reasons
