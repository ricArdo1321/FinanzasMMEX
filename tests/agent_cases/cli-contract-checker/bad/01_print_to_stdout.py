# BAD: bare prints to stdout corrupt JSON envelope; no run_id; ANSI colors used.
import sys


def cmd_run(args) -> int:
    print("\033[32m[OK]\033[0m starting run...")  # VIOLATION: ANSI + non-JSON to stdout
    print("Processing 12 items")  # VIOLATION: text to stdout
    sys.stdout.write('{"ok": true, "data": null}\n')  # VIOLATION: missing fields
    return 0
