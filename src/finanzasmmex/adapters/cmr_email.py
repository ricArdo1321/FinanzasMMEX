import hashlib
import re
from datetime import date
from typing import Literal

from ..etl.normalize import normalize_merchant, parse_clp_amount
from ..models import CanonicalTx

PARSER_NAME = "cmr_email_v1"
PARSER_VERSION = "1.0"

_AMOUNT_RE = re.compile(
    r"compra\s+(?:realizada\s+)?(?:por\s+)?(?P<currency>CLP\s*)?\$?\s*"
    r"(?P<amount>[0-9][0-9.\s]*)",
    re.IGNORECASE,
)
_MERCHANT_RE = re.compile(
    r"compra\s+(?:realizada\s+)?(?:por\s+)?(?:CLP\s*)?\$?\s*[0-9][0-9.\s]*\s+en\s+"
    r"(?P<merchant>.+?)\s+el\s+\d{2}[/-]\d{2}[/-]\d{4}",
    re.IGNORECASE | re.DOTALL,
)
_CARD_RE = re.compile(
    r"tarjeta\s+(?:CMR\s+)?(?:terminada\s+en|\*+)\s*(\d{4})",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"el\s+(?P<day>\d{2})[/-](?P<month>\d{2})[/-](?P<year>\d{4})",
    re.IGNORECASE,
)
_INSTALLMENTS_RE = re.compile(r"cuotas?\s*[:\-]?\s*(\d+)", re.IGNORECASE)
_OPERATION_RE = re.compile(
    r"(?:n[uú]mero|nro\.?|n[°o])\s+de\s+operaci[oó]n\s*[:\-]?\s*([A-Z0-9-]+)",
    re.IGNORECASE,
)


class CmrEmailParseError(ValueError):
    pass


def parse_purchase_email(
    raw_text: str,
    *,
    source_file: str | None = None,
    owner: Literal["ricardo", "laura", "joint"] = "ricardo",
) -> CanonicalTx:
    content_sha256 = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    text = raw_text.replace("\xa0", " ")

    amount_match = _required_search(_AMOUNT_RE, text, "amount")
    merchant_match = _required_search(_MERCHANT_RE, text, "merchant")
    card_last4, card_ambiguous = _card_last4(text)
    date_match = _required_search(_DATE_RE, text, "event_date")

    operation_number = _optional_match(_OPERATION_RE, text)
    installments = _installments(text)

    amount_value = parse_clp_amount(_clean_text(amount_match.group("amount")))
    merchant_raw = _clean_text(merchant_match.group("merchant"))
    currency_explicit = amount_match.group("currency") is not None
    event_date = date.fromisoformat(
        f"{int(date_match.group('year')):04d}-"
        f"{int(date_match.group('month')):02d}-"
        f"{int(date_match.group('day')):02d}"
    )

    review_reasons: list[str] = []
    if not currency_explicit:
        review_reasons.append("currency_implicit")
    if installments is not None and installments > 1:
        review_reasons.append(f"installments:{installments}")
    if card_ambiguous:
        review_reasons.append("card_ambiguous")
    if operation_number is None:
        review_reasons.append("partial_extraction:operation_number")

    return CanonicalTx(
        owner=owner,
        source_type="email",
        source_file=source_file,
        source_ref=operation_number,
        raw_text=raw_text,
        content_sha256=content_sha256,
        event_date=event_date,
        posted_date=event_date,
        amount=amount_value,
        currency="CLP",
        direction="debit",
        account_alias=f"CMR_{_owner_label(owner)}_{card_last4}",
        card_last4=card_last4,
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
        raise CmrEmailParseError(f"Missing CMR field: {field_name}")
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


def _card_last4(text: str) -> tuple[str, bool]:
    matches = _distinct_in_order(_CARD_RE.findall(text))
    if not matches:
        raise CmrEmailParseError("Missing CMR field: card_last4")
    return matches[0], len(matches) != 1


def _distinct_in_order(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            out.append(value)
            seen.add(value)
    return out


def _installments(text: str) -> int | None:
    match = _INSTALLMENTS_RE.search(text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _owner_label(owner: Literal["ricardo", "laura", "joint"]) -> str:
    return {"ricardo": "Ricardo", "laura": "Laura", "joint": "Joint"}[owner]
