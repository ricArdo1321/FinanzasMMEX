from ..models import CanonicalTx
from .fitid import ensure_fitid


def prepare_for_staging(tx: CanonicalTx) -> CanonicalTx:
    return ensure_fitid(tx)
