# Security Policy

## Supported versions

Only the latest released version of AgentRisk receives security updates.

## What counts as a security issue here

AgentRisk is a local, offline library and MCP server. It makes no network calls,
stores no credentials, and never talks to a broker. Even so, some issues would be
security-relevant:

- A way to make `check_trade_risk` return `proceed: true` for a trade that a
  correct evaluation of the policy would BLOCK (a bypass of the guardrail).
- A way to modify the policy file through the tools without the confirm flow, or
  without the change appearing in the diff and audit log.
- Path traversal or file overwrite outside the `.agentrisk/` directory via
  `policy_path` or `AGENTRISK_HOME`.
- Malicious input (portfolio, trade, or policy YAML) that causes code execution.

Verdict correctness bugs that are not bypasses (for example a wrong percentage in
a message) are ordinary bugs; please file a regular issue for those.

## Reporting a vulnerability

Please do not open a public issue for security reports. Use GitHub's private
vulnerability reporting ("Report a vulnerability" under the Security tab of the
repository). Include a minimal reproduction if you can.

You can expect an acknowledgement within a few days. Fixes are released as soon
as practical, with credit to the reporter unless you prefer otherwise.
