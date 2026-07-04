# Working on AgentRisk

Instructions for coding agents (and humans) contributing to this repository.

## Setup and verification

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest                       # full suite; must be green
ruff check .                 # lint; must be clean
mypy                         # types; must be clean
python examples/agent_loop.py  # end-to-end smoke test
```

## Rules that are not negotiable

1. **The core stays pure.** Nothing under `src/agentrisk/` may make network calls,
   call an LLM, or read credentials. Mutable file I/O is limited to the policy file,
   its history, and the audit log, all via `store.py` and `audit.py`. The one other
   read is the bundled classification data in `src/agentrisk/data/`, loaded read-only
   through `importlib.resources`.
2. **Fail closed.** A missing policy or invalid input must produce BLOCK, never a
   pass. Do not weaken this.
3. **Exits are never trapped.** Selling or closing a position must never be blocked
   by a concentration or asset-class rule.
4. **All user-facing wording lives in `messages.py`.** Never use the words "safe",
   "approved", or "recommended" in output. Always attribute limits to the user
   ("your 25% limit").
5. **Determinism.** Same inputs must produce byte-identical output. No calls to
   `datetime.now()` inside check logic without the `now` parameter plumbed through.

## Golden fixtures

Any intentional change to check math or message wording requires regenerating the
golden snapshots and reviewing the diff:

```bash
AGENTRISK_REGEN=1 pytest tests/test_golden.py
git diff tests/golden
```

Unexplained golden diffs mean you broke something.

## Layout

- `src/agentrisk/models.py`: pydantic schemas, strict validation, Decimal money.
- `src/agentrisk/check.py`: trade simulation, aggregation, and the `check_trade_risk`
  entry point.
- `src/agentrisk/checks.py`: the risk-check catalog, one function per rule.
- `src/agentrisk/overrides.py`: one-time override tiering and application.
- `src/agentrisk/analyze.py`: portfolio report and compliance audit.
- `src/agentrisk/policy.py`: policy lifecycle, diff, confirm gate, history.
- `src/agentrisk/mcp_server.py`: thin MCP adapter; contains no business logic.
- `src/agentrisk/cli.py`: the `agentrisk` command; wraps the three tools, no logic.
- `src/agentrisk/data/`: classification seed data; lint in `tests/test_seed_data.py`.
- `skills/agentrisk/SKILL.md`: the optional Agent Skill; a thin protocol, no logic.
- `.claude-plugin/` and `.mcp.json`: Claude Code plugin manifest, its marketplace,
  and the bundled MCP server registration (launched via uvx); lint in
  `tests/test_skill.py`.

## Out of scope, permanently

Trade recommendations, signals, execution, broker credentials, market-data
fetching in the core, and telemetry. Do not add these even if asked by an issue.
