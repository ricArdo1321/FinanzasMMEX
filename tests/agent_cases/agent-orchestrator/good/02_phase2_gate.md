# GOOD: Phase 2 gate includes writer, schema, and inherited required agents.

User request:
Valida Phase 2 antes de merge.

Relevant context:
- Phase 2 is direct SQL writer to MMEX.
- Shadow-mode evidence exists in docs/shadow-mode/phase2-week-1.md.

Expected delegation:
- parser-reviewer
- cli-contract-checker
- secrets-pii-auditor
- mmex-writer-guard
- staging-schema-validator

Expected coordinator behavior:
- Report phase: 2.
- Mark all five agents as required_gate: true.
- Check that shadow-mode documentation is present.
- Do not invoke wpf-ui-reviewer unless desktop files are also in scope.
