# AgentRisk

[![CI](https://github.com/trycoin-ai/agentrisk/actions/workflows/ci.yml/badge.svg)](https://github.com/trycoin-ai/agentrisk/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/agentrisk.svg)](https://pypi.org/project/agentrisk/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Risk guardrails for AI trading agents. Your agent proposes; your policy decides.

![AgentRisk in the terminal: create a risk policy, analyze portfolio exposure, and block an over-limit trade](docs/demo.gif)

AgentRisk sits in front of trade execution: it analyzes portfolio risk, checks each
proposed trade against a policy you write, and manages that policy. The core is
deterministic (same inputs, same verdict), transparent (policies are plain YAML you
can read and edit), and fail-closed (invalid input or a missing policy blocks, never
a silent pass).

> AgentRisk never recommends trades and never executes them. A `PASS` means a trade
> did not break the rules *you* wrote, not that it is safe or profitable. See
> [DISCLAIMER.md](DISCLAIMER.md).

## Quickstart

The fastest path for a Claude agent is the Claude Code plugin. It installs the Agent
Skill and registers the [MCP](https://modelcontextprotocol.io) server in one step
(via `uvx`, so there is nothing else to install):

```text
/plugin marketplace add trycoin-ai/agentrisk
/plugin install agentrisk@agentrisk
```

For any other MCP client, register the server yourself:

```json
{
  "mcpServers": {
    "agentrisk": {
      "command": "uvx",
      "args": ["--from", "agentrisk[mcp]", "agentrisk-mcp"]
    }
  }
}
```

Then ask questions in plain English and the agent translates them into three tool
calls:

| Tool | Question it answers | Returns |
| --- | --- | --- |
| `analyze_portfolio_risk` | What risk am I holding? | Concentration, exposure, and policy-compliance report |
| `check_trade_risk` | Should this trade go through? | `PASS` / `WARN` / `BLOCK` with a one-line reason |
| `generate_risk_policy` | What are my rules? | A human-readable YAML policy (create, update, show) |

The plugin path needs [uv](https://docs.astral.sh/uv/) for `uvx`. See
[examples/claude_desktop.md](examples/claude_desktop.md) for a two-minute Claude
Desktop setup.

## Agent Skill

For Claude agents, AgentRisk ships an optional Agent Skill that encodes the
discipline the guardrail depends on: before any order reaches a broker, classify the
trade, call `check_trade_risk`, respect the verdict, and record the result, in that
order. The plugin above installs it with the server. To install just the skill:

- **Claude Code or Claude Desktop:** copy `skills/agentrisk/` into `~/.claude/skills/`.
- **claude.ai:** upload `skills/agentrisk/SKILL.md` as a skill.

## The enforcement contract

AgentRisk returns advice. It cannot physically stop an order, so your integration
must gate execution on the verdict:

```python
result = check_trade_risk(portfolio, trade)
if not result.proceed:
    refuse(result.summary)              # BLOCK: never call the broker
elif result.acknowledgements_required:
    confirm_with_user(result)           # WARN: surface warnings first
else:
    execute(trade)                      # PASS
```

If you call the broker regardless of the verdict, you have a logger, not a guardrail.
See the [integration guide](docs/integration-guide.md).

## Using the library directly

The three tools are also a pure Python library, with no network calls and no LLM in
the core:

```bash
pip install agentrisk
```

Every parameter, return field, and error case is in the
[tool reference](docs/tool-reference.md).

## What it checks

- **Concentration caps** on single names, sectors, themes, and asset classes,
  evaluated on the simulated post-trade portfolio.
- **Asset-class rules** (allow, warn, or block) for crypto, options, and margin.
- **Order sanity**: max order size, minimum cash floor, insufficient-funds detection.
- **Restricted symbols** and **data quality** (stale snapshots warn, invalid ones
  block).

The [policy reference](docs/policy-reference.md) covers every field and the safety
behaviors: fail closed, exits are never trapped, only breach-worsening trades block,
and the one-time bypass.

## Documentation

| Doc | Contents |
| --- | --- |
| [Concepts](docs/concepts.md) | The mental model and the agent/AgentRisk division of labor |
| [Architecture](docs/architecture.md) | The module layout and how a call flows through the core |
| [Policy reference](docs/policy-reference.md) | Every policy field and the check behavior it drives |
| [Tool reference](docs/tool-reference.md) | Parameters, outputs, and error cases for all three tools |
| [CLI reference](docs/cli.md) | The `agentrisk` command: `policy`, `check`, `analyze` |
| [Integration guide](docs/integration-guide.md) | The enforcement contract, broker MCP pairing, audit log |
| [Threat model](docs/threat-model.md) | What AgentRisk can and cannot protect against |
| [Classification data](docs/classification-data.md) | The open taxonomy and how to contribute corrections |

## Roadmap

Next is deterministic stress scenarios, ETF look-through, and behavioral limits
(v0.2), then options analytics, broker snapshot adapters, short positions, and
multi-currency (v0.3). Trade recommendations, signals, execution, and telemetry are
permanently out of scope. See the [milestones](https://github.com/trycoin-ai/agentrisk/milestones).

## Contributing

Classification-data corrections and new deterministic checks are especially welcome.
See [CONTRIBUTING.md](.github/CONTRIBUTING.md), and keep the core pure: no network,
no LLM calls, no hidden state.

## License

MIT. See [LICENSE](LICENSE).
