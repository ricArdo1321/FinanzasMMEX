# Multiuser Contract

Phase 5 keeps ownership explicit in every transaction. The contract is small on
purpose: one owner field for data ownership, optional tags for business
grouping, and account aliases that do not expose full RUTs or account numbers.

## Owners

Valid owners:

- `ricardo`
- `laura`
- `joint`

`owner` is mandatory in canonical transactions, quick-add and any future source
that can create transactions. A parser must send ambiguous ownership to
`needs_review` instead of guessing.

## Ownership Tags

Reserved ownership tags:

- `Personal-R` for `owner=ricardo`
- `Personal-L` for `owner=laura`
- `Conjunto` for `owner=joint`

Other tags are allowed for categories or workflow. When a reserved ownership tag
is present, it must match the transaction owner and there can be only one
reserved ownership tag in the same transaction.

Accepted aliases normalize to the reserved tags:

- `joint` and `conjunto` -> `Conjunto`
- `personal-r`, `personal_r`, `personal-ricardo` -> `Personal-R`
- `personal-l`, `personal_l`, `personal-laura` -> `Personal-L`

## Account Aliases

Account aliases must identify the product without storing full sensitive
identifiers. Use owner and a short product hint, for example:

- `BE_Ricardo_1234`
- `BE_Laura_5678`
- `CMR_Laura_1234`
- `Joint_BE_1234`

Full RUTs, full PANs and full account numbers stay out of aliases, fixtures and
logs.

## CLI Surface

- `quickadd create --owner ... --tags ...` normalizes ownership tags and rejects
  conflicts.
- `review update --owner ... --tags ...` validates the final owner/tag contract.
- `review bulk-update` applies the same validation per row.
- `review list --tag <tag>` filters by exact normalized tag.
