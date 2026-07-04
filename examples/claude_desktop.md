# Add AgentRisk to Claude Desktop (2 minutes)

AgentRisk ships an MCP server exposing its three tools. Once connected, Claude can
analyze a portfolio, check a proposed trade, and manage a risk policy, all through
structured tool calls, with no natural-language parsing inside AgentRisk.

## 1. Install

```bash
pip install "agentrisk[mcp]"
```

## 2. Register the server

Edit your Claude Desktop config file:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

Add an `agentrisk` entry under `mcpServers`:

```json
{
  "mcpServers": {
    "agentrisk": {
      "command": "agentrisk-mcp"
    }
  }
}
```

If you prefer `uv` to manage the server without a pip install, use this instead:

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

Restart Claude Desktop. You should see three tools available: `analyze_portfolio_risk`,
`check_trade_risk`, and `generate_risk_policy`.

## 3. Try it

Paste a portfolio and ask questions like:

> "Here's my portfolio: [paste JSON]. Set up a policy: no single stock over 25%,
> warn me on options, block leverage and crypto."

> "Am I overexposed to AI stocks?"

> "I'm thinking of buying 20 more NVDA at $120. Check it against my policy first."

Claude will translate these into structured tool calls. Remember: AgentRisk only
*advises*. Whether an order is actually placed is up to you and whatever execution
setup you use. AgentRisk never trades.

## Notes

- Claude Code users can get this server plus the pre-trade Agent Skill in one step
  with the AgentRisk plugin: `/plugin marketplace add trycoin-ai/agentrisk`, then
  `/plugin install agentrisk@agentrisk`. See the README's "Agent Skill" section.
- The policy is stored at `./.agentrisk/policy.yaml` in the working directory by
  default. Set the `AGENTRISK_HOME` environment variable to change the location.
- AgentRisk makes no network calls and has no telemetry.
