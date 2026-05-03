import json
import re
from dataclasses import replace
from typing import Any, Iterable

import httpx

from ..models import CanonicalTx

DEFAULT_MODEL = "qwen3:8b"
DEFAULT_ENDPOINT = "http://localhost:11434"
DEFAULT_TIMEOUT = 15.0

_RUT_RE = re.compile(
    r"\b(?:\d{1,2}\.\d{3}\.\d{3}|\d{7,8})-[\dkK]\b"
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_LONG_DIGITS_RE = re.compile(r"\b\d{8,}\b")

_PROMPT_TEMPLATE = (
    "Clasifica esta transaccion bancaria chilena. Responde SOLO JSON con "
    "claves: category (str), subcategory (str|null), tags (lista de str). "
    "Sin texto extra.\n\n"
    "Transaccion:\n"
    "- merchant: {merchant}\n"
    "- direction: {direction}\n"
    "- tx_type: {tx_type}\n"
    "- currency: {currency}\n"
    "- amount: {amount}\n"
)


def classify_with_ollama(
    tx: CanonicalTx,
    *,
    client: httpx.Client | None = None,
    model: str = DEFAULT_MODEL,
    endpoint: str = DEFAULT_ENDPOINT,
    timeout: float = DEFAULT_TIMEOUT,
) -> CanonicalTx:
    own_client = client is None
    http = client or httpx.Client(base_url=endpoint, timeout=timeout)
    try:
        result = _call_ollama(http, tx, model)
    except _FallbackError as exc:
        return _mark_review(tx, str(exc))
    finally:
        if own_client:
            http.close()

    return replace(
        tx,
        category_guess=result["category"],
        subcategory_guess=result.get("subcategory"),
        tags=_merge_tags(tx.tags, result.get("tags", [])),
    )


def sanitize_for_log(value: Any) -> Any:
    if isinstance(value, str):
        return _scrub_text(value)
    if isinstance(value, dict):
        return {k: sanitize_for_log(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_for_log(v) for v in value]
    if isinstance(value, tuple):
        return tuple(sanitize_for_log(v) for v in value)
    return value


class _FallbackError(RuntimeError):
    pass


def _call_ollama(
    http: httpx.Client,
    tx: CanonicalTx,
    model: str,
) -> dict[str, Any]:
    prompt = _build_prompt(tx)
    body = {"model": model, "prompt": prompt, "format": "json", "stream": False}
    try:
        response = http.post("/api/generate", json=body)
    except httpx.HTTPError as exc:
        raise _FallbackError(f"ollama_fallback_failed:{type(exc).__name__}") from exc

    if response.status_code >= 400:
        raise _FallbackError(f"ollama_fallback_failed:http_{response.status_code}")

    try:
        envelope = response.json()
    except json.JSONDecodeError as exc:
        raise _FallbackError("ollama_fallback_failed:envelope_not_json") from exc

    raw = envelope.get("response", "")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _FallbackError("ollama_fallback_failed:invalid_json") from exc

    if not isinstance(parsed, dict) or not parsed.get("category"):
        raise _FallbackError("ollama_fallback_failed:missing_category")

    return parsed


def _build_prompt(tx: CanonicalTx) -> str:
    merchant = _scrub_text(tx.merchant_norm or tx.merchant_raw or "")
    return _PROMPT_TEMPLATE.format(
        merchant=merchant,
        direction=tx.direction,
        tx_type=tx.tx_type,
        currency=tx.currency,
        amount=str(tx.amount),
    )


def _merge_tags(existing: Iterable[str], extra: Iterable[Any]) -> list[str]:
    out: list[str] = list(existing)
    for tag in extra:
        if isinstance(tag, str) and tag and tag not in out:
            out.append(tag)
    return out


def _mark_review(tx: CanonicalTx, reason: str) -> CanonicalTx:
    combined = ";".join(filter(None, [tx.review_reason, reason]))
    return replace(tx, needs_review=True, review_reason=combined or reason)


def _scrub_text(value: str) -> str:
    out = _RUT_RE.sub("[RUT]", value)
    out = _EMAIL_RE.sub("[EMAIL]", out)
    out = _LONG_DIGITS_RE.sub("[DIGITS]", out)
    return out
