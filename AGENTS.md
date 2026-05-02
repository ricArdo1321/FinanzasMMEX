# Codex Agent Guide - FinanzasMMEX

This file is the Codex-facing bridge for the specialist agents stored in
`.claude/agents/`. Use it when working in this repository, especially when the
user asks to "usar agentes", coordinate reviews, validate a phase gate, prepare
a merge/PR/commit, or decide which specialist should inspect a change.

## Startup

Before agent-style review or coordinated work, read:

- `CLAUDE.md`
- `PLAN2.md`
- `.claude/agents/README.md`
- The specific `.claude/agents/<agent>.md` prompts for every specialist in scope

Treat `.claude/agents/*.md` as the source of truth for specialist rules,
severity, hard blockers, phase gates, and output formats.

## How Codex Uses The Agents

Codex can use the Claude agent prompts in two modes:

1. **Delegated mode:** if the user explicitly asks for agents, delegation,
   parallel review, or a phase-gate review, spawn Codex subagents when available.
   Give each subagent the relevant `.claude/agents/<agent>.md` prompt, the user
   request, and only the files/diff/output in that specialist's scope.
2. **Local checklist mode:** if subagent tooling is not available or the user did
   not explicitly ask for delegation, apply the relevant specialist checklist
   yourself and state clearly that it was a local Codex pass, not a spawned
   specialist run.

Do not claim that a specialist agent ran unless it actually ran.

## Routing

| Scope / trigger | Use this specialist prompt |
|---|---|
| `src/finanzasmmex/adapters/**`, email/API parser logic, `CanonicalTx` extraction | `parser-reviewer` |
| `src/finanzasmmex/writer/**`, `.mmb`, OFX, SQL writer, backup, MMEX dedup | `mmex-writer-guard` |
| `src/finanzasmmex/staging/schema.sql`, `repo.py`, migrations | `staging-schema-validator` |
| `src/finanzasmmex/cli.py`, CLI commands, exit codes, `contracts/**` | `cli-contract-checker` |
| `desktop/FinanzasMMEX.App/**`, WPF, subprocess invocation, UI JSON parsing | `wpf-ui-reviewer` |
| `src/finanzasmmex/secrets/vault.py`, fixtures, logs, pre-commit/pre-PR, credential handling | `secrets-pii-auditor` |
| Explicit source artifact to anonymize into `tests/fixtures/**` | `fixtures-anonymizer` |
| Multi-area change, phase gate, pre-merge/pre-PR orchestration, or "which agents?" | `agent-orchestrator` |

## Phase Gates

- **Phase 1 merge:** `parser-reviewer`, `cli-contract-checker`,
  `secrets-pii-auditor` must pass without `blocker`.
- **Phase 2 merge:** Phase 1 specialists plus `mmex-writer-guard` and
  `staging-schema-validator`; verify 1 week of shadow-mode against
  `finanza_test.mmb` is documented.
- **Phase 4 merge:** relevant earlier gates plus `wpf-ui-reviewer`.
- Phases 3 and 5 inherit Phase 2 + Phase 4 gates unless `PLAN2.md` changes this.

For commit, PR, release, merge, or "dejalo listo", include
`secrets-pii-auditor` even if the diff does not obviously touch secrets.

## Delegation Rules For Codex

- Keep specialist scopes separate. Do not ask one agent to inspect another
  agent's domain.
- Specialist review agents are read-only. They produce findings and fixes, not
  production-code edits.
- `fixtures-anonymizer` is the only writer-style specialist and may write only
  under `tests/fixtures/**`, using an explicit user-supplied source path.
- Preserve `blocker` findings exactly. Do not downgrade severity.
- Collapse duplicate findings only when file, line, rule, and root cause match.
- If a required gate was not run, report it as missing. If it is required for
  merge/PR/release, treat the gate as blocked.
- If the main Codex agent edits code, run or apply relevant specialist reviews
  after implementation and before finalizing when the touched scope requires it.

## Suggested Codex Report

Use this shape for coordinated runs:

```yaml
agent_mode: delegated | local-checklist
agents:
  - name: <agent>
    status: invoked | applied-locally | skipped | failed
    reason: <why>
findings:
  - severity: blocker|major|minor|nit
    source_agent: <agent>
    location: <file>:<line>
    rule: <rule-id>
    message: <issue>
    fix: <proposal>
gate_status:
  phase: <none|1|2|3|4|5>
  blockers_count: N
  status: clear|blocked
summary: <1-2 lines>
```

For ordinary implementation work, keep the final response concise, but mention
which specialist prompts were used or which required gate remains pending.
