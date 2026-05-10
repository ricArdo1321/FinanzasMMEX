from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from ..models import CanonicalTx

_TRANSFER_TX_TYPES = {"transfer_in", "transfer_out", "internal_transfer"}
_TRANSFER_KEYWORDS = ("TRANSFER", "TRANSF", "ABONO", "GIRO ENTRE")
_PAIR_WINDOW = timedelta(days=1)


def link_internal_transfers(txs: Iterable[CanonicalTx]) -> list[CanonicalTx]:
    items = list(txs)
    by_uid: dict[str, CanonicalTx] = {tx.tx_uid: tx for tx in items}

    paired: dict[str, str] = {}  # tx_uid -> pair_uid
    to_alias: dict[str, str] = {}  # tx_uid -> counterpart account_alias
    consumed: set[str] = set()

    for i, tx_a in enumerate(items):
        if tx_a.tx_uid in consumed:
            continue
        if not _is_transfer_candidate(tx_a):
            continue
        for tx_b in items[i + 1:]:
            if tx_b.tx_uid in consumed:
                continue
            if not _is_pair(tx_a, tx_b):
                continue
            to_alias[tx_a.tx_uid] = tx_b.account_alias
            to_alias[tx_b.tx_uid] = tx_a.account_alias
            paired[tx_a.tx_uid] = tx_b.tx_uid
            paired[tx_b.tx_uid] = tx_a.tx_uid
            consumed.add(tx_a.tx_uid)
            consumed.add(tx_b.tx_uid)
            break

    return [
        _apply_pair(by_uid[uid], paired[uid], to_alias[uid])
        if uid in paired
        else tx
        for uid, tx in by_uid.items()
    ]


def _is_transfer_candidate(tx: CanonicalTx) -> bool:
    if tx.tx_type in _TRANSFER_TX_TYPES:
        return True
    haystack = (tx.merchant_norm or tx.merchant_raw or "").upper()
    return any(keyword in haystack for keyword in _TRANSFER_KEYWORDS)


def _is_pair(a: CanonicalTx, b: CanonicalTx) -> bool:
    if a.owner != b.owner:
        return False
    if a.account_alias == b.account_alias:
        return False
    if {a.direction, b.direction} != {"debit", "credit"}:
        return False
    if _amount(a) != _amount(b):
        return False
    if not _is_transfer_candidate(b):
        return False
    return _within_window(a, b)


def _amount(tx: CanonicalTx) -> Decimal:
    return tx.amount.quantize(Decimal("0.00"))


def _within_window(a: CanonicalTx, b: CanonicalTx) -> bool:
    da = _ref_date(a)
    db = _ref_date(b)
    if da is None or db is None:
        return False
    return abs(da - db) <= _PAIR_WINDOW


def _ref_date(tx: CanonicalTx) -> date | None:
    return tx.event_date or tx.posted_date or tx.booking_date


def _apply_pair(tx: CanonicalTx, pair_uid: str, to_account_alias: str) -> CanonicalTx:
    return replace(
        tx,
        transfer_pair_uid=pair_uid,
        tx_type="internal_transfer",
        to_account_alias=to_account_alias,
    )
