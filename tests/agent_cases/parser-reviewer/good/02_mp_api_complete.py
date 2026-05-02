# GOOD: MP API adapter, complete CanonicalTx, ISO dates from API JSON,
# direction inferred from `operation_type`, parser metadata explicit.
import hashlib
from datetime import date
from decimal import Decimal

from finanzasmmex.models import CanonicalTx

PARSER_NAME = "mp_api_v1"
PARSER_VERSION = "1.0"


def parse(payment: dict, raw: str) -> CanonicalTx:
    sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    amount = Decimal(str(payment["transaction_amount"]))
    direction = "credit" if payment["operation_type"] == "money_in" else "debit"
    posted = date.fromisoformat(payment["date_approved"][:10])
    return CanonicalTx(
        owner="ricardo",
        source_type="mp_api",
        source_ref=str(payment["id"]),
        content_sha256=sha,
        amount=amount,
        currency=payment.get("currency_id", "CLP"),
        direction=direction,
        account_alias="MP_Ricardo",
        tx_type="purchase" if direction == "debit" else "transfer_in",
        merchant_raw=payment.get("description", ""),
        posted_date=posted,
        parser_name=PARSER_NAME,
        parser_version=PARSER_VERSION,
        raw_text=raw,
        fitid_synthetic="",
    )
