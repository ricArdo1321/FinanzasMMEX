import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from finanzasmmex.adapters.mp_api import (
    MercadoPagoClient,
    MercadoPagoCredentialsError,
    MercadoPagoTemporaryError,
    parse_payment,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "mp_api" / "payment_anonymized.json"


def _payment_payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parse_payment_fixture_maps_canonical_fields() -> None:
    raw_text = FIXTURE.read_text(encoding="utf-8")
    payload = json.loads(raw_text)

    tx = parse_payment(payload, source_file=str(FIXTURE), raw_text=raw_text)

    assert tx.owner == "ricardo"
    assert tx.source_type == "mp_api"
    assert tx.source_file == str(FIXTURE)
    assert tx.source_ref == "fixture-demo-001"
    assert tx.content_sha256
    assert tx.event_date == date(2026, 5, 2)
    assert tx.posted_date == date(2026, 5, 2)
    assert tx.amount == Decimal("12500.00")
    assert tx.currency == "CLP"
    assert tx.direction == "credit"
    assert tx.account_alias == "MP_Ricardo"
    assert tx.merchant_raw == "Pago de prueba anonimizado"
    assert tx.merchant_norm == "PAGO DE PRUEBA ANONIMIZADO"
    assert tx.tx_type == "transfer_in"
    assert tx.parser_name == "mp_api_v1"
    assert tx.parser_version == "1.0"
    assert tx.fitid_synthetic is None
    assert tx.needs_review is False


def test_parse_payment_hashes_full_raw_text_when_supplied() -> None:
    raw_text = FIXTURE.read_text(encoding="utf-8")
    payload = json.loads(raw_text)

    tx = parse_payment(payload, source_file=str(FIXTURE), raw_text=raw_text)

    assert tx.raw_text == raw_text
    assert tx.content_sha256 == hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


def test_parse_payment_infers_debit_transfer_from_operation_type() -> None:
    payload = _payment_payload()
    payload["operation_type"] = "money_transfer"

    tx = parse_payment(payload, raw_text=json.dumps(payload, sort_keys=True))

    assert tx.direction == "debit"
    assert tx.tx_type == "transfer_out"
    assert tx.needs_review is False


def test_parse_payment_marks_unknown_operation_for_review() -> None:
    payload = _payment_payload()
    payload["operation_type"] = "unexpected_operation"

    tx = parse_payment(payload)

    assert tx.needs_review is True
    assert "operation_type_unknown" in str(tx.review_reason)


def test_parse_payment_rejects_non_approved() -> None:
    payload = _payment_payload()
    payload["status"] = "rejected"
    with pytest.raises(ValueError, match="status"):
        parse_payment(payload)


def test_parse_payment_rejects_non_clp() -> None:
    payload = _payment_payload()
    payload["currency_id"] = "USD"
    with pytest.raises(ValueError, match="currency"):
        parse_payment(payload)


def test_parse_payment_marks_review_when_description_missing() -> None:
    payload = _payment_payload()
    payload["description"] = ""
    tx = parse_payment(payload)
    assert tx.needs_review is True
    assert "merchant_missing" in str(tx.review_reason)
    assert tx.merchant_raw == "MERCADO PAGO"


def test_parse_payment_owner_overrides_alias() -> None:
    tx = parse_payment(_payment_payload(), owner="laura")
    assert tx.account_alias == "MP_Laura"


def test_parse_payment_handles_float_amount_without_corruption() -> None:
    payload = _payment_payload()
    payload["transaction_amount"] = 1250.50
    tx = parse_payment(payload)
    assert tx.amount == Decimal("1250.50")


def test_parse_payment_handles_iso_z_suffix() -> None:
    payload = _payment_payload()
    payload["date_approved"] = "2026-05-02T14:15:00Z"
    tx = parse_payment(payload)
    assert tx.event_date == date(2026, 5, 2)


@pytest.mark.parametrize("amount", [0, -12500, "-12500.00"])
def test_parse_payment_rejects_zero_or_negative_amount(amount) -> None:
    payload = _payment_payload()
    payload["transaction_amount"] = amount
    with pytest.raises(ValueError, match="must be > 0"):
        parse_payment(payload)


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://api.mercadopago.com",
    )


def test_client_search_payments_returns_results() -> None:
    payment = _payment_payload()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer TEST-TOKEN"
        assert request.url.path == "/v1/payments/search"
        return httpx.Response(200, json={"results": [payment]})

    with _mock_client(handler) as http:
        client = MercadoPagoClient(access_token="TEST-TOKEN", http=http)
        results = list(
            client.search_payments(
                begin_date="2026-05-01T00:00:00Z",
                end_date="2026-05-31T23:59:59Z",
            )
        )

    assert len(results) == 1
    assert results[0]["id"] == payment["id"]


def test_client_401_raises_credentials_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "invalid_token"})

    with _mock_client(handler) as http:
        client = MercadoPagoClient(access_token="REVOKED", http=http)
        with pytest.raises(MercadoPagoCredentialsError):
            list(client.search_payments(begin_date="x", end_date="y"))


def test_client_5xx_raises_temporary_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="service unavailable")

    with _mock_client(handler) as http:
        client = MercadoPagoClient(access_token="X", http=http)
        with pytest.raises(MercadoPagoTemporaryError):
            list(client.search_payments(begin_date="x", end_date="y"))


def test_client_connection_error_raises_temporary_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with _mock_client(handler) as http:
        client = MercadoPagoClient(access_token="X", http=http)
        with pytest.raises(MercadoPagoTemporaryError):
            list(client.search_payments(begin_date="x", end_date="y"))


def test_client_repr_does_not_leak_token() -> None:
    client = MercadoPagoClient(access_token="SECRET-TOKEN-12345")
    try:
        assert "SECRET-TOKEN-12345" not in repr(client)
        assert "SECRET-TOKEN-12345" not in str(client)
    finally:
        client.close()


def test_client_context_manager_closes_owned_http() -> None:
    with MercadoPagoClient(access_token="X") as client:
        assert client.http is not None
        owned = client._owns_http
    assert owned is True
    assert client._owns_http is False


def test_client_does_not_close_externally_owned_http() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"results": []}))
    external = httpx.Client(transport=transport, base_url="https://api.mercadopago.com")
    try:
        with MercadoPagoClient(access_token="X", http=external) as client:
            list(client.search_payments(begin_date="x", end_date="y"))
        assert external.is_closed is False
    finally:
        external.close()
