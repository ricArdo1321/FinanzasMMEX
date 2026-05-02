# GOOD: BE email adapter, all required fields, robust regex with re.IGNORECASE,
# ISO date parsing, content_sha256 over full raw, needs_review on ambiguity,
# parser metadata explicit.
import hashlib
import re
from datetime import date
from decimal import Decimal

from finanzasmmex.models import CanonicalTx

PARSER_NAME = "be_email_v3"
PARSER_VERSION = "1.0"

AMOUNT_RE = re.compile(r"\$\s*([\d.]+)", re.IGNORECASE)
DATE_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
MERCHANT_RE = re.compile(r"comercio[:\s]+([^\n<]+)", re.IGNORECASE)


def parse(raw: str) -> CanonicalTx:
    sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    a = AMOUNT_RE.search(raw)
    d = DATE_RE.search(raw)
    m = MERCHANT_RE.search(raw)

    if not a or not d:
        return CanonicalTx(
            owner="ricardo",
            source_type="email",
            content_sha256=sha,
            amount=Decimal("0.01"),
            currency="CLP",
            direction="debit",
            account_alias="BE_Ricardo_RUT",
            tx_type="purchase",
            parser_name=PARSER_NAME,
            parser_version=PARSER_VERSION,
            needs_review=True,
            review_reason="missing amount or date",
            raw_text=raw,
            fitid_synthetic="",  # set in ETL
        )

    posted = date(int(d.group(3)), int(d.group(2)), int(d.group(1)))
    amount = Decimal(a.group(1).replace(".", ""))
    return CanonicalTx(
        owner="ricardo",
        source_type="email",
        content_sha256=sha,
        amount=amount,
        currency="CLP",
        direction="debit",
        account_alias="BE_Ricardo_RUT",
        tx_type="purchase",
        parser_name=PARSER_NAME,
        parser_version=PARSER_VERSION,
        posted_date=posted,
        merchant_raw=(m.group(1).strip() if m else ""),
        raw_text=raw,
        fitid_synthetic="",
    )
