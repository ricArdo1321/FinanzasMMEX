# BAD: No dedup against CUSTOMFIELDDATA_V1.sync_hash. No ROLLBACK on exception.
# Backup hard-coded inside repo (path violation). reconcile_log.status not checked.
import sqlite3
from pathlib import Path

MMEX_TEST_DB = Path("C:/Finanzas/finanza_test.mmb")
BACKUP_DIR = Path(__file__).parent / "backups"  # VIOLATION: backup inside repo


def write_batch(rows):
    BACKUP_DIR.mkdir(exist_ok=True)
    # backup pre only — no post
    conn = sqlite3.connect(str(MMEX_TEST_DB), timeout=0)
    conn.execute("BEGIN IMMEDIATE")
    for row in rows:
        # VIOLATION: no SELECT against CUSTOMFIELDDATA_V1 to dedup before insert
        conn.execute(
            "INSERT INTO CHECKINGACCOUNT_V1 (TRANSDATE, TRANSAMOUNT) VALUES (?, ?)",
            (row["date"], row["amount"]),
        )
    conn.commit()
    # VIOLATION: no try/except → no rollback path
    conn.close()
