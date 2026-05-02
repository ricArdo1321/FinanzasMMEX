# GOOD: Multi-area review routes each touched path to the right specialist.

User request:
Revisa este cambio antes de merge.

Changed files:
- src/finanzasmmex/adapters/be_email.py
- src/finanzasmmex/cli.py
- src/finanzasmmex/staging/schema.sql
- desktop/FinanzasMMEX.App/MainWindow.xaml.cs

Expected delegation:
- parser-reviewer for adapters/be_email.py
- cli-contract-checker for cli.py
- staging-schema-validator for staging/schema.sql
- wpf-ui-reviewer for desktop/FinanzasMMEX.App/MainWindow.xaml.cs
- secrets-pii-auditor because this is a pre-merge review

Expected coordinator behavior:
- Invoke specialists with narrow scopes.
- Do not do specialist findings itself.
- Preserve each specialist output under source_agent.
