# BAD: references productive finanza.mmb directly. Absolute blocker.
# Also: no BEGIN IMMEDIATE, no rollback, no backup.
import sqlite3
from pathlib import Path

MMEX_DB = Path("C:/Finanzas/finanza.mmb")  # VIOLATION: productive .mmb


def write_batch(rows):
    conn = sqlite3.connect(str(MMEX_DB))  # VIOLATION: no timeout=0
    for row in rows:
        conn.execute(
            "INSERT INTO CHECKINGACCOUNT_V1 (TRANSDATE, TRANSAMOUNT) VALUES (?, ?)",
            (row["date"], row["amount"]),
        )  # VIOLATION: no transaction wrap, no dedup, no sync_hash
    conn.commit()
    conn.close()
    # VIOLATION: no backup pre/post
