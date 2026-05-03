import hashlib
from dataclasses import replace
from datetime import date
from decimal import Decimal

from ..models import CanonicalTx
from .normalize import normalize_merchant


def ensure_fitid(tx: CanonicalTx) -> CanonicalTx:
    merchant_norm = tx.merchant_norm or normalize_merchant(tx.merchant_raw)
    enriched = replace(tx, merchant_norm=merchant_norm)
    return replace(enriched, fitid_synthetic=compute_fitid(enriched))


def compute_fitid(tx: CanonicalTx) -> str:
    event_date = _tx_date(tx)
    merchant_norm = tx.merchant_norm or normalize_merchant(tx.merchant_raw)
    amount = tx.amount.quantize(Decimal("0.00"))
    material = "|".join(
        [
            tx.owner,
            tx.account_alias,
            event_date.isoformat(),
            str(amount),
            merchant_norm,
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _tx_date(tx: CanonicalTx) -> date:
    tx_date = tx.event_date or tx.booking_date or tx.posted_date
    if tx_date is None:
        raise ValueError("Cannot compute FITID without a transaction date")
    return tx_date
