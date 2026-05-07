from collections.abc import Iterable
from datetime import date, datetime, timezone
from decimal import Decimal
from html import escape
from pathlib import Path

from ..artifacts import safe_output_path
from ..models import CanonicalTx


def write_ofx(transactions: Iterable[CanonicalTx], output_path: str | Path) -> Path:
    txs = list(transactions)
    if not txs:
        raise ValueError("OFX export requires at least one transaction")

    accounts = {tx.account_alias for tx in txs}
    if len(accounts) == 1:
        path = safe_output_path(output_path, allowed_suffixes={".ofx"})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_render_ofx(txs), encoding="utf-8")
        return path

    # Multiple accounts: write one file per account, using alias as suffix
    base = safe_output_path(output_path, allowed_suffixes={".ofx"})
    base.parent.mkdir(parents=True, exist_ok=True)
    stem = base.stem
    suffix = base.suffix
    last_path = base
    for account_alias in sorted(accounts):
        account_txs = [tx for tx in txs if tx.account_alias == account_alias]
        path = base.with_name(f"{stem}_{account_alias}{suffix}")
        path.write_text(_render_ofx(account_txs), encoding="utf-8")
        last_path = path
    return last_path


def _render_ofx(transactions: list[CanonicalTx]) -> str:
    if not transactions:
        raise ValueError("OFX export requires at least one transaction")

    accounts = {tx.account_alias for tx in transactions}
    if len(accounts) != 1:
        raise ValueError("OFX export requires one account per file")

    account_alias = next(iter(accounts))
    now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    start_date = min(_ofx_date(tx) for tx in transactions)
    end_date = max(_ofx_date(tx) for tx in transactions)
    tx_blocks = "\n".join(_render_transaction(tx) for tx in transactions)

    return f"""OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:UTF-8
CHARSET:UNICODE
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE

<OFX>
  <SIGNONMSGSRSV1>
    <SONRS>
      <STATUS><CODE>0<SEVERITY>INFO</STATUS>
      <DTSERVER>{now}
      <LANGUAGE>SPA
    </SONRS>
  </SIGNONMSGSRSV1>
  <BANKMSGSRSV1>
    <STMTTRNRS>
      <TRNUID>{now}
      <STATUS><CODE>0<SEVERITY>INFO</STATUS>
      <STMTRS>
        <CURDEF>CLP
        <BANKACCTFROM>
          <BANKID>FINANZASMMEX
          <ACCTID>{_value(account_alias)}
          <ACCTTYPE>CHECKING
        </BANKACCTFROM>
        <BANKTRANLIST>
          <DTSTART>{start_date}
          <DTEND>{end_date}
{tx_blocks}
        </BANKTRANLIST>
        <LEDGERBAL>
          <BALAMT>0.00
          <DTASOF>{now}
        </LEDGERBAL>
      </STMTRS>
    </STMTTRNRS>
  </BANKMSGSRSV1>
</OFX>
"""


def _render_transaction(tx: CanonicalTx) -> str:
    if not tx.fitid_synthetic:
        raise ValueError("OFX export requires fitid_synthetic")

    signed_amount = _signed_amount(tx)
    payee = tx.merchant_norm or tx.merchant_raw or "NEEDS REVIEW"

    return f"""          <STMTTRN>
            <TRNTYPE>{'DEBIT' if tx.direction == 'debit' else 'CREDIT'}
            <DTPOSTED>{_ofx_date(tx)}
            <TRNAMT>{signed_amount}
            <FITID>{_value(tx.fitid_synthetic)}
            <NAME>{_value(payee)}
            <MEMO>{_value(tx.tx_type)}
          </STMTTRN>"""


def _signed_amount(tx: CanonicalTx) -> str:
    amount = tx.amount.quantize(Decimal("0.00"))
    if tx.direction == "debit":
        amount = -amount
    return f"{amount:.2f}"


def _ofx_date(tx: CanonicalTx) -> str:
    tx_date = tx.posted_date or tx.event_date or tx.booking_date
    if tx_date is None:
        raise ValueError("OFX export requires a transaction date")
    if isinstance(tx_date, date):
        return tx_date.strftime("%Y%m%d000000")
    raise TypeError("Unexpected transaction date type")


def _value(value: str) -> str:
    return escape(value.replace("\r", " ").replace("\n", " "), quote=False)


# Public alias kept for test imports and backward compat
render_ofx = _render_ofx
