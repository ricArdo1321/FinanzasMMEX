import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, List, Literal
from uuid import uuid4

from ..etl.categorize import CategoryRule
from ..models import CanonicalTx

JobRunStatus = Literal["running", "ok", "error", "deferred"]


@dataclass(frozen=True)
class RawArtifactRecord:
    artifact_id: str
    artifact_type: str
    source_ref: str
    content_sha256: str
    payload_blob: bytes | None
    payload_text: str | None
    fetched_at: str


@dataclass(frozen=True)
class JobRunRecord:
    run_id: str
    job_name: str
    started_at: str
    finished_at: str | None
    status: JobRunStatus
    items_processed: int
    items_inserted: int
    items_review: int
    error_message: str | None
    metadata: dict[str, Any] | None


class StagingRepo:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self, schema_path: str) -> None:
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = f.read()
        with closing(self._get_connection()) as conn:
            conn.executescript(schema)
            conn.commit()

    def upsert_tx(self, tx: CanonicalTx) -> None:
        self.upsert_batch([tx])

    def upsert_batch(self, txs: Iterable[CanonicalTx]) -> None:
        sql = """
        INSERT INTO canonical_tx (
            tx_uid, owner, source_type, source_file, source_ref,
            content_sha256, raw_text,
            event_date, booking_date, posted_date, amount, currency, direction,
            account_alias, card_last4, merchant_raw, merchant_norm, tx_type,
            category_guess, subcategory_guess, tags_json, fitid_synthetic,
            parser_name, parser_version, needs_review, review_reason,
            mmex_account_id, mmex_tx_id, mmex_status, transfer_pair_uid,
            to_account_alias
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?
        )
        ON CONFLICT(fitid_synthetic) DO UPDATE SET
            mmex_status = excluded.mmex_status,
            updated_at = datetime('now')
        """

        batch_params = []
        for tx in txs:
            params = (
                tx.tx_uid,
                tx.owner,
                tx.source_type,
                tx.source_file,
                tx.source_ref,
                tx.content_sha256,
                tx.raw_text,
                tx.event_date.isoformat() if tx.event_date else None,
                tx.booking_date.isoformat() if tx.booking_date else None,
                tx.posted_date.isoformat() if tx.posted_date else None,
                float(tx.amount),
                tx.currency,
                tx.direction,
                tx.account_alias,
                tx.card_last4,
                tx.merchant_raw,
                tx.merchant_norm,
                tx.tx_type,
                tx.category_guess,
                tx.subcategory_guess,
                json.dumps(tx.tags),
                tx.fitid_synthetic,
                tx.parser_name,
                tx.parser_version,
                1 if tx.needs_review else 0,
                tx.review_reason,
                tx.mmex_account_id,
                tx.mmex_tx_id,
                tx.mmex_status,
                tx.transfer_pair_uid,
                tx.to_account_alias,
            )
            batch_params.append(params)

        with closing(self._get_connection()) as conn:
            # Disable FKs during batch upsert to allow circular transfer references
            # (leg A points to leg B which is also being inserted).
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.executemany(sql, batch_params)

            # Ensure integrity before committing
            violations = conn.execute(
                "PRAGMA foreign_key_check(canonical_tx)"
            ).fetchall()
            if violations:
                # Row shape: (table, rowid, parent_table, fkid)
                v = violations[0]
                raise sqlite3.IntegrityError(
                    f"Foreign key constraint failed in {v[0]} rowid {v[1]} "
                    f"referencing {v[2]}"
                )

            conn.commit()

    def get_pending_txs(self) -> List[CanonicalTx]:
        sql = "SELECT * FROM canonical_tx WHERE mmex_status = 'pending'"
        with closing(self._get_connection()) as conn:
            rows = conn.execute(sql).fetchall()
            return [self._row_to_tx(row) for row in rows]

    def list_txs(
        self,
        *,
        owner: str | None = None,
        account_alias: str | None = None,
        mmex_status: str | None = None,
        needs_review_only: bool = False,
        since: str | None = None,
        until: str | None = None,
        source_type: str | None = None,
        category_guess: str | None = None,
        merchant_query: str | None = None,
        limit: int = 200,
    ) -> List[CanonicalTx]:
        clauses: list[str] = []
        params: list[object] = []
        if owner is not None:
            clauses.append("owner = ?")
            params.append(owner)
        if account_alias is not None:
            clauses.append("account_alias = ?")
            params.append(account_alias)
        if mmex_status is not None:
            clauses.append("mmex_status = ?")
            params.append(mmex_status)
        if needs_review_only:
            clauses.append("needs_review = 1")
        if since is not None:
            clauses.append("COALESCE(posted_date, booking_date, event_date) >= ?")
            params.append(since)
        if until is not None:
            clauses.append("COALESCE(posted_date, booking_date, event_date) <= ?")
            params.append(until)
        if source_type is not None:
            clauses.append("source_type = ?")
            params.append(source_type)
        if category_guess is not None:
            clauses.append("category_guess = ?")
            params.append(category_guess)
        if merchant_query is not None:
            clauses.append("(merchant_norm LIKE ? OR merchant_raw LIKE ?)")
            like = f"%{merchant_query}%"
            params.extend([like, like])

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT * FROM canonical_tx "
            f"{where} "
            "ORDER BY COALESCE(posted_date, booking_date, event_date) DESC, "
            "tx_uid ASC "
            "LIMIT ?"
        )
        params.append(int(limit))

        with closing(self._get_connection()) as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_tx(row) for row in rows]

    def get_tx(self, tx_uid: str) -> CanonicalTx | None:
        sql = "SELECT * FROM canonical_tx WHERE tx_uid = ?"
        with closing(self._get_connection()) as conn:
            row = conn.execute(sql, (tx_uid,)).fetchone()
            return self._row_to_tx(row) if row else None

    _UPDATABLE_FIELDS: dict[str, str] = {
        "owner": "owner",
        "category_guess": "category_guess",
        "subcategory_guess": "subcategory_guess",
        "merchant_norm": "merchant_norm",
        "tags_json": "tags_json",
        "needs_review": "needs_review",
        "review_reason": "review_reason",
    }

    def update_tx_fields(self, tx_uid: str, fields: dict[str, object]) -> bool:
        if not fields:
            return False
        unknown = set(fields) - set(self._UPDATABLE_FIELDS)
        if unknown:
            raise ValueError(f"Unsupported review fields: {sorted(unknown)}")

        assignments = ", ".join(f"{col} = ?" for col in fields)
        params = list(fields.values()) + [tx_uid]
        sql = (
            f"UPDATE canonical_tx SET {assignments}, "
            "updated_at = datetime('now') WHERE tx_uid = ?"
        )
        with closing(self._get_connection()) as conn:
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor.rowcount > 0

    def update_mmex_status(self, tx_uid: str, status: str) -> bool:
        sql = (
            "UPDATE canonical_tx SET mmex_status = ?, updated_at = datetime('now') "
            "WHERE tx_uid = ?"
        )
        with closing(self._get_connection()) as conn:
            cursor = conn.execute(sql, (status, tx_uid))
            conn.commit()
            return cursor.rowcount > 0

    def mark_inserted(
        self,
        tx_uid: str,
        *,
        mmex_account_id: int,
        mmex_tx_id: int,
    ) -> bool:
        sql = """
        UPDATE canonical_tx
        SET mmex_status = 'inserted',
            mmex_account_id = ?,
            mmex_tx_id = ?,
            updated_at = datetime('now')
        WHERE tx_uid = ?
        """
        with closing(self._get_connection()) as conn:
            cursor = conn.execute(sql, (mmex_account_id, mmex_tx_id, tx_uid))
            conn.commit()
            return cursor.rowcount > 0

    def get_tx_by_fitid(self, fitid_synthetic: str) -> CanonicalTx | None:
        sql = "SELECT * FROM canonical_tx WHERE fitid_synthetic = ?"
        with closing(self._get_connection()) as conn:
            row = conn.execute(sql, (fitid_synthetic,)).fetchone()
            return self._row_to_tx(row) if row else None

    def has_reconcile_off(self, account_aliases: Iterable[str]) -> bool:
        aliases = sorted(set(account_aliases))
        if not aliases:
            return False
        placeholders = ",".join("?" for _ in aliases)
        sql = (
            "SELECT 1 FROM reconcile_log "
            f"WHERE account_alias IN ({placeholders}) AND status = 'off' LIMIT 1"
        )
        with closing(self._get_connection()) as conn:
            return conn.execute(sql, aliases).fetchone() is not None

    def insert_reconcile_log(
        self,
        *,
        account_alias: str,
        period_start: str,
        period_end: str,
        balance_initial: Decimal,
        balance_final: Decimal,
        sum_credits: Decimal,
        sum_debits: Decimal,
        expected_final: Decimal,
        status: str,
        delta: Decimal,
        notes: str | None = None,
    ) -> int:
        sql = """
        INSERT INTO reconcile_log (
            account_alias, period_start, period_end, balance_initial,
            balance_final, sum_credits, sum_debits, expected_final,
            status, delta, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with closing(self._get_connection()) as conn:
            cursor = conn.execute(
                sql,
                (
                    account_alias,
                    period_start,
                    period_end,
                    float(balance_initial),
                    float(balance_final),
                    float(sum_credits),
                    float(sum_debits),
                    float(expected_final),
                    status,
                    float(delta),
                    notes,
                ),
            )
            conn.commit()
            return cursor.lastrowid  # type: ignore[return-value]

    def insert_raw_artifact(
        self,
        *,
        artifact_type: str,
        source_ref: str,
        content_sha256: str,
        payload_blob: bytes | None = None,
        payload_text: str | None = None,
        artifact_id: str | None = None,
    ) -> str:
        resolved_id = artifact_id or str(uuid4())
        sql = """
        INSERT OR IGNORE INTO raw_artifacts (
            artifact_id, artifact_type, source_ref, content_sha256,
            payload_blob, payload_text
        ) VALUES (?, ?, ?, ?, ?, ?)
        """
        with closing(self._get_connection()) as conn:
            conn.execute(
                sql,
                (
                    resolved_id,
                    artifact_type,
                    source_ref,
                    content_sha256,
                    sqlite3.Binary(payload_blob) if payload_blob is not None else None,
                    payload_text,
                ),
            )
            row = conn.execute(
                "SELECT artifact_id FROM raw_artifacts WHERE content_sha256 = ?",
                (content_sha256,),
            ).fetchone()
            conn.commit()
            if row is None:
                raise sqlite3.IntegrityError("raw_artifacts insert did not persist")
            return str(row["artifact_id"])

    def get_raw_artifact_by_sha(
        self,
        content_sha256: str,
    ) -> RawArtifactRecord | None:
        with closing(self._get_connection()) as conn:
            row = conn.execute(
                "SELECT * FROM raw_artifacts WHERE content_sha256 = ?",
                (content_sha256,),
            ).fetchone()
            return self._row_to_raw_artifact(row) if row else None

    def start_job_run(
        self,
        *,
        job_name: str,
        metadata: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> str:
        resolved_id = run_id or str(uuid4())
        with closing(self._get_connection()) as conn:
            conn.execute(
                """
                INSERT INTO job_runs (
                    run_id, job_name, started_at, status, metadata_json
                ) VALUES (?, ?, datetime('now'), 'running', ?)
                """,
                (
                    resolved_id,
                    job_name,
                    json.dumps(metadata, sort_keys=True) if metadata else None,
                ),
            )
            conn.commit()
            return resolved_id

    def finish_job_run(
        self,
        run_id: str,
        *,
        status: JobRunStatus,
        items_processed: int = 0,
        items_inserted: int = 0,
        items_review: int = 0,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        with closing(self._get_connection()) as conn:
            cursor = conn.execute(
                """
                UPDATE job_runs
                SET finished_at = datetime('now'),
                    status = ?,
                    items_processed = ?,
                    items_inserted = ?,
                    items_review = ?,
                    error_message = ?,
                    metadata_json = COALESCE(?, metadata_json)
                WHERE run_id = ?
                """,
                (
                    status,
                    items_processed,
                    items_inserted,
                    items_review,
                    error_message,
                    json.dumps(metadata, sort_keys=True) if metadata else None,
                    run_id,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def record_job_run(
        self,
        *,
        job_name: str,
        status: JobRunStatus,
        items_processed: int = 0,
        items_inserted: int = 0,
        items_review: int = 0,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> str:
        resolved_id = run_id or str(uuid4())
        with closing(self._get_connection()) as conn:
            conn.execute(
                """
                INSERT INTO job_runs (
                    run_id, job_name, started_at, finished_at, status,
                    items_processed, items_inserted, items_review,
                    error_message, metadata_json
                ) VALUES (?, ?, datetime('now'), datetime('now'), ?, ?, ?, ?, ?, ?)
                """,
                (
                    resolved_id,
                    job_name,
                    status,
                    items_processed,
                    items_inserted,
                    items_review,
                    error_message,
                    json.dumps(metadata, sort_keys=True) if metadata else None,
                ),
            )
            conn.commit()
            return resolved_id

    def get_job_run(self, run_id: str) -> JobRunRecord | None:
        with closing(self._get_connection()) as conn:
            row = conn.execute(
                "SELECT * FROM job_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            return self._row_to_job_run(row) if row else None

    def list_rules(self, *, active_only: bool = False) -> list[CategoryRule]:
        sql = "SELECT * FROM category_rules"
        params: list[Any] = []
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY active DESC, priority ASC, rule_id ASC"
        with closing(self._get_connection()) as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_rule(row) for row in rows]

    def add_rule(
        self,
        *,
        pattern: str,
        pattern_type: str,
        merchant_norm: str,
        category_name: str,
        subcategory_name: str | None = None,
        tags: list[str] | None = None,
        fuzzy_threshold: int = 85,
        priority: int = 100,
    ) -> int:
        sql = """
        INSERT INTO category_rules (
            pattern, pattern_type, merchant_norm, category_name,
            subcategory_name, tags_json, fuzzy_threshold, priority
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        with closing(self._get_connection()) as conn:
            cursor = conn.execute(
                sql,
                (
                    pattern,
                    pattern_type,
                    merchant_norm,
                    category_name,
                    subcategory_name,
                    json.dumps(tags or []),
                    fuzzy_threshold,
                    priority,
                ),
            )
            conn.commit()
            return cursor.lastrowid  # type: ignore[return-value]

    def update_rule(self, rule_id: int, **fields: Any) -> bool:
        allowed = {
            "pattern", "pattern_type", "merchant_norm", "category_name",
            "subcategory_name", "tags_json", "fuzzy_threshold", "priority", "active",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unknown rule fields: {sorted(unknown)}")
        assignments = ", ".join(f"{col} = ?" for col in fields)
        params = list(fields.values()) + [rule_id]
        sql = f"UPDATE category_rules SET {assignments} WHERE rule_id = ?"
        with closing(self._get_connection()) as conn:
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor.rowcount > 0

    def delete_rule(self, rule_id: int) -> bool:
        with closing(self._get_connection()) as conn:
            cursor = conn.execute(
                "DELETE FROM category_rules WHERE rule_id = ?", (rule_id,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def _row_to_rule(self, row: sqlite3.Row) -> CategoryRule:
        return CategoryRule(
            rule_id=row["rule_id"],
            pattern=row["pattern"],
            pattern_type=row["pattern_type"],
            merchant_norm=row["merchant_norm"],
            category_name=row["category_name"],
            subcategory_name=row["subcategory_name"],
            tags=json.loads(row["tags_json"]),
            fuzzy_threshold=row["fuzzy_threshold"],
            priority=row["priority"],
            active=bool(row["active"]),
        )

    def _row_to_raw_artifact(self, row: sqlite3.Row) -> RawArtifactRecord:
        return RawArtifactRecord(
            artifact_id=row["artifact_id"],
            artifact_type=row["artifact_type"],
            source_ref=row["source_ref"],
            content_sha256=row["content_sha256"],
            payload_blob=row["payload_blob"],
            payload_text=row["payload_text"],
            fetched_at=row["fetched_at"],
        )

    def _row_to_job_run(self, row: sqlite3.Row) -> JobRunRecord:
        metadata_json = row["metadata_json"]
        return JobRunRecord(
            run_id=row["run_id"],
            job_name=row["job_name"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            status=row["status"],
            items_processed=row["items_processed"],
            items_inserted=row["items_inserted"],
            items_review=row["items_review"],
            error_message=row["error_message"],
            metadata=json.loads(metadata_json) if metadata_json else None,
        )

    def _row_to_tx(self, row: sqlite3.Row) -> CanonicalTx:
        return CanonicalTx(
            tx_uid=row["tx_uid"],
            owner=row["owner"],
            source_type=row["source_type"],
            source_file=row["source_file"],
            source_ref=row["source_ref"],
            content_sha256=row["content_sha256"],
            raw_text=row["raw_text"],
            event_date=(
                date.fromisoformat(row["event_date"]) if row["event_date"] else None
            ),
            booking_date=(
                date.fromisoformat(row["booking_date"]) if row["booking_date"] else None
            ),
            posted_date=(
                date.fromisoformat(row["posted_date"]) if row["posted_date"] else None
            ),
            amount=Decimal(str(row["amount"])),
            currency=row["currency"],
            direction=row["direction"],
            account_alias=row["account_alias"],
            card_last4=row["card_last4"],
            merchant_raw=row["merchant_raw"],
            merchant_norm=row["merchant_norm"],
            tx_type=row["tx_type"],
            category_guess=row["category_guess"],
            subcategory_guess=row["subcategory_guess"],
            tags=json.loads(row["tags_json"]),
            fitid_synthetic=row["fitid_synthetic"],
            parser_name=row["parser_name"],
            parser_version=row["parser_version"],
            needs_review=bool(row["needs_review"]),
            review_reason=row["review_reason"],
            mmex_account_id=row["mmex_account_id"],
            mmex_tx_id=row["mmex_tx_id"],
            mmex_status=row["mmex_status"],
            transfer_pair_uid=row["transfer_pair_uid"],
            to_account_alias=row["to_account_alias"],
        )
