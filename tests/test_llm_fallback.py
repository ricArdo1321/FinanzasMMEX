import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from finanzasmmex.etl.llm_fallback import (
    classify_with_ollama,
    sanitize_for_log,
)
from finanzasmmex.models import CanonicalTx


def _tx(merchant: str = "Comercio Demo Ambiguo") -> CanonicalTx:
    return CanonicalTx(
        owner="ricardo",
        source_type="email",
        content_sha256="abc",
        event_date=date(2026, 5, 2),
        amount=Decimal("12340.00"),
        direction="debit",
        account_alias="BE_Ricardo_1234",
        merchant_raw=merchant,
        merchant_norm=merchant.upper(),
        tx_type="purchase",
        parser_name="be_email_v1",
    )


def _mock_client(handler) -> httpx.Client:
    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport, base_url="http://localhost:11434")


def test_valid_response_enriches_category() -> None:
    payload = {
        "category": "Comida",
        "subcategory": "Cafeterias",
        "tags": ["personal", "delivery"],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/generate"
        body = json.loads(request.content)
        assert body["model"] == "qwen3:8b"
        assert body["format"] == "json"
        assert body["stream"] is False
        return httpx.Response(
            200,
            json={"response": json.dumps(payload), "done": True},
        )

    with _mock_client(handler) as client:
        out = classify_with_ollama(_tx(), client=client)

    assert out.category_guess == "Comida"
    assert out.subcategory_guess == "Cafeterias"
    assert "personal" in out.tags
    assert "delivery" in out.tags
    assert out.needs_review is False


def test_invalid_json_marks_needs_review() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"response": "this is not json", "done": True},
        )

    with _mock_client(handler) as client:
        out = classify_with_ollama(_tx(), client=client)

    assert out.needs_review is True
    assert "ollama" in str(out.review_reason).lower()
    assert out.category_guess is None


def test_http_error_marks_needs_review() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server boom")

    with _mock_client(handler) as client:
        out = classify_with_ollama(_tx(), client=client)

    assert out.needs_review is True
    assert "ollama" in str(out.review_reason).lower()


def test_connection_refused_marks_needs_review() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=request)

    with _mock_client(handler) as client:
        out = classify_with_ollama(_tx(), client=client)

    assert out.needs_review is True
    assert "ollama" in str(out.review_reason).lower()


def test_response_missing_category_marks_needs_review() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"response": json.dumps({"tags": ["x"]}), "done": True},
        )

    with _mock_client(handler) as client:
        out = classify_with_ollama(_tx(), client=client)

    assert out.needs_review is True


def test_existing_needs_review_is_preserved_on_failure() -> None:
    tx = _tx().__class__(
        **{**_tx().__dict__, "needs_review": True, "review_reason": "currency_implicit"}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with _mock_client(handler) as client:
        out = classify_with_ollama(tx, client=client)

    assert out.needs_review is True
    assert "currency_implicit" in str(out.review_reason)
    assert "ollama" in str(out.review_reason).lower()


def test_sanitize_for_log_masks_rut() -> None:
    payload = {"merchant": "Pago a 12.345.678-9 por servicios"}
    out = sanitize_for_log(payload)
    assert "12.345.678-9" not in json.dumps(out)
    assert "[RUT]" in json.dumps(out)


def test_sanitize_for_log_masks_rut_without_dots() -> None:
    payload = {"merchant": "Pago a 12345678-9 y a 1234567-K"}
    serialized = json.dumps(sanitize_for_log(payload))
    assert "12345678-9" not in serialized
    assert "1234567-K" not in serialized
    assert "[RUT]" in serialized


def test_sanitize_for_log_masks_long_digit_runs() -> None:
    payload = {"text": "Cuenta 0001234567890123 origen"}
    out = sanitize_for_log(payload)
    assert "0001234567890123" not in json.dumps(out)


def test_sanitize_for_log_masks_emails() -> None:
    payload = {"contact": "Aviso a usuario@dominio.cl ahora"}
    out = sanitize_for_log(payload)
    assert "usuario@dominio.cl" not in json.dumps(out)
    assert "[EMAIL]" in json.dumps(out)


def test_sanitize_for_log_handles_nested_structures() -> None:
    payload = {
        "outer": {"inner": ["string with 12.345.678-9 inside", {"k": "x@y.cl"}]}
    }
    serialized = json.dumps(sanitize_for_log(payload))
    assert "12.345.678-9" not in serialized
    assert "x@y.cl" not in serialized


def test_prompt_does_not_include_raw_text(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "response": json.dumps({"category": "X", "tags": []}),
                "done": True,
            },
        )

    tx = _tx()
    secret_raw = "RUT 12.345.678-9 user@x.cl 0001234567890123"
    tx_with_secret = tx.__class__(**{**tx.__dict__, "raw_text": secret_raw})

    with _mock_client(handler) as client:
        classify_with_ollama(tx_with_secret, client=client)

    body_text = json.dumps(captured["body"])
    assert "12.345.678-9" not in body_text
    assert "user@x.cl" not in body_text
    assert "0001234567890123" not in body_text
