# BAD: removed `run_id` from envelope (breaking change). Reused exit code 1
# (not in mapped set 0/2/3/4/5). Validation error returns exit code 1 instead of 2.
import json
import sys


def emit(ok: bool, data=None, errors=None) -> None:
    # VIOLATION: missing `warnings` and `run_id`
    payload = {"ok": ok, "data": data, "errors": errors or []}
    sys.stdout.write(json.dumps(payload) + "\n")


def cmd_init(args) -> int:
    if not args.db:
        emit(ok=False, errors=[{"code": "BAD_ARGS", "message": "missing --db"}])
        return 1  # VIOLATION: should be 2 for validation
    emit(ok=True, data={"db_path": args.db})
    return 0
