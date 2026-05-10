from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from .ownership import Owner


@dataclass(frozen=True)
class CanonicalTx:
    # Identidad y origen
    tx_uid: str = field(default_factory=lambda: str(uuid4()))
    owner: Owner = "ricardo"
    source_type: Literal[
        "email", "mp_api", "scraping", "ofx", "qif", "csv", "xlsx", "pdf", "manual"
    ] = "email"
    source_file: str | None = None  # path local o gmail message-id
    source_ref: str | None = None  # message-id, run_id de scraping, etc.
    raw_text: str = ""  # texto crudo del email/HTML/PDF
    content_sha256: str = ""  # hash del raw_text completo

    # Temporalidad
    event_date: date | None = None  # fecha de la transacción real
    booking_date: date | None = None  # fecha contable del banco
    posted_date: date | None = None  # fecha en que aparece en el extracto

    # Cuantitativo
    amount: Decimal = Decimal("0.00")  # SIEMPRE positivo
    currency: str = "CLP"
    direction: Literal["debit", "credit"] = "debit"

    # Cuenta / tarjeta
    account_alias: str = ""  # 'BE_Ricardo_RUT', 'CMR_Laura'
    card_last4: str | None = None

    # Comercio
    merchant_raw: str = ""
    merchant_norm: str | None = None  # normalizado por dict + RapidFuzz

    # Tipología contable
    tx_type: Literal[
        "purchase",
        "bill_payment",
        "transfer_in",
        "transfer_out",
        "internal_transfer",
        "refund",
        "cash_withdrawal",
        "fee",
    ] = "purchase"

    # Categorización
    category_guess: str | None = None
    subcategory_guess: str | None = None
    tags: list[str] = field(default_factory=list)

    # Trazabilidad
    parser_name: str = ""  # 'be_email_v3'
    parser_version: str = "1.0"
    needs_review: bool = False  # True si hay ambigüedad
    review_reason: str | None = None

    # FITID sintético (calculado en ETL, no en adapter)
    fitid_synthetic: str | None = None

    # Estado en MMEX
    mmex_account_id: int | None = None
    mmex_tx_id: int | None = None
    mmex_status: Literal["pending", "exported", "inserted", "rejected"] = "pending"

    # Vinculación de transferencias
    transfer_pair_uid: str | None = None
    to_account_alias: str | None = None
