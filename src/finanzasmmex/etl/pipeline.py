from typing import Iterable

from ..models import CanonicalTx
from .categorize import CategoryRule, categorize_tx
from .fitid import ensure_fitid
from .transfers import link_internal_transfers


def prepare_for_staging(
    tx: CanonicalTx,
    rules: Iterable[CategoryRule] = (),
) -> CanonicalTx:
    return ensure_fitid(categorize_tx(tx, rules))


def prepare_batch_for_staging(
    txs: Iterable[CanonicalTx],
    rules: Iterable[CategoryRule] = (),
) -> list[CanonicalTx]:
    rules_list = list(rules)
    categorized = [categorize_tx(tx, rules_list) for tx in txs]
    linked = link_internal_transfers(categorized)
    return [ensure_fitid(tx) for tx in linked]
