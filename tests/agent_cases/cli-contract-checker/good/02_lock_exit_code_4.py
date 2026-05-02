# GOOD: exit code 4 for MMEX lock, distinguished from validation/credentials/transient.
import sqlite3

from .envelope import emit


def cmd_run(args) -> int:
    try:
        # ... do work, may attempt to write to mmex
        emit(ok=True, data={"items_inserted": 12}, run_id=args.run_id)
        return 0
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            emit(
                ok=False,
                errors=[
                    {
                        "code": "MMEX_LOCKED",
                        "message": "finanza_test.mmb is locked; close MMEX and retry",
                        "details": {"sqlite_error": str(e)},
                    }
                ],
                run_id=args.run_id,
            )
            return 4
        emit(
            ok=False,
            errors=[{"code": "TRANSIENT", "message": str(e), "details": None}],
            run_id=args.run_id,
        )
        return 5
