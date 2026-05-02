# BAD: amount carries sign instead of using direction; ambiguous extraction does not set
# needs_review; date parsed without ISO validation.
from datetime import datetime
from decimal import Decimal

from finanzasmmex.models import CanonicalTx

PARSER_NAME = "cmr_email_v1"
PARSER_VERSION = "0.1"


def parse(raw: str) -> CanonicalTx:
    # Multi-match ambiguity ignored, no needs_review set.
    amount_str = raw.split("$")[1].split()[0]
    # Date parsed with strptime then converted to str — no ISO validation.
    date_str = datetime.strptime("01-12-2026", "%d-%m-%Y").strftime("%Y-%m-%d")

    return CanonicalTx(
        owner="ricardo",
        source_type="email",
        content_sha256="abc",  # not actually computed
        amount=Decimal(f"-{amount_str.replace('.', '')}"),  # WRONG: negative amount
        currency="CLP",
        direction="debit",
        account_alias="CMR_Ricardo",
        tx_type="purchase",
        parser_name=PARSER_NAME,
        parser_version=PARSER_VERSION,
        # needs_review NOT set despite ambiguity
        raw_text=raw,
        fitid_synthetic="",
    )
