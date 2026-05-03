import hashlib
import re
from datetime import date
from typing import Literal

from ..etl.normalize import normalize_merchant, parse_clp_amount
from ..models import CanonicalTx

PARSER_NAME = "mach_email_v1"
PARSER_VERSION = "1.0"

_AMOUNT_RE = re.compile(
    r"(?:pagaste|compra(?:ste)?(?:\s+por)?|cargo\s+por)\s+"
    r"(?P<currency>CLP\s*)?\$?\s*(?P<amount>[0-9][0-9.\s]*)",
    re.IGNORECASE,
)
_MERCHANT_RE = re.compile(
    r"(?:pagaste|compra(?:ste)?(?:\s+por)?|cargo\s+por)\s+"
    r"(?:CLP\s*)?\$?\s*[0-9][0-9.\s]*\s+en\s+(?P<merchant>.+?)"
    r"(?:\.\s*(?:\n|$)|\n|$)",
    re.IGNORECASE,
)
_CARD_RE = re.compile(
    r"tarjeta\s+(?:mach\s+)?(?:terminada\s+en|\*+)\s*(\d{4})",
    re.IGNORECASE,
)
_DATE_DMY_RE = re.compile(
    r"fecha\s*[:\-]?\s*(?P<day>\d{2})[/-](?P<month>\d{2})[/-](?P<year>\d{4})",
    re.IGNORECASE,
)
_DATE_ISO_RE = re.compile(
    r"fecha\s*[:\-]?\s*(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})",
    re.IGNORECASE,
)
_TX_ID_RE = re.compile(
    r"(?:id\s+(?:de\s+)?transacci[oó]n|c[oó]digo\s+de\s+transacci[oó]n)\s*[:\-]?\s*"
    r"([A-Z0-9-]+)",
    re.IGNORECASE,
)


class MachEmailParseError(ValueError):
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
    card_last4 = _required_match(_CARD_RE, text, "card_last4")
    event_date = _parse_date(text)

    tx_id = _optional_match(_TX_ID_RE, text)

    amount_value = parse_clp_amount(_clean_text(amount_match.group("amount")))
    merchant_raw = _clean_text(merchant_match.group("merchant"))
    currency_explicit = amount_match.group("currency") is not None

    review_reasons: list[str] = []
    if not currency_explicit:
        review_reasons.append("currency_implicit")
    if tx_id is None:
        review_reasons.append("partial_extraction:tx_id")

    return CanonicalTx(
        owner=owner,
        source_type="email",
        source_file=source_file,
        source_ref=tx_id,
        raw_text=raw_text,
        content_sha256=content_sha256,
        event_date=event_date,
        posted_date=event_date,
        amount=amount_value,
        currency="CLP",
        direction="debit",
        account_alias=f"MACH_{_owner_label(owner)}_{card_last4}",
        card_last4=card_last4,
        merchant_raw=merchant_raw,
        merchant_norm=normalize_merchant(merchant_raw),
        tx_type="purchase",
        parser_name=PARSER_NAME,
        parser_version=PARSER_VERSION,
        needs_review=bool(review_reasons),
        review_reason=";".join(review_reasons) if review_reasons else None,
    )


def _parse_date(text: str) -> date:
    for pattern in (_DATE_ISO_RE, _DATE_DMY_RE):
        match = pattern.search(text)
        if match:
            iso = (
                f"{int(match.group('year')):04d}-"
                f"{int(match.group('month')):02d}-"
                f"{int(match.group('day')):02d}"
            )
            return date.fromisoformat(iso)
    raise MachEmailParseError("Missing Mach field: event_date")


def _required_search(
    pattern: re.Pattern[str],
    text: str,
    field_name: str,
) -> re.Match[str]:
    match = pattern.search(text)
    if not match:
        raise MachEmailParseError(f"Missing Mach field: {field_name}")
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


def _owner_label(owner: Literal["ricardo", "laura", "joint"]) -> str:
    return {"ricardo": "Ricardo", "laura": "Laura", "joint": "Joint"}[owner]
