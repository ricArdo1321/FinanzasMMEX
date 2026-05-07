import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from types import TracebackType
from typing import Any, Iterable, Iterator, Literal, Mapping

import httpx

from ..etl.normalize import normalize_merchant
from ..models import CanonicalTx

PARSER_NAME = "mp_api_v1"
PARSER_VERSION = "1.0"

DEFAULT_BASE_URL = "https://api.mercadopago.com"
DEFAULT_TIMEOUT = 15.0


class MercadoPagoCredentialsError(RuntimeError):
    pass


class MercadoPagoTemporaryError(RuntimeError):
    pass


class MercadoPagoParseError(ValueError):
    pass


def parse_payment(
    payload: Mapping[str, Any],
    *,
    source_file: str | None = None,
    owner: Literal["ricardo", "laura", "joint"] = "ricardo",
) -> CanonicalTx:
    if payload.get("status") != "approved":
        raise MercadoPagoParseError(
            f"Unsupported payment status: {payload.get('status')!r}"
        )

    currency = str(payload.get("currency_id") or "")
    if currency != "CLP":
        raise MercadoPagoParseError(f"Unsupported currency: {currency!r}")

    raw_amount = payload.get("transaction_amount")
    if raw_amount is None:
        raise MercadoPagoParseError("Missing MP field: transaction_amount")
    amount = _coerce_amount(raw_amount)

    raw_date = str(payload.get("date_approved") or "")
    if not raw_date:
        raise MercadoPagoParseError("Missing MP field: date_approved")

    try:
        event_dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MercadoPagoParseError(
            f"Invalid MP date_approved: {raw_date!r}"
        ) from exc

    description = (payload.get("description") or "").strip()
    review_reasons: list[str] = []
    if not description:
        description = "MERCADO PAGO"
        review_reasons.append("merchant_missing")

    raw_text = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    content_sha256 = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    event_date = event_dt.date()
    source_ref = _stringify(payload.get("external_reference") or payload.get("id"))

    return CanonicalTx(
        owner=owner,
        source_type="mp_api",
        source_file=source_file,
        source_ref=source_ref,
        raw_text=raw_text,
        content_sha256=content_sha256,
        event_date=event_date,
        posted_date=event_date,
        amount=amount,
        currency="CLP",
        direction="credit",
        account_alias=f"MP_{_owner_label(owner)}",
        merchant_raw=description,
        merchant_norm=normalize_merchant(description),
        tx_type="transfer_in",
        parser_name=PARSER_NAME,
        parser_version=PARSER_VERSION,
        needs_review=bool(review_reasons),
        review_reason=";".join(review_reasons) if review_reasons else None,
    )


@dataclass
class MercadoPagoClient:
    access_token: str
    base_url: str = DEFAULT_BASE_URL
    timeout: float = DEFAULT_TIMEOUT
    http: httpx.Client | None = field(default=None, repr=False)
    _owns_http: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.http is None:
            self.http = httpx.Client(base_url=self.base_url, timeout=self.timeout)
            self._owns_http = True

    def __repr__(self) -> str:
        masked = "***" if self.access_token else "<unset>"
        return f"MercadoPagoClient(access_token={masked}, base_url={self.base_url!r})"

    def __str__(self) -> str:
        return self.__repr__()

    def __enter__(self) -> "MercadoPagoClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_http and self.http is not None:
            self.http.close()
            self._owns_http = False

    def search_payments(
        self,
        *,
        begin_date: str,
        end_date: str,
        status: str = "approved",
        page_size: int = 50,
    ) -> Iterator[dict[str, Any]]:
        offset = 0
        while True:
            payload = self._search(
                begin_date=begin_date,
                end_date=end_date,
                status=status,
                limit=page_size,
                offset=offset,
            )
            results = payload.get("results", [])
            if not results:
                return
            for entry in results:
                yield entry
            if len(results) < page_size:
                return
            offset += page_size

    def _search(
        self,
        *,
        begin_date: str,
        end_date: str,
        status: str,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        assert self.http is not None
        params: dict[str, str | int] = {
            "status": status,
            "begin_date": begin_date,
            "end_date": end_date,
            "limit": limit,
            "offset": offset,
        }
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }
        try:
            response = self.http.get(
                "/v1/payments/search",
                params=params,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise MercadoPagoTemporaryError(
                f"mp_request_failed:{type(exc).__name__}"
            ) from exc

        if response.status_code in (401, 403):
            raise MercadoPagoCredentialsError(
                f"mp_credentials_invalid:http_{response.status_code}"
            )
        if response.status_code >= 500:
            raise MercadoPagoTemporaryError(
                f"mp_server_error:http_{response.status_code}"
            )
        if response.status_code >= 400:
            raise MercadoPagoTemporaryError(
                f"mp_client_error:http_{response.status_code}"
            )

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise MercadoPagoTemporaryError("mp_invalid_envelope") from exc

        if not isinstance(data, dict):
            raise MercadoPagoTemporaryError("mp_invalid_envelope_type")
        return data


def parse_payments(
    payloads: Iterable[Mapping[str, Any]],
    *,
    source_file: str | None = None,
    owner: Literal["ricardo", "laura", "joint"] = "ricardo",
) -> list[CanonicalTx]:
    return [parse_payment(p, source_file=source_file, owner=owner) for p in payloads]


def _coerce_amount(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise MercadoPagoParseError(
            f"Invalid MP transaction_amount: {value!r}"
        ) from exc
    amount = amount.quantize(Decimal("0.00"))
    if amount <= 0:
        raise MercadoPagoParseError("MP transaction_amount must be > 0")
    return amount


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _owner_label(owner: Literal["ricardo", "laura", "joint"]) -> str:
    return {"ricardo": "Ricardo", "laura": "Laura", "joint": "Joint"}[owner]
