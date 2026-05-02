import sqlite3
import json
from decimal import Decimal
from datetime import date
from typing import List, Optional
from ..models import CanonicalTx

class StagingRepo:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self, schema_path: str):
        with open(schema_path, 'r') as f:
            schema = f.read()
        with self._get_connection() as conn:
            conn.executescript(schema)

    def upsert_tx(self, tx: CanonicalTx):
        sql = """
        INSERT INTO canonical_tx (
            tx_uid, owner, source_type, source_file, source_ref, content_sha256, raw_text,
            event_date, booking_date, posted_date, amount, currency, direction,
            account_alias, card_last4, merchant_raw, merchant_norm, tx_type,
            category_guess, subcategory_guess, tags_json, fitid_synthetic,
            parser_name, parser_version, needs_review, review_reason,
            mmex_account_id, mmex_tx_id, mmex_status, transfer_pair_uid
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(fitid_synthetic) DO UPDATE SET
            mmex_status = excluded.mmex_status,
            updated_at = datetime('now')
        """
        params = (
            tx.tx_uid, tx.owner, tx.source_type, tx.source_file, tx.source_ref, tx.content_sha256, tx.raw_text,
            tx.event_date.isoformat() if tx.event_date else None,
            tx.booking_date.isoformat() if tx.booking_date else None,
            tx.posted_date.isoformat() if tx.posted_date else None,
            float(tx.amount), tx.currency, tx.direction,
            tx.account_alias, tx.card_last4, tx.merchant_raw, tx.merchant_norm, tx.tx_type,
            tx.category_guess, tx.subcategory_guess, json.dumps(tx.tags), tx.fitid_synthetic,
            tx.parser_name, tx.parser_version, 1 if tx.needs_review else 0, tx.review_reason,
            tx.mmex_account_id, tx.mmex_tx_id, tx.mmex_status, tx.transfer_pair_uid
        )
        with self._get_connection() as conn:
            conn.execute(sql, params)

    def get_pending_txs(self) -> List[CanonicalTx]:
        sql = "SELECT * FROM canonical_tx WHERE mmex_status = 'pending'"
        with self._get_connection() as conn:
            rows = conn.execute(sql).fetchall()
            return [self._row_to_tx(row) for row in rows]

    def _row_to_tx(self, row: sqlite3.Row) -> CanonicalTx:
        return CanonicalTx(
            tx_uid=row['tx_uid'],
            owner=row['owner'],
            source_type=row['source_type'],
            source_file=row['source_file'],
            source_ref=row['source_ref'],
            content_sha256=row['content_sha256'],
            raw_text=row['raw_text'],
            event_date=date.fromisoformat(row['event_date']) if row['event_date'] else None,
            booking_date=date.fromisoformat(row['booking_date']) if row['booking_date'] else None,
            posted_date=date.fromisoformat(row['posted_date']) if row['posted_date'] else None,
            amount=Decimal(str(row['amount'])),
            currency=row['currency'],
            direction=row['direction'],
            account_alias=row['account_alias'],
            card_last4=row['card_last4'],
            merchant_raw=row['merchant_raw'],
            merchant_norm=row['merchant_norm'],
            tx_type=row['tx_type'],
            category_guess=row['category_guess'],
            subcategory_guess=row['subcategory_guess'],
            tags=json.loads(row['tags_json']),
            fitid_synthetic=row['fitid_synthetic'],
            parser_name=row['parser_name'],
            parser_version=row['parser_version'],
            needs_review=bool(row['needs_review']),
            review_reason=row['review_reason'],
            mmex_account_id=row['mmex_account_id'],
            mmex_tx_id=row['mmex_tx_id'],
            mmex_status=row['mmex_status'],
            transfer_pair_uid=row['transfer_pair_uid']
        )
