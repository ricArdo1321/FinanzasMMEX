import re
from dataclasses import dataclass, field, replace
from typing import Iterable, Literal

from rapidfuzz import fuzz

from ..models import CanonicalTx
from .normalize import normalize_merchant

PatternType = Literal["substr", "regex", "fuzzy"]
_TYPE_ORDER: dict[PatternType, int] = {"substr": 0, "regex": 1, "fuzzy": 2}


@dataclass(frozen=True)
class CategoryRule:
    rule_id: int
    pattern: str
    pattern_type: PatternType
    merchant_norm: str
    category_name: str
    subcategory_name: str | None = None
    tags: list[str] = field(default_factory=list)
    fuzzy_threshold: int = 85
    priority: int = 100
    active: bool = True


def categorize_tx(tx: CanonicalTx, rules: Iterable[CategoryRule]) -> CanonicalTx:
    target = tx.merchant_norm or normalize_merchant(tx.merchant_raw)
    candidates = [
        rule
        for rule in rules
        if rule.active and _matches(rule, target)
    ]
    if not candidates:
        return tx

    winner = min(
        candidates,
        key=lambda rule: (_TYPE_ORDER[rule.pattern_type], rule.priority, rule.rule_id),
    )

    merged_tags = list(dict.fromkeys([*tx.tags, *winner.tags]))
    return replace(
        tx,
        merchant_norm=winner.merchant_norm,
        category_guess=winner.category_name,
        subcategory_guess=winner.subcategory_name,
        tags=merged_tags,
    )


def _matches(rule: CategoryRule, merchant: str) -> bool:
    pattern = rule.pattern
    if rule.pattern_type == "substr":
        return pattern.upper() in merchant.upper()
    if rule.pattern_type == "regex":
        try:
            return re.search(pattern, merchant, flags=re.IGNORECASE) is not None
        except re.error:
            return False
    if rule.pattern_type == "fuzzy":
        score = fuzz.partial_ratio(pattern.upper(), merchant.upper())
        return score >= rule.fuzzy_threshold
    return False
