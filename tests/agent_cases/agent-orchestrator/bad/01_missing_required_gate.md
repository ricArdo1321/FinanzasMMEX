# BAD: Required pre-PR secrets gate is omitted.

User request:
Prepara esto para PR.

Changed files:
- src/finanzasmmex/adapters/cmr_email.py
- src/finanzasmmex/cli.py

# VIOLATION: A correct coordinator must include secrets-pii-auditor for pre-PR.
Bad delegation plan:
- parser-reviewer
- cli-contract-checker

Expected finding:
- severity: blocker
- rule: missing-required-gate
- message mentions secrets-pii-auditor is required for pre-PR/pre-merge.
