# Linux Work Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the work recorded in `linux.md` so Gmail recovery hints, Mercado Pago online ingestion, and the current transfer writer state are production-safe and verifiable.

**Architecture:** Keep the CLI JSON envelope stable and avoid broad redesign. Gmail stays offline-only until real OAuth exists. Mercado Pago online ingestion becomes fail-fast before staging side effects, with explicit credential/temporary error mapping. Internal transfers already have a partial writer fix in the current worktree; finish that with lint, tests, and writer gate validation instead of replacing it.

**Tech Stack:** Python 3.11+, argparse CLI, SQLite staging, Mercado Pago adapter, pytest, ruff, mypy, detect-secrets, optional Codex/Claude specialist gates.

---

## Scope And Files

- Modify: `src/finanzasmmex/cli.py`
  - Remove invalid Gmail login recovery hints.
  - Map Mercado Pago credential and temporary exceptions explicitly.
- Modify: `src/finanzasmmex/orchestrator/jobs.py`
  - Make MP online parse failures fail before staging/OFX side effects.
  - Use `MercadoPagoClient` as a context manager.
- Modify: `src/finanzasmmex/adapters/mp_api.py`
  - Reject negative amounts instead of converting them to positive credits.
- Modify: `src/finanzasmmex/writer/mmex_sql.py`
  - Keep the existing transfer implementation, but finish lint cleanup and rerun writer checks.
- Modify: `tests/test_cli_contract.py`
  - Add CLI contract tests for Gmail credential details and MP online exception mapping.
- Modify: `tests/test_mp_api.py`
  - Add explicit negative amount test.
- Modify or create: `tests/test_mp_online_job.py`
  - Add run-level MP online parse-failure tests.
- Modify: `contracts/CHANGELOG.md`
  - Record behavior changes without changing the envelope schema.
- Modify: `linux.md`
  - Correct the inaccurate Gmail login note and add current verification evidence.
- Modify: `tareas/a-hacer.md`
  - Track this plan and execution checklist.

## Task 1: Establish Current Baseline

**Files:**
- Read: `linux.md`
- Read: `src/finanzasmmex/cli.py`
- Read: `src/finanzasmmex/orchestrator/jobs.py`
- Read: `src/finanzasmmex/adapters/mp_api.py`
- Read: `src/finanzasmmex/writer/mmex_sql.py`

- [ ] **Step 1: Confirm worktree state**

Run:

```powershell
git status --short
```

Expected:

```text
Shows existing user/worktree changes. Do not revert unrelated files.
```

- [ ] **Step 2: Confirm targeted Linux-work tests still pass before edits**

Run:

```powershell
& 'C:\Users\sqsri\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_cli_contract.py tests/test_phase1_job.py tests/test_mp_api.py tests/test_cmr_email.py tests/test_mach_email.py --basetemp 'C:\tmp\pytest-finanzasmmex-linux-work'
```

Expected:

```text
54 passed
```

- [ ] **Step 3: Confirm transfer writer current state**

Run:

```powershell
& 'C:\Users\sqsri\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_mmex_sql_writer.py::test_transfer_inserts_one_mmex_row tests/test_mmex_sql_writer.py::test_transfer_idempotent tests/test_mmex_sql_writer.py::test_transfer_incomplete_pair_rejected tests/test_mmex_sql_writer.py::test_transfer_rollback_on_mapping_error tests/test_mmex_sql_writer.py::test_transfer_both_staging_tx_uids_in_summary --basetemp 'C:\tmp\pytest-finanzasmmex-transfer-plan'
```

Expected:

```text
5 passed
```

## Task 2: Fix Gmail Credential Recovery Contract

**Files:**
- Modify: `src/finanzasmmex/cli.py`
- Modify: `tests/test_cli_contract.py`
- Modify: `contracts/CHANGELOG.md`

- [ ] **Step 1: Add failing tests for unsupported Gmail login hints**

Add to `tests/test_cli_contract.py`:

```python
def test_run_gmail_without_input_does_not_advertise_unsupported_login() -> None:
    result = run_cli("run", "--source", "gmail", "--writer", "ofx")

    payload = parse_stdout(result)
    details = payload["errors"][0]["details"]

    assert result.returncode == 3
    assert payload["errors"][0]["code"] == "CREDENTIALS_REQUIRED"
    assert details["offline_flag"] == "--input"
    assert "login_command" not in details


def test_run_all_without_input_does_not_advertise_unsupported_gmail_login() -> None:
    result = run_cli("run", "--source", "all", "--writer", "ofx")

    payload = parse_stdout(result)
    details = payload["errors"][0]["details"]

    assert result.returncode == 3
    assert payload["errors"][0]["code"] == "CREDENTIALS_REQUIRED"
    assert details["offline_flag"] == "--input"
    assert "login_command" not in details
```

- [ ] **Step 2: Run the new tests and confirm they fail**

Run:

```powershell
& 'C:\Users\sqsri\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_cli_contract.py::test_run_gmail_without_input_does_not_advertise_unsupported_login tests/test_cli_contract.py::test_run_all_without_input_does_not_advertise_unsupported_gmail_login --basetemp 'C:\tmp\pytest-finanzasmmex-gmail-contract'
```

Expected:

```text
FAIL because details still includes login_command
```

- [ ] **Step 3: Remove the invalid Gmail login command from CLI error details**

In `src/finanzasmmex/cli.py`, replace both Gmail credential details blocks with:

```python
"details": {
    "source": args.source,
    "offline_flag": "--input",
    "available_mode": "offline_input_only",
},
```

Apply this in:

- `_run_gmail()`
- `_run_gmail_all()`

- [ ] **Step 4: Run the Gmail contract tests**

Run:

```powershell
& 'C:\Users\sqsri\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_cli_contract.py::test_run_gmail_without_input_does_not_advertise_unsupported_login tests/test_cli_contract.py::test_run_all_without_input_does_not_advertise_unsupported_gmail_login --basetemp 'C:\tmp\pytest-finanzasmmex-gmail-contract'
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Document the contract note**

Append to `contracts/CHANGELOG.md`:

```markdown
## 2026-05-07 - Gmail credential recovery hint

### Changed

- `run --source gmail` and `run --source all` no longer advertise
  `finanzasmmex login --source gmail`, because Gmail OAuth login is not
  implemented yet. The commands still return `CREDENTIALS_REQUIRED` exit `3`
  and keep `offline_flag: "--input"` for offline ingestion.

### Breaking changes

None. The envelope schema is unchanged.
```

## Task 3: Map Mercado Pago Online Errors Explicitly

**Files:**
- Modify: `src/finanzasmmex/cli.py`
- Modify: `tests/test_cli_contract.py`

- [ ] **Step 1: Add unit-level CLI tests for MP online exceptions**

Add to `tests/test_cli_contract.py`:

```python
import argparse

import pytest

from finanzasmmex import cli
from finanzasmmex.adapters.mp_api import (
    MercadoPagoCredentialsError,
    MercadoPagoTemporaryError,
)


def _mp_online_args(tmp_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        input=None,
        source="mp",
        writer="ofx",
        db=str(tmp_path / "staging.db"),
        schema=str(ROOT / "src" / "finanzasmmex" / "staging" / "schema.sql"),
        ofx_output=str(tmp_path / "mp.ofx"),
        report_output=str(tmp_path / "review.html"),
        begin_date="2026-05-01",
        end_date="2026-05-07",
    )


def test_run_mp_online_credentials_error_maps_exit_3(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    def raise_credentials(**kwargs):
        raise MercadoPagoCredentialsError("mp_credentials_invalid:http_401")

    monkeypatch.setenv("MP_ACCESS_TOKEN", "TEST-TOKEN")
    monkeypatch.setenv("FINANZASMMEX_DISABLE_VAULT", "1")
    monkeypatch.setattr(cli, "run_mp_online", raise_credentials)

    with pytest.raises(SystemExit) as exc:
        cli._run_mp(_mp_online_args(tmp_path))

    payload = json.loads(capsys.readouterr().out)
    assert exc.value.code == 3
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "CREDENTIALS_REQUIRED"
    assert "TEST-TOKEN" not in json.dumps(payload)


def test_run_mp_online_temporary_error_maps_exit_5(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    def raise_temporary(**kwargs):
        raise MercadoPagoTemporaryError("mp_server_error:http_503")

    monkeypatch.setenv("MP_ACCESS_TOKEN", "TEST-TOKEN")
    monkeypatch.setenv("FINANZASMMEX_DISABLE_VAULT", "1")
    monkeypatch.setattr(cli, "run_mp_online", raise_temporary)

    with pytest.raises(SystemExit) as exc:
        cli._run_mp(_mp_online_args(tmp_path))

    payload = json.loads(capsys.readouterr().out)
    assert exc.value.code == 5
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "TEMPORARY_FAILURE"
    assert "TEST-TOKEN" not in json.dumps(payload)
```

- [ ] **Step 2: Run and confirm failures**

Run:

```powershell
& 'C:\Users\sqsri\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_cli_contract.py::test_run_mp_online_credentials_error_maps_exit_3 tests/test_cli_contract.py::test_run_mp_online_temporary_error_maps_exit_5 --basetemp 'C:\tmp\pytest-finanzasmmex-mp-contract'
```

Expected:

```text
At least credential test fails with exit 5 until CLI catches MercadoPagoCredentialsError.
```

- [ ] **Step 3: Import MP exceptions in CLI**

In `src/finanzasmmex/cli.py`, add:

```python
from .adapters.mp_api import MercadoPagoCredentialsError, MercadoPagoTemporaryError
```

- [ ] **Step 4: Catch MP online exceptions around `run_mp_online()`**

Replace the direct `result = run_mp_online(...)` call in `_run_mp()` with:

```python
    try:
        result = run_mp_online(
            access_token=token,
            begin_date=begin_date,
            end_date=end_date,
            db_path=args.db,
            schema_path=args.schema,
            ofx_output_path=args.ofx_output,
            report_output_path=args.report_output,
        )
    except MercadoPagoCredentialsError as exc:
        _emit(
            False,
            errors=[
                {
                    "code": "CREDENTIALS_REQUIRED",
                    "message": "Mercado Pago access token is invalid or expired",
                    "details": {
                        "source": args.source,
                        "login_command": "finanzasmmex login --source mp",
                        "exception_type": type(exc).__name__,
                    },
                }
            ],
            exit_code=3,
        )
    except MercadoPagoTemporaryError as exc:
        _emit(
            False,
            errors=[
                {
                    "code": "TEMPORARY_FAILURE",
                    "message": "Mercado Pago API request failed temporarily",
                    "details": {"source": args.source, "exception_type": type(exc).__name__},
                }
            ],
            exit_code=5,
        )
```

- [ ] **Step 5: Run MP contract tests**

Run:

```powershell
& 'C:\Users\sqsri\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_cli_contract.py::test_run_mp_online_credentials_error_maps_exit_3 tests/test_cli_contract.py::test_run_mp_online_temporary_error_maps_exit_5 --basetemp 'C:\tmp\pytest-finanzasmmex-mp-contract'
```

Expected:

```text
2 passed
```

## Task 4: Prevent Silent Drops In MP Online Ingestion

**Files:**
- Modify: `src/finanzasmmex/orchestrator/jobs.py`
- Create: `tests/test_mp_online_job.py`

- [ ] **Step 1: Add tests proving parse failure aborts before side effects**

Create `tests/test_mp_online_job.py`:

```python
import json
import sqlite3
from pathlib import Path

import pytest

from finanzasmmex.adapters.mp_api import MercadoPagoParseError
from finanzasmmex.orchestrator import jobs
from finanzasmmex.orchestrator.jobs import run_mp_online

ROOT = Path(__file__).resolve().parents[1]


class FakeMercadoPagoClient:
    def __init__(self, access_token: str) -> None:
        self.access_token = access_token

    def __enter__(self) -> "FakeMercadoPagoClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def search_payments(self, **kwargs):
        fixture = json.loads(
            (ROOT / "tests" / "fixtures" / "mp_api" / "payment_anonymized.json")
            .read_text(encoding="utf-8")
        )
        malformed = dict(fixture)
        malformed["id"] = "bad-approved-payment"
        malformed["currency_id"] = "USD"
        return [fixture, malformed]


def test_run_mp_online_parse_failure_aborts_before_staging(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(jobs, "MercadoPagoClient", FakeMercadoPagoClient, raising=False)

    db_path = tmp_path / "staging.db"
    ofx_path = tmp_path / "mp.ofx"
    report_path = tmp_path / "review.html"

    with pytest.raises(MercadoPagoParseError, match="bad-approved-payment"):
        run_mp_online(
            access_token="TEST-TOKEN",
            begin_date="2026-05-01",
            end_date="2026-05-07",
            db_path=str(db_path),
            schema_path=str(ROOT / "src" / "finanzasmmex" / "staging" / "schema.sql"),
            ofx_output_path=str(ofx_path),
            report_output_path=str(report_path),
        )

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM canonical_tx").fetchone()[0]
    assert count == 0
    assert not ofx_path.exists()
    assert not report_path.exists()
```

- [ ] **Step 2: Run and confirm failure**

Run:

```powershell
& 'C:\Users\sqsri\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_mp_online_job.py --basetemp 'C:\tmp\pytest-finanzasmmex-mp-online'
```

Expected:

```text
FAIL because the current loop catches ValueError and continues.
```

- [ ] **Step 3: Move client import to module scope**

In `src/finanzasmmex/orchestrator/jobs.py`, add near existing imports:

```python
from ..adapters.mp_api import MercadoPagoClient, MercadoPagoParseError
```

Remove the local `from ..adapters.mp_api import MercadoPagoClient` inside `run_mp_online()`.

- [ ] **Step 4: Parse all MP payments before staging side effects**

Replace the loop in `run_mp_online()` with:

```python
    payments: list[Mapping[str, Any]]
    with MercadoPagoClient(access_token=access_token) as client:
        payments = list(
            client.search_payments(
                begin_date=begin_date,
                end_date=end_date,
                status="approved",
                page_size=page_size,
            )
        )

    transactions: list[CanonicalTx] = []
    for payment in payments:
        try:
            parsed = parse_payment(payment, owner=owner)
        except ValueError as exc:
            ref = str(payment.get("id") or payment.get("external_reference") or "<unknown>")
            raise MercadoPagoParseError(
                f"Approved Mercado Pago payment could not be parsed: {ref}"
            ) from exc
        transactions.append(prepare_for_staging(parsed))

    if not transactions:
        raise ValueError("No approved Mercado Pago payments found in date range")

    for tx in transactions:
        repo.upsert_tx(tx)
```

This preserves the existing output contract for success and removes the silent-drop behavior.

- [ ] **Step 5: Run MP online tests**

Run:

```powershell
& 'C:\Users\sqsri\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_mp_online_job.py tests/test_phase1_job.py tests/test_mp_api.py --basetemp 'C:\tmp\pytest-finanzasmmex-mp-online'
```

Expected:

```text
All selected tests passed
```

## Task 5: Reject Negative MP Amounts

**Files:**
- Modify: `src/finanzasmmex/adapters/mp_api.py`
- Modify: `tests/test_mp_api.py`

- [ ] **Step 1: Add explicit negative amount test**

Replace `test_parse_payment_rejects_zero_or_negative_amount()` in `tests/test_mp_api.py` with:

```python
@pytest.mark.parametrize("amount", [0, -12500, "-12500.00"])
def test_parse_payment_rejects_zero_or_negative_amount(amount) -> None:
    payload = _payment_payload()
    payload["transaction_amount"] = amount
    with pytest.raises(ValueError, match="must be > 0"):
        parse_payment(payload)
```

- [ ] **Step 2: Run and confirm negative cases fail**

Run:

```powershell
& 'C:\Users\sqsri\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_mp_api.py::test_parse_payment_rejects_zero_or_negative_amount --basetemp 'C:\tmp\pytest-finanzasmmex-mp-negative'
```

Expected:

```text
FAIL for negative values until copy_abs is removed.
```

- [ ] **Step 3: Remove `copy_abs()`**

In `src/finanzasmmex/adapters/mp_api.py`, replace:

```python
    amount = amount.copy_abs().quantize(Decimal("0.00"))
```

with:

```python
    amount = amount.quantize(Decimal("0.00"))
```

Keep:

```python
    if amount <= 0:
        raise MercadoPagoParseError("MP transaction_amount must be > 0")
```

- [ ] **Step 4: Run MP parser tests**

Run:

```powershell
& 'C:\Users\sqsri\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_mp_api.py --basetemp 'C:\tmp\pytest-finanzasmmex-mp-negative'
```

Expected:

```text
All tests in tests/test_mp_api.py passed
```

## Task 6: Finish Transfer Writer Cleanup

**Files:**
- Modify: `src/finanzasmmex/writer/mmex_sql.py`
- Test: `tests/test_mmex_sql_writer.py`

- [ ] **Step 1: Confirm current transfer tests are green**

Run:

```powershell
& 'C:\Users\sqsri\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_mmex_sql_writer.py::test_transfer_inserts_one_mmex_row tests/test_mmex_sql_writer.py::test_transfer_idempotent tests/test_mmex_sql_writer.py::test_transfer_incomplete_pair_rejected tests/test_mmex_sql_writer.py::test_transfer_rollback_on_mapping_error tests/test_mmex_sql_writer.py::test_transfer_both_staging_tx_uids_in_summary --basetemp 'C:\tmp\pytest-finanzasmmex-transfer'
```

Expected:

```text
5 passed
```

- [ ] **Step 2: Fix ruff line-length failures**

In `src/finanzasmmex/writer/mmex_sql.py`, replace the long assert with:

```python
    assert tx.to_account_alias, (
        "to_account_alias must be set before calling _insert_transfer_tx"
    )
```

Replace the long transfer schema error with:

```python
        raise MmexSchemaError(
            "CHECKINGACCOUNT_V1 missing required columns for Transfer: "
            f"{sorted(missing)}"
        )
```

- [ ] **Step 3: Run writer lint and tests**

Run:

```powershell
& 'C:\Users\sqsri\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m ruff check src/finanzasmmex/writer/mmex_sql.py
& 'C:\Users\sqsri\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_mmex_sql_writer.py --basetemp 'C:\tmp\pytest-finanzasmmex-writer'
```

Expected:

```text
ruff: All checks passed
pytest: all writer tests passed
```

## Task 7: Update Documentation

**Files:**
- Modify: `linux.md`
- Modify: `contracts/CHANGELOG.md`
- Modify: `tareas/a-hacer.md`

- [ ] **Step 1: Correct the Gmail note in `linux.md`**

Replace:

```markdown
**Issue implementado**: Wire CMR + Mach email parsers en CLI/orchestrator + fix login --source gmail.
```

with:

```markdown
**Issue implementado**: Wire CMR + Mach email parsers en CLI/orchestrator.
Gmail OAuth login sigue fuera de alcance; el CLI no debe recomendar
`login --source gmail` hasta que exista.
```

- [ ] **Step 2: Add MP hardening note to `linux.md`**

Append:

```markdown
## 2026-05-07 - Hardening post-review

**Correcciones planificadas**:
- Gmail credential errors: no anunciar `login --source gmail` mientras no exista.
- MP online: mapear 401/403 a `CREDENTIALS_REQUIRED` exit 3.
- MP online: abortar si un pago aprobado no parsea; no hacer upsert parcial.
- MP parser: rechazar montos negativos.
- Writer transfer: mantener una fila MMEX `Transfer` por par y cerrar lint/tests.

**Verificacion esperada**:
- `ruff check src/ tests/`
- `mypy src/`
- `pytest --basetemp C:\tmp\pytest-finanzasmmex-full`
- `detect-secrets scan --baseline .secrets.baseline`
```

- [ ] **Step 3: Add MP behavior notes to `contracts/CHANGELOG.md`**

Append:

```markdown
## 2026-05-07 - Mercado Pago online hardening

### Changed

- MP 401/403 online errors map to `CREDENTIALS_REQUIRED` exit `3`.
- MP temporary/network/server errors map to `TEMPORARY_FAILURE` exit `5`.
- MP online ingestion aborts before staging/OFX side effects if an approved
  payment cannot be parsed.
- MP negative `transaction_amount` values are rejected instead of converted to
  positive credits.

### Breaking changes

None. The envelope schema is unchanged. MP online behavior is stricter for
unsafe source data.
```

## Task 8: Specialist Gates And Final Verification

**Files:**
- Read: `.claude/agents/cli-contract-checker.md`
- Read: `.claude/agents/parser-reviewer.md`
- Read: `.claude/agents/mmex-writer-guard.md`
- Read: `.claude/agents/secrets-pii-auditor.md`

- [ ] **Step 1: Run Python checks**

Run:

```powershell
& 'C:\Users\sqsri\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m ruff check src/ tests/
& 'C:\Users\sqsri\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m mypy src/
& 'C:\Users\sqsri\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest --basetemp 'C:\tmp\pytest-finanzasmmex-full'
```

Expected:

```text
ruff: All checks passed
mypy: Success: no issues found
pytest: all tests passed
```

- [ ] **Step 2: Run secrets scan**

Run:

```powershell
& 'C:\Users\sqsri\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m detect_secrets scan --baseline .secrets.baseline
```

Expected:

```text
Exit code 0, no new findings
```

- [ ] **Step 3: Run specialist reviews**

If the user says to use agents, delegate:

- `cli-contract-checker` for `src/finanzasmmex/cli.py` and `contracts/CHANGELOG.md`.
- `parser-reviewer` for `src/finanzasmmex/adapters/mp_api.py`.
- `mmex-writer-guard` for `src/finanzasmmex/writer/mmex_sql.py`.
- `secrets-pii-auditor` because this touches ingestion/token behavior and is pre-finalization.

If agents are not requested, apply the same `.claude/agents/*.md` checklists locally and report `agent_mode: local-checklist`.

- [ ] **Step 4: Optional WPF contract build**

Run if CLI envelope behavior changed in a way that might affect the desktop consumer:

```powershell
dotnet build FinanzasMMEX.slnx
```

Expected:

```text
Build succeeded
```

## Commit Plan

- [ ] **Commit 1: CLI contract hardening**

```powershell
git add src/finanzasmmex/cli.py tests/test_cli_contract.py contracts/CHANGELOG.md linux.md tareas/a-hacer.md
git commit -m "fix(cli): harden gmail and mp credential contracts"
```

- [ ] **Commit 2: MP online ingestion hardening**

```powershell
git add src/finanzasmmex/orchestrator/jobs.py src/finanzasmmex/adapters/mp_api.py tests/test_mp_online_job.py tests/test_mp_api.py contracts/CHANGELOG.md linux.md
git commit -m "fix(mp): fail safely on online parse edge cases"
```

- [ ] **Commit 3: Transfer writer cleanup**

```powershell
git add src/finanzasmmex/writer/mmex_sql.py tests/test_mmex_sql_writer.py
git commit -m "fix(writer): complete internal transfer SQL path"
```

If the current worktree already groups these changes from prior work, keep commits focused by staging only the files touched by each task.

## Self-Review

- Spec coverage:
  - Gmail unsupported login hint: Task 2.
  - MP credential exit code: Task 3.
  - Silent MP drops: Task 4.
  - Negative MP amount: Task 5.
  - Transfer writer current state: Task 6.
  - Documentation and evidence: Task 7.
  - Gates: Task 8.
- Placeholder scan: No task depends on "TBD" or hidden future work.
- Type consistency:
  - Uses existing `RunSummary`, `CanonicalTx`, `MercadoPagoClient`, and MP exception names.
  - Adds no new envelope schema fields.
