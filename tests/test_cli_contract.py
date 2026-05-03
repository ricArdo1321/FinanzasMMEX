import json
import subprocess
import sys


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "finanzasmmex.cli", *args],
        check=False,
        capture_output=True,
        text=True,
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


def test_run_success_returns_full_envelope() -> None:
    result = run_cli("run", "--source", "gmail", "--writer", "ofx")

    payload = parse_stdout(result)
    assert result.returncode == 0
    assert payload["ok"] is True
    assert payload["data"]["source"] == "gmail"
    assert payload["data"]["writer"] == "ofx"
    assert payload["errors"] == []
    assert payload["warnings"] == []
    assert payload["run_id"]


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
