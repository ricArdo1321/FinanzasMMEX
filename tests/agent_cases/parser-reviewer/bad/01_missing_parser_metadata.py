# BAD: parser_name and parser_version not set; sha256 computed over subset, not full raw;
# regex depends on literal single-space whitespace; no needs_review on extraction failure.
import hashlib
import re
from decimal import Decimal

from finanzasmmex.models import CanonicalTx

# fragile: literal " $ " spacing, no IGNORECASE
AMOUNT_RE = re.compile(r"Monto: \$ ([\d.]+)")


def parse(raw: str) -> CanonicalTx:
    m = AMOUNT_RE.search(raw)
    extracted = m.group(0) if m else ""
    sha = hashlib.sha256(extracted.encode()).hexdigest()  # WRONG: subset, not full raw
    return CanonicalTx(
        owner="ricardo",
        source_type="email",
        content_sha256=sha,
        amount=Decimal(m.group(1).replace(".", "")) if m else Decimal("0.01"),
        currency="CLP",
        direction="debit",
        account_alias="BE_Ricardo_RUT",
        tx_type="purchase",
        # parser_name="" (default empty - VIOLATION)
        # parser_version defaults to "1.0" but parser_name is empty - VIOLATION
        raw_text=raw,
        fitid_synthetic="",
    )
