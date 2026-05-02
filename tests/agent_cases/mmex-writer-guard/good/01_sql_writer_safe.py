# GOOD: BEGIN IMMEDIATE wrap, ROLLBACK on error, sync_hash atomic with row insert,
# dedup by sync_hash before insert, lock detect timeout=0, backup pre/post,
# only finanza_test.mmb referenced.
import shutil
import sqlite3
from pathlib import Path
from typing import Iterable

MMEX_TEST_DB = Path("C:/Finanzas/finanza_test.mmb")  # PRODUCTION path NOT touched
BACKUP_DIR = Path("C:/Finanzas/backups")  # outside repo, configurable in real code


def _backup(label: str) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dst = BACKUP_DIR / f"{label}_{MMEX_TEST_DB.name}"
    shutil.copy2(MMEX_TEST_DB, dst)
    return dst


def write_batch(rows: Iterable[dict], reconcile_status: str) -> None:
    if reconcile_status == "off":
        raise RuntimeError("reconcile descuadrado, writer bloqueado")

    _backup("pre")
    conn = sqlite3.connect(str(MMEX_TEST_DB), timeout=0)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for row in rows:
            existing = conn.execute(
                "SELECT 1 FROM CUSTOMFIELDDATA_V1 WHERE CONTENT = ?",
                (row["sync_hash"],),
            ).fetchone()
            if existing:
                continue
            cur = conn.execute(
                "INSERT INTO CHECKINGACCOUNT_V1 (ACCOUNTID, TRANSDATE, TRANSAMOUNT) "
                "VALUES (?, ?, ?)",
                (row["account_id"], row["date"], row["amount"]),
            )
            conn.execute(
                "INSERT INTO CUSTOMFIELDDATA_V1 (FIELDID, REFID, CONTENT) VALUES (?, ?, ?)",
                (row["sync_field_id"], cur.lastrowid, row["sync_hash"]),
            )
        conn.commit()
    except sqlite3.OperationalError as e:
        conn.rollback()
        if "locked" in str(e).lower():
            raise SystemExit(4)  # exit code 4 = MMEX lock
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    _backup("post")
