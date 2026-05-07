import json
import sqlite3
from contextlib import closing
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, List

from ..etl.categorize import CategoryRule
from ..models import CanonicalTx


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
        sql = """
        INSERT INTO canonical_tx (
            tx_uid, owner, source_type, source_file, source_ref,
            content_sha256, raw_text,
            event_date, booking_date, posted_date, amount, currency, direction,
            account_alias, card_last4, merchant_raw, merchant_norm, tx_type,
            category_guess, subcategory_guess, tags_json, fitid_synthetic,
            parser_name, parser_version, needs_review, review_reason,
            mmex_account_id, mmex_tx_id, mmex_status, transfer_pair_uid
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        ON CONFLICT(fitid_synthetic) DO UPDATE SET
            mmex_status = excluded.mmex_status,
            updated_at = datetime('now')
        """
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
        )
        with closing(self._get_connection()) as conn:
            conn.execute(sql, params)
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
        )
