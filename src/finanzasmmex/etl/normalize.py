import re
import unicodedata
from decimal import Decimal, InvalidOperation


def parse_clp_amount(value: str | int | Decimal) -> Decimal:
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int):
        amount = Decimal(value)
    else:
        digits = re.sub(r"\D", "", value)
        if not digits:
            raise ValueError(f"Invalid CLP amount: {value!r}")
        try:
            amount = Decimal(digits)
        except InvalidOperation as exc:
            raise ValueError(f"Invalid CLP amount: {value!r}") from exc

    amount = abs(amount).quantize(Decimal("0.00"))
    if amount <= 0:
        raise ValueError("CLP amount must be greater than zero")
    return amount


def normalize_merchant(value: str) -> str:
    without_accents = unicodedata.normalize("NFKD", value)
    ascii_value = without_accents.encode("ascii", "ignore").decode("ascii")
    compact = re.sub(r"\s+", " ", ascii_value).strip()
    return compact.upper()
