# GOOD: single envelope helper, exit codes mapped, logs to stderr, JSON-only stdout.
import json
import sys
import uuid


def emit(
    ok: bool,
    data=None,
    errors=None,
    warnings=None,
    run_id: str | None = None,
) -> None:
    payload = {
        "ok": ok,
        "data": data,
        "errors": errors or [],
        "warnings": warnings or [],
        "run_id": run_id or str(uuid.uuid4()),
    }
    sys.stdout.write(json.dumps(payload) + "\n")


def cmd_init(args) -> int:
    try:
        # ... initialize db
        emit(ok=True, data={"db_path": args.db})
        return 0
    except ValueError as e:
        emit(ok=False, errors=[{"code": "VALIDATION", "message": str(e), "details": None}])
        return 2
    except PermissionError as e:
        emit(
            ok=False,
            errors=[{"code": "CREDENTIALS", "message": str(e), "details": None}],
        )
        return 3
