import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_cli(
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, "-m", "finanzasmmex.cli", *args],
        check=False,
        capture_output=True,
        text=True,
        env=merged_env,
    )


def parse_stdout(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout)


def test_missing_command_returns_json_validation_error() -> None:
    result = run_cli()

    payload = parse_stdout(result)
    assert result.returncode == 2
    assert payload["ok"] is False
    assert payload["data"] is None
    assert payload["errors"][0]["code"] == "VALIDATION_ERROR"
    assert payload["warnings"] == []
    assert payload["run_id"]


def test_root_help_returns_json_envelope() -> None:
    result = run_cli("--help")

    payload = parse_stdout(result)
    assert result.returncode == 0
    assert payload["ok"] is True
    assert "usage:" in payload["data"]["help"]
    assert payload["errors"] == []


def test_subcommand_help_returns_json_envelope() -> None:
    result = run_cli("run", "--help")

    payload = parse_stdout(result)
    assert result.returncode == 0
    assert payload["ok"] is True
    assert "--source" in payload["data"]["help"]
    assert payload["errors"] == []


def test_invalid_argument_returns_json_validation_error() -> None:
    result = run_cli("run", "--source", "bad")

    payload = parse_stdout(result)
    assert result.returncode == 2
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "VALIDATION_ERROR"


def test_run_success_returns_full_envelope(tmp_path) -> None:
    result = run_cli(
        "run",
        "--source",
        "gmail",
        "--writer",
        "ofx",
        "--input",
        str(ROOT / "tests" / "fixtures" / "gmail"),
        "--db",
        str(tmp_path / "staging.db"),
        "--ofx-output",
        str(tmp_path / "bancoestado.ofx"),
        "--report-output",
        str(tmp_path / "review.html"),
    )

    payload = parse_stdout(result)
    assert result.returncode == 0
    assert payload["ok"] is True
    assert payload["data"]["source"] == "gmail"
    assert payload["data"]["writer"] == "ofx"
    assert payload["data"]["items_processed"] == 1
    assert payload["data"]["items_review"] == 1
    assert Path(payload["data"]["ofx_path"]).is_file()
    assert Path(payload["data"]["report_path"]).is_file()
    assert payload["errors"] == []
    assert payload["warnings"] == []
    assert payload["run_id"]


def test_run_without_input_returns_credentials_error() -> None:
    result = run_cli("run", "--source", "gmail", "--writer", "ofx")

    payload = parse_stdout(result)
    assert result.returncode == 3
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "CREDENTIALS_REQUIRED"
    assert payload["errors"][0]["details"]["offline_flag"] == "--input"


def test_run_mp_offline_input_succeeds(tmp_path) -> None:
    fixture = ROOT / "tests" / "fixtures" / "mp_api" / "payment_anonymized.json"
    result = run_cli(
        "run",
        "--source",
        "mp",
        "--writer",
        "ofx",
        "--input",
        str(fixture),
        "--db",
        str(tmp_path / "staging.db"),
        "--ofx-output",
        str(tmp_path / "mp.ofx"),
        "--report-output",
        str(tmp_path / "review.html"),
    )

    payload = parse_stdout(result)
    assert result.returncode == 0
    assert payload["ok"] is True
    assert payload["data"]["source"] == "mp"
    assert payload["data"]["items_processed"] == 1
    assert Path(payload["data"]["ofx_path"]).is_file()
    # Token must never be echoed in any envelope field.
    assert "access_token" not in result.stdout.lower()


def test_run_mp_without_input_or_token_returns_credentials_error() -> None:
    result = run_cli(
        "run",
        "--source",
        "mp",
        "--writer",
        "ofx",
        env={"FINANZASMMEX_DISABLE_VAULT": "1"},
    )

    payload = parse_stdout(result)
    assert result.returncode == 3
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "CREDENTIALS_REQUIRED"
    assert payload["errors"][0]["details"]["login_command"].endswith("--source mp")


def test_login_mp_requires_token_env_var() -> None:
    result = run_cli(
        "login",
        "--source",
        "mp",
        env={"MP_ACCESS_TOKEN": "", "FINANZASMMEX_DISABLE_VAULT": "1"},
    )

    payload = parse_stdout(result)
    assert result.returncode == 3
    assert payload["errors"][0]["code"] == "CREDENTIALS_REQUIRED"
    assert payload["errors"][0]["details"]["expected_env"] == "MP_ACCESS_TOKEN"


def test_login_mp_does_not_echo_token_value_on_failure() -> None:
    sentinel = "SENTINEL-TOKEN-DO-NOT-LEAK-9b3c1e"
    result = run_cli(
        "login",
        "--source",
        "mp",
        env={"MP_ACCESS_TOKEN": sentinel, "FINANZASMMEX_DISABLE_VAULT": "1"},
    )

    # Disabled vault means set_secret still runs; we cannot guarantee storage
    # without keyring, but we can guarantee the envelope never echoes the token.
    assert sentinel not in result.stdout
    assert sentinel not in result.stderr


def test_login_mp_invalid_source_validation_error() -> None:
    result = run_cli("login", "--source", "gmail")
    payload = parse_stdout(result)
    assert result.returncode == 2
    assert payload["errors"][0]["code"] == "VALIDATION_ERROR"


def test_init_missing_schema_returns_validation_error(tmp_path) -> None:
    result = run_cli(
        "init",
        "--db",
        str(tmp_path / "staging.db"),
        "--schema",
        str(tmp_path / "missing.sql"),
    )

    payload = parse_stdout(result)
    assert result.returncode == 2
    assert payload["ok"] is False
    assert payload["data"] is None
    assert payload["errors"][0]["code"] == "VALIDATION_ERROR"
    assert payload["errors"][0]["details"]["schema_path"].endswith("missing.sql")
    assert payload["warnings"] == []
