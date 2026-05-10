import pytest

from finanzasmmex.ownership import (
    OWNER_TAG_BY_OWNER,
    normalize_tag,
    normalize_tags,
    validate_owner_tags,
)


def test_normalize_ownership_tags_and_dedupe() -> None:
    assert normalize_tag("joint") == "Conjunto"
    assert normalize_tag("personal_l") == "Personal-L"
    assert normalize_tags([" personal-r ", "Personal-R", "cafes"]) == [
        "Personal-R",
        "cafes",
    ]


def test_owner_tag_contract_matches_expected_owner() -> None:
    for owner, tag in OWNER_TAG_BY_OWNER.items():
        validate_owner_tags(owner, [tag, "cafes"])


def test_owner_tag_contract_rejects_conflicting_tag() -> None:
    with pytest.raises(ValueError, match="conflicts with owner ricardo"):
        validate_owner_tags("ricardo", ["Conjunto"])
