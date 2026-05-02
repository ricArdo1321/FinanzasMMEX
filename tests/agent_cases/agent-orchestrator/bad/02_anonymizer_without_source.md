# BAD: fixtures-anonymizer is invoked without an explicit source path.

User request:
Busca algun correo real y conviertelo en fixture.

# VIOLATION: fixtures-anonymizer may only run when the user supplies a source file path.
Bad delegation plan:
- fixtures-anonymizer with instruction to search the repo for real source artifacts.

Expected finding:
- severity: blocker
- rule: anonymizer-source-required
- message says the source path must be explicit and output must stay under tests/fixtures/**.
