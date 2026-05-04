"""Direct SQL writer to a Money Manager Ex .mmb database.

Safety contract (Phase 2 hard rules; see CLAUDE.md "Writer modes"):
- Productive `finanza.mmb` MUST never be written by this module. The path
  guard rejects exact and disguised productive names.
- A connection MUST be transactional (BEGIN IMMEDIATE / COMMIT / ROLLBACK)
  with timeout=0 so an MMEX-held write lock is detected immediately as
  MmexLockedError (mappable to CLI exit code 4).
- Pre/post backups MUST be taken via the SQLite Online Backup API (safe
  against a concurrent writer), under a backup directory that is rotated
  to keep the last 30 days only.
- A batch with reconcile_log.status='off' for any account in the batch
  MUST block the writer.
"""

import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from ..models import CanonicalTx
from ..staging.repo import StagingRepo

_BACKUP_RETENTION_DAYS = 30


class MmexSqlError(Exception):
    pass


class MmexSafetyError(MmexSqlError):
    pass


class MmexLockedError(MmexSqlError):
    pass


class MmexSchemaError(MmexSqlError):
    pass


class MmexMappingError(MmexSqlError):
    pass


@dataclass(frozen=True)
class SqlWriteSummary:
    items_considered: int
    items_inserted: int
    items_skipped_duplicate: int
    items_rejected_review: int
    items_rejected_unsupported: int
    mmex_path: str
    backup_pre_path: str | None
    backup_post_path: str | None
    mmex_tx_ids: dict[str, int] = field(default_factory=dict)
    mmex_account_ids: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "items_considered": self.items_considered,
            "items_inserted": self.items_inserted,
            "items_skipped_duplicate": self.items_skipped_duplicate,
            "items_rejected_review": self.items_rejected_review,
            "items_rejected_unsupported": self.items_rejected_unsupported,
            "mmex_path": self.mmex_path,
            "backup_pre_path": self.backup_pre_path,
            "backup_post_path": self.backup_post_path,
            "mmex_tx_ids": self.mmex_tx_ids,
            "mmex_account_ids": self.mmex_account_ids,
        }


def write_sql(
    transactions: Iterable[CanonicalTx],
    *,
    mmex_db_path: str | Path,
    backup_dir: str | Path,
    allow_shadow_write: bool = False,
    staging_repo: StagingRepo | None = None,
) -> SqlWriteSummary:
    txs = list(transactions)
    mmex_path = _safe_mmex_db_path(mmex_db_path, allow_shadow_write)

    rejected_review = sum(1 for tx in txs if tx.needs_review)
    rejected_unsupported = sum(1 for tx in txs if _unsupported_for_sql(tx))
    eligible = [
        tx for tx in txs if not tx.needs_review and not _unsupported_for_sql(tx)
    ]

    if not eligible:
        return SqlWriteSummary(
            items_considered=len(txs),
            items_inserted=0,
            items_skipped_duplicate=0,
            items_rejected_review=rejected_review,
            items_rejected_unsupported=rejected_unsupported,
            mmex_path=str(mmex_path),
            backup_pre_path=None,
            backup_post_path=None,
        )

    if staging_repo is not None:
        aliases = {tx.account_alias for tx in eligible}
        if staging_repo.has_reconcile_off(aliases):
            raise MmexSafetyError(
                "Refusing to write: at least one account in the batch has "
                "reconcile_log.status='off'"
            )

    # Probe for MMEX-held lock FIRST so we surface MmexLockedError before
    # any file-system side effect (a hung MMEX should not also create a
    # backup file).
    _assert_not_locked(mmex_path)
    # Pre-backup runs on a separate read-only connection. The SQLite Online
    # Backup API is safe even if MMEX re-opens between the probe and here —
    # it serialises pages through SQLite's locking instead of shutil.copy2.
    # Pre-backup failure MUST abort (no COMMIT has happened yet); only the
    # post-backup is tolerant to OSError because the COMMIT already succeeded.
    pre_backup_path: Path | None = _safe_backup(mmex_path, backup_dir, "pre")
    inserted: dict[str, int] = {}
    inserted_accounts: dict[str, int] = {}
    duplicates = 0

    conn = _connect(mmex_path)
    try:
        # BEGIN IMMEDIATE: an MMEX-held lock surfaces here as MmexLockedError
        # mapped to CLI exit code 4. The TOCTOU window between pre-backup
        # and BEGIN IMMEDIATE is bounded by the backup step; if MMEX grabbed
        # the lock between, we never reach insert and never need to undo.
        _begin_immediate(conn)
        _ensure_required_schema(conn)
        sync_field_id = _ensure_sync_hash_field(conn)

        for tx in eligible:
            if not tx.fitid_synthetic:
                raise MmexMappingError("fitid_synthetic is required for SQL writer")
            if _sync_hash_exists(conn, sync_field_id, tx.fitid_synthetic):
                duplicates += 1
                continue

            account_id = _resolve_account_id(conn, tx.account_alias)
            category_id, subcategory_id = _resolve_category(
                conn,
                tx.category_guess,
                tx.subcategory_guess,
            )
            payee_id = _resolve_payee_id(
                conn,
                _payee_name(tx),
                category_id,
                subcategory_id,
            )
            mmex_tx_id = _insert_checking_tx(
                conn,
                tx,
                account_id=account_id,
                payee_id=payee_id,
                category_id=category_id,
                subcategory_id=subcategory_id,
            )
            _insert_sync_hash(conn, sync_field_id, mmex_tx_id, tx.fitid_synthetic)
            inserted[tx.tx_uid] = mmex_tx_id
            inserted_accounts[tx.tx_uid] = account_id

        conn.commit()
    except sqlite3.OperationalError as exc:
        _rollback_quietly(conn)
        if _is_locked(exc):
            raise MmexLockedError("MMEX database is locked") from exc
        raise
    except Exception:
        _rollback_quietly(conn)
        raise
    finally:
        conn.close()

    # Post-backup must not undo a successful commit. If it fails the run
    # is still successful, but the caller is told via a missing path.
    post_backup_path: str | None
    try:
        post_backup_path = str(_safe_backup(mmex_path, backup_dir, "post"))
    except OSError:
        post_backup_path = None

    return SqlWriteSummary(
        items_considered=len(txs),
        items_inserted=len(inserted),
        items_skipped_duplicate=duplicates,
        items_rejected_review=rejected_review,
        items_rejected_unsupported=rejected_unsupported,
        mmex_path=str(mmex_path),
        backup_pre_path=str(pre_backup_path) if pre_backup_path else None,
        backup_post_path=post_backup_path,
        mmex_tx_ids=inserted,
        mmex_account_ids=inserted_accounts,
    )


_SHADOW_TOKENS = ("test", "shadow", "demo")


def _safe_mmex_db_path(
    mmex_db_path: str | Path,
    allow_shadow_write: bool,
) -> Path:
    raw_path = Path(mmex_db_path).expanduser()
    # resolve(strict=False) collapses ".." and normalises casing on disk where
    # possible; we still defend against names crafted to look like shadow files.
    path = raw_path.resolve(strict=False)
    suffix = path.suffix.lower()
    stem_lower = path.stem.lower()
    name_lower = path.name.lower()

    if suffix == ".emb":
        raise MmexSafetyError("Encrypted .emb MMEX files are not writable in Phase 2")
    if suffix != ".mmb":
        raise MmexSafetyError("SQL writer target must be a .mmb database")

    has_shadow_token = any(token in stem_lower for token in _SHADOW_TOKENS)
    looks_productive = name_lower == "finanza.mmb" or (
        stem_lower.startswith("finanza") and not has_shadow_token
    )
    if looks_productive:
        raise MmexSafetyError(
            "Refusing to write productive finanza*.mmb path in Phase 2"
        )
    if not allow_shadow_write:
        raise MmexSafetyError("SQL writer requires explicit shadow/test write flag")
    if not has_shadow_token:
        raise MmexSafetyError("SQL writer target must be a test/shadow .mmb path")
    if not path.is_file():
        raise MmexSafetyError("SQL writer target .mmb does not exist")
    return path


def _unsupported_for_sql(tx: CanonicalTx) -> bool:
    return tx.tx_type in {"transfer_in", "transfer_out", "internal_transfer"}


def _safe_backup(mmex_path: Path, backup_dir: str | Path, kind: str) -> Path:
    """Take a transactionally consistent backup via the SQLite Online Backup API.

    Unlike a raw file copy, this is safe even if MMEX is reading the file
    concurrently because the API serialises pages through SQLite's locking.
    Used for the post-write backup with a fresh read connection.
    """
    src = sqlite3.connect(mmex_path, timeout=0)
    try:
        return _safe_backup_via_conn(src, mmex_path, backup_dir, kind)
    finally:
        src.close()


def _safe_backup_via_conn(
    src: sqlite3.Connection,
    mmex_path: Path,
    backup_dir: str | Path,
    kind: str,
) -> Path:
    """Backup using an existing connection (used inside the writer transaction)."""
    out_dir = Path(backup_dir).expanduser().resolve(strict=False)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    out_path = out_dir / f"{mmex_path.stem}.{stamp}.{kind}.mmb"
    if out_path.exists():
        # Microsecond clash should be vanishingly rare; bail loud rather than
        # overwrite an existing backup file.
        raise OSError(f"Backup target already exists: {out_path}")

    dst = sqlite3.connect(out_path)
    try:
        src.backup(dst)
    finally:
        dst.close()

    _prune_old_backups(out_dir, mmex_path.stem)
    return out_path


def _prune_old_backups(backup_dir: Path, stem: str) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=_BACKUP_RETENTION_DAYS)
    cutoff_ts = cutoff.timestamp()
    # Anchor on the exact stamp pattern (YYYYMMDDTHHMMSS_microsecondsZ) so a
    # different stem that happens to share a prefix with `stem` cannot be
    # cross-deleted from this directory.
    pattern = f"{stem}.????????T??????_*Z.*.mmb"
    for entry in backup_dir.glob(pattern):
        try:
            if entry.stat().st_mtime < cutoff_ts:
                entry.unlink()
        except OSError:
            # Best-effort prune; never break the writer for cleanup issues.
            continue


def _assert_not_locked(mmex_path: Path) -> None:
    """Probe MMEX for a write lock and surface MmexLockedError immediately.

    Done before pre-backup and main BEGIN IMMEDIATE so a busy MMEX never
    triggers any file-system side effect.
    """
    conn = _connect(mmex_path)
    try:
        _begin_immediate(conn)
        conn.rollback()
    finally:
        conn.close()


def _connect(mmex_path: Path) -> sqlite3.Connection:
    try:
        # Autocommit mode + explicit BEGIN IMMEDIATE: every statement after
        # BEGIN IMMEDIATE participates in the same transaction until COMMIT
        # or ROLLBACK. timeout=0 keeps lock detection instant.
        conn = sqlite3.connect(mmex_path, timeout=0, isolation_level=None)
    except sqlite3.OperationalError as exc:
        if _is_locked(exc):
            raise MmexLockedError("MMEX database is locked") from exc
        raise
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn



def _begin_immediate(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        if _is_locked(exc):
            raise MmexLockedError("MMEX database is locked") from exc
        raise


def _rollback_quietly(conn: sqlite3.Connection) -> None:
    try:
        conn.rollback()
    except sqlite3.Error:
        pass


def _is_locked(exc: sqlite3.OperationalError) -> bool:
    return "locked" in str(exc).lower()


def _ensure_required_schema(conn: sqlite3.Connection) -> None:
    for table in (
        "ACCOUNTLIST_V1",
        "PAYEE_V1",
        "CATEGORY_V1",
        "SUBCATEGORY_V1",
        "CHECKINGACCOUNT_V1",
        "CUSTOMFIELD_V1",
        "CUSTOMFIELDDATA_V1",
    ):
        if not _table_exists(conn, table):
            raise MmexSchemaError(f"MMEX table missing: {table}")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row["name"]) for row in rows}


def _first_present(columns: set[str], candidates: Sequence[str]) -> str:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    raise MmexSchemaError(f"None of these columns exist: {', '.join(candidates)}")


def _next_id(conn: sqlite3.Connection, table: str, column: str) -> int:
    row = conn.execute(f"SELECT COALESCE(MAX({column}), 0) + 1 FROM {table}").fetchone()
    return int(row[0])


def _ensure_sync_hash_field(conn: sqlite3.Connection) -> int:
    columns = _columns(conn, "CUSTOMFIELD_V1")
    id_col = _first_present(columns, ("FIELDID", "CUSTOMFIELDID"))
    name_col = _first_present(columns, ("DESCRIPTION", "FIELDNAME", "NAME"))
    row = conn.execute(
        f"SELECT {id_col} FROM CUSTOMFIELD_V1 WHERE lower({name_col}) = ?",
        ("sync_hash",),
    ).fetchone()
    if row is not None:
        return int(row[id_col])

    field_id = _next_id(conn, "CUSTOMFIELD_V1", id_col)
    values: dict[str, object] = {id_col: field_id, name_col: "sync_hash"}
    if "REFTYPE" in columns:
        values["REFTYPE"] = "Transaction"
    if "TYPE" in columns:
        values["TYPE"] = "String"
    if "PROPERTIES" in columns:
        values["PROPERTIES"] = ""
    _insert_row(conn, "CUSTOMFIELD_V1", values)
    return field_id


def _sync_data_columns(conn: sqlite3.Connection) -> tuple[str, str, str, str | None]:
    columns = _columns(conn, "CUSTOMFIELDDATA_V1")
    field_col = _first_present(columns, ("FIELDID", "CUSTOMFIELDID"))
    ref_col = _first_present(columns, ("REFID", "TRANSID"))
    content_col = _first_present(columns, ("CONTENT", "VALUE", "DATA"))
    id_col = next(
        (
            candidate
            for candidate in (
                "FIELDATADID",
                "FIELDDATAID",
                "CUSTOMFIELDDATAID",
                "ID",
            )
            if candidate in columns
        ),
        None,
    )
    return field_col, ref_col, content_col, id_col


def _sync_hash_exists(
    conn: sqlite3.Connection,
    field_id: int,
    sync_hash: str,
) -> bool:
    field_col, _ref_col, content_col, _id_col = _sync_data_columns(conn)
    row = conn.execute(
        (
            f"SELECT 1 FROM CUSTOMFIELDDATA_V1 WHERE {field_col} = ? "
            f"AND {content_col} = ? LIMIT 1"
        ),
        (field_id, sync_hash),
    ).fetchone()
    return row is not None


def _insert_sync_hash(
    conn: sqlite3.Connection,
    field_id: int,
    mmex_tx_id: int,
    sync_hash: str,
) -> None:
    field_col, ref_col, content_col, id_col = _sync_data_columns(conn)
    values: dict[str, object] = {
        field_col: field_id,
        ref_col: mmex_tx_id,
        content_col: sync_hash,
    }
    if id_col is not None:
        values[id_col] = _next_id(conn, "CUSTOMFIELDDATA_V1", id_col)
    _insert_row(conn, "CUSTOMFIELDDATA_V1", values)


def _resolve_account_id(conn: sqlite3.Connection, account_alias: str) -> int:
    columns = _columns(conn, "ACCOUNTLIST_V1")
    id_col = _first_present(columns, ("ACCOUNTID",))
    name_col = _first_present(columns, ("ACCOUNTNAME", "ACCOUNTNAME_U"))
    rows = conn.execute(
        f"SELECT {id_col} FROM ACCOUNTLIST_V1 WHERE {name_col} = ?",
        (account_alias,),
    ).fetchall()
    if len(rows) != 1:
        raise MmexMappingError(
            f"MMEX account is not uniquely resolved: {account_alias}"
        )
    return int(rows[0][id_col])


def _resolve_category(
    conn: sqlite3.Connection,
    category_name: str | None,
    subcategory_name: str | None,
) -> tuple[int, int]:
    category = (category_name or "Sin categoria").strip() or "Sin categoria"
    category_id = _get_or_create_named(
        conn,
        table="CATEGORY_V1",
        id_candidates=("CATEGID",),
        name_candidates=("CATEGNAME",),
        name=category,
    )
    if not subcategory_name:
        return category_id, -1

    columns = _columns(conn, "SUBCATEGORY_V1")
    id_col = _first_present(columns, ("SUBCATEGID",))
    name_col = _first_present(columns, ("SUBCATEGNAME",))
    parent_col = _first_present(columns, ("CATEGID",))
    row = conn.execute(
        (
            f"SELECT {id_col} FROM SUBCATEGORY_V1 "
            f"WHERE {name_col} = ? AND {parent_col} = ?"
        ),
        (subcategory_name, category_id),
    ).fetchone()
    if row is not None:
        return category_id, int(row[id_col])
    subcategory_id = _next_id(conn, "SUBCATEGORY_V1", id_col)
    _insert_row(
        conn,
        "SUBCATEGORY_V1",
        {id_col: subcategory_id, name_col: subcategory_name, parent_col: category_id},
    )
    return category_id, subcategory_id


def _resolve_payee_id(
    conn: sqlite3.Connection,
    payee_name: str,
    category_id: int,
    subcategory_id: int,
) -> int:
    columns = _columns(conn, "PAYEE_V1")
    id_col = _first_present(columns, ("PAYEEID",))
    name_col = _first_present(columns, ("PAYEENAME",))
    row = conn.execute(
        f"SELECT {id_col} FROM PAYEE_V1 WHERE {name_col} = ?",
        (payee_name,),
    ).fetchone()
    if row is not None:
        return int(row[id_col])

    payee_id = _next_id(conn, "PAYEE_V1", id_col)
    values: dict[str, object] = {id_col: payee_id, name_col: payee_name}
    if "CATEGID" in columns:
        values["CATEGID"] = category_id
    if "SUBCATEGID" in columns:
        values["SUBCATEGID"] = subcategory_id
    _insert_row(conn, "PAYEE_V1", values)
    return payee_id


def _get_or_create_named(
    conn: sqlite3.Connection,
    *,
    table: str,
    id_candidates: Sequence[str],
    name_candidates: Sequence[str],
    name: str,
) -> int:
    columns = _columns(conn, table)
    id_col = _first_present(columns, id_candidates)
    name_col = _first_present(columns, name_candidates)
    row = conn.execute(
        f"SELECT {id_col} FROM {table} WHERE {name_col} = ?",
        (name,),
    ).fetchone()
    if row is not None:
        return int(row[id_col])
    row_id = _next_id(conn, table, id_col)
    _insert_row(conn, table, {id_col: row_id, name_col: name})
    return row_id


def _insert_checking_tx(
    conn: sqlite3.Connection,
    tx: CanonicalTx,
    *,
    account_id: int,
    payee_id: int,
    category_id: int,
    subcategory_id: int,
) -> int:
    columns = _columns(conn, "CHECKINGACCOUNT_V1")
    trans_id_col = _first_present(columns, ("TRANSID",))
    trans_id = _next_id(conn, "CHECKINGACCOUNT_V1", trans_id_col)
    tx_date = tx.posted_date or tx.event_date or tx.booking_date
    if tx_date is None:
        raise MmexMappingError("Transaction date is required for SQL writer")

    values: dict[str, object] = {
        trans_id_col: trans_id,
        "ACCOUNTID": account_id,
        "TOACCOUNTID": -1,
        "PAYEEID": payee_id,
        "TRANSCODE": "Withdrawal" if tx.direction == "debit" else "Deposit",
        "TRANSAMOUNT": _amount_value(tx.amount),
        "STATUS": "N",
        "TRANSACTIONNUMBER": tx.source_ref or "",
        "NOTES": _notes(tx),
        "CATEGID": category_id,
        "SUBCATEGID": subcategory_id,
        "TRANSDATE": tx_date.isoformat(),
        "FOLLOWUPID": -1,
        "TOTRANSAMOUNT": 0,
        "COLOR": "",
        "DELETEDTIME": "",
    }
    filtered = {key: value for key, value in values.items() if key in columns}
    required = {"ACCOUNTID", "PAYEEID", "TRANSCODE", "TRANSAMOUNT", "TRANSDATE"}
    missing = required - set(filtered)
    if missing:
        raise MmexSchemaError(
            f"CHECKINGACCOUNT_V1 missing required columns: {sorted(missing)}"
        )
    _insert_row(conn, "CHECKINGACCOUNT_V1", filtered)
    return trans_id


def _amount_value(amount: Decimal) -> str:
    return str(amount.quantize(Decimal("0.00")))


def _payee_name(tx: CanonicalTx) -> str:
    name = (tx.merchant_norm or tx.merchant_raw).strip()
    if not name:
        raise MmexMappingError("Payee/merchant is required for SQL writer")
    return name


def _notes(tx: CanonicalTx) -> str:
    parts = [
        "FinanzasMMEX",
        f"source={tx.source_type}",
        f"parser={tx.parser_name}:{tx.parser_version}",
    ]
    if tx.fitid_synthetic:
        parts.append(f"sync_hash={tx.fitid_synthetic}")
    return " | ".join(parts)


def _insert_row(
    conn: sqlite3.Connection,
    table: str,
    values: Mapping[str, object],
) -> None:
    columns = list(values)
    placeholders = ", ".join("?" for _ in columns)
    column_sql = ", ".join(columns)
    conn.execute(
        f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})",
        [values[column] for column in columns],
    )
