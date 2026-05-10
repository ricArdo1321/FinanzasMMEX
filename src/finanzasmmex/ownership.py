from typing import Iterable, Literal

Owner = Literal["ricardo", "laura", "joint"]

VALID_OWNERS: frozenset[str] = frozenset({"ricardo", "laura", "joint"})

OWNERSHIP_TAGS: frozenset[str] = frozenset(
    {"Conjunto", "Personal-R", "Personal-L"}
)

OWNER_TAG_BY_OWNER: dict[str, str] = {
    "ricardo": "Personal-R",
    "laura": "Personal-L",
    "joint": "Conjunto",
}

_OWNERSHIP_TAG_ALIASES: dict[str, str] = {
    "conjunto": "Conjunto",
    "joint": "Conjunto",
    "personal-r": "Personal-R",
    "personal_r": "Personal-R",
    "personal-ricardo": "Personal-R",
    "personal-r-ricardo": "Personal-R",
    "personal-l": "Personal-L",
    "personal_l": "Personal-L",
    "personal-laura": "Personal-L",
    "personal-l-laura": "Personal-L",
}


def normalize_tag(tag: str) -> str:
    cleaned = tag.strip()
    key = cleaned.casefold().replace("_", "-")
    return _OWNERSHIP_TAG_ALIASES.get(key, cleaned)


def normalize_tags(tags: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_tag in tags:
        tag = normalize_tag(raw_tag)
        if not tag or tag in seen:
            continue
        normalized.append(tag)
        seen.add(tag)
    return normalized


def ownership_tags(tags: Iterable[str]) -> set[str]:
    return {tag for tag in normalize_tags(tags) if tag in OWNERSHIP_TAGS}


def validate_owner_tags(owner: str, tags: Iterable[str]) -> None:
    if owner not in VALID_OWNERS:
        raise ValueError("owner must be one of ricardo|laura|joint")

    found = ownership_tags(tags)
    if len(found) > 1:
        ordered = ", ".join(sorted(found))
        raise ValueError(f"only one ownership tag is allowed: {ordered}")

    expected = OWNER_TAG_BY_OWNER[owner]
    if found and expected not in found:
        ordered = ", ".join(sorted(found))
        raise ValueError(
            f"ownership tag {ordered} conflicts with owner {owner}; "
            f"expected {expected}"
        )
