from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from finanzasmmex.etl.transfers import link_internal_transfers
from finanzasmmex.models import CanonicalTx


def _tx(
    *,
    direction: str,
    account: str,
    amount: str = "50000.00",
    event: date = date(2026, 5, 2),
    merchant: str = "Transferencia interna",
    tx_type: str = "transfer_out",
    owner: str = "ricardo",
    tx_uid: str | None = None,
) -> CanonicalTx:
    kwargs: dict[str, Any] = {
        "owner": owner,
        "source_type": "email",
        "content_sha256": "abc",
        "event_date": event,
        "amount": Decimal(amount),
        "direction": direction,
        "account_alias": account,
        "merchant_raw": merchant,
        "merchant_norm": merchant.upper(),
        "tx_type": tx_type,
        "parser_name": "be_email_v1",
    }
    if tx_uid is not None:
        kwargs["tx_uid"] = tx_uid
    return CanonicalTx(**kwargs)


def test_link_pairs_opposite_direction_same_amount_same_date() -> None:
    a = _tx(direction="debit", account="BE_R", tx_type="transfer_out", tx_uid="a")
    b = _tx(direction="credit", account="MACH_R", tx_type="transfer_in", tx_uid="b")
    out = link_internal_transfers([a, b])
    by_uid = {tx.tx_uid: tx for tx in out}
    assert by_uid["a"].transfer_pair_uid == by_uid["b"].transfer_pair_uid
    assert by_uid["a"].transfer_pair_uid is not None
    assert by_uid["a"].tx_type == "internal_transfer"
    assert by_uid["b"].tx_type == "internal_transfer"


def test_link_does_not_pair_different_amounts() -> None:
    a = _tx(direction="debit", account="BE_R", amount="50000.00", tx_uid="a")
    b = _tx(direction="credit", account="MACH_R", amount="49000.00", tx_uid="b")
    out = link_internal_transfers([a, b])
    assert all(tx.transfer_pair_uid is None for tx in out)


def test_link_does_not_pair_different_owners() -> None:
    a = _tx(direction="debit", account="BE_R", owner="ricardo", tx_uid="a")
    b = _tx(direction="credit", account="MACH_L", owner="laura", tx_uid="b")
    out = link_internal_transfers([a, b])
    assert all(tx.transfer_pair_uid is None for tx in out)


def test_link_does_not_pair_same_account() -> None:
    a = _tx(direction="debit", account="BE_R", tx_uid="a")
    b = _tx(direction="credit", account="BE_R", tx_uid="b")
    out = link_internal_transfers([a, b])
    assert all(tx.transfer_pair_uid is None for tx in out)


def test_link_pairs_within_one_day_window() -> None:
    a = _tx(
        direction="debit",
        account="BE_R",
        event=date(2026, 5, 2),
        tx_type="transfer_out",
        tx_uid="a",
    )
    b = _tx(
        direction="credit",
        account="MACH_R",
        event=date(2026, 5, 2) + timedelta(days=1),
        tx_type="transfer_in",
        tx_uid="b",
    )
    out = link_internal_transfers([a, b])
    by_uid = {tx.tx_uid: tx for tx in out}
    assert by_uid["a"].transfer_pair_uid is not None
    assert by_uid["a"].transfer_pair_uid == by_uid["b"].transfer_pair_uid


def test_link_skips_pairs_outside_window() -> None:
    a = _tx(direction="debit", account="BE_R", event=date(2026, 5, 2), tx_uid="a")
    b = _tx(direction="credit", account="MACH_R", event=date(2026, 5, 5), tx_uid="b")
    out = link_internal_transfers([a, b])
    assert all(tx.transfer_pair_uid is None for tx in out)


def test_link_does_not_pair_purchases_without_transfer_signal() -> None:
    a = _tx(
        direction="debit",
        account="BE_R",
        merchant="Supermercado",
        tx_type="purchase",
        tx_uid="a",
    )
    b = _tx(
        direction="credit",
        account="MACH_R",
        merchant="Devolucion",
        tx_type="refund",
        tx_uid="b",
    )
    out = link_internal_transfers([a, b])
    assert all(tx.transfer_pair_uid is None for tx in out)


def test_link_is_idempotent() -> None:
    a = _tx(direction="debit", account="BE_R", tx_type="transfer_out", tx_uid="a")
    b = _tx(direction="credit", account="MACH_R", tx_type="transfer_in", tx_uid="b")
    once = link_internal_transfers([a, b])
    twice = link_internal_transfers(once)
    once_pairs = {tx.tx_uid: tx.transfer_pair_uid for tx in once}
    twice_pairs = {tx.tx_uid: tx.transfer_pair_uid for tx in twice}
    assert once_pairs == twice_pairs
