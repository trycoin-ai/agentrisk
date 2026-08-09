"""MCP server exposing the three tools over stdio.

No business logic lives here; the tool docstrings teach a calling agent how to
translate natural language into structured arguments. Run with ``agentrisk-mcp``.
"""

from __future__ import annotations

from typing import Any

from .analyze import analyze_portfolio_risk as _analyze
from .check import check_trade_risk as _check
from .policy import generate_risk_policy as _policy

_INSTRUCTIONS = (
    "AgentRisk provides pre-execution risk checks for trading agents. It NEVER "
    "recommends or executes trades. Call check_trade_risk BEFORE executing any "
    "trade and gate execution on the returned 'proceed' boolean: if proceed is "
    "false, do not trade and relay 'summary'; if there are "
    "'acknowledgements_required', surface them to the user before trading. A PASS "
    "means the trade did not violate the user's own policy, not that it is safe."
)


MCP_MISSING = (
    "The MCP server needs the 'mcp' package. Install agentrisk with its "
    "[mcp] extra (see the README's Installation section)."
)


def _installed_mcp_version() -> str:
    """Best-effort version of the installed mcp package, for the error message."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("mcp")
    except PackageNotFoundError:
        return "unknown"


def _incompatible_mcp_message() -> str:
    """Explain that mcp is installed but too new, which is not a missing extra."""
    return (
        f"The installed 'mcp' package (version {_installed_mcp_version()}) does not "
        "provide mcp.server.fastmcp, which this release of AgentRisk is built on. "
        "AgentRisk supports mcp>=1.2.0,<2. Reinstall a supported version with: "
        'pip install --upgrade "agentrisk[mcp]"'
    )


def build_server() -> Any:
    """Construct the FastMCP server (imported lazily so the core needs no MCP dep)."""
    try:
        import mcp as _mcp_pkg  # noqa: F401
    except ImportError as exc:
        raise SystemExit(MCP_MISSING) from exc

    # The package is present, so a failure here means a version whose layout we do
    # not support. Saying "install the extra" would send the user in circles.
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise SystemExit(_incompatible_mcp_message()) from exc

    mcp = FastMCP("agentrisk", instructions=_INSTRUCTIONS)

    @mcp.tool()
    def analyze_portfolio_risk(
        portfolio: dict,
        focus: dict | None = None,
        analyses: list[str] | None = None,
        policy_path: str | None = None,
    ) -> dict:
        """Analyze a portfolio's risk and return a structured report (read-only).

        Use this to answer questions about *current* holdings: concentration,
        exposure to a sector/theme/asset class, and compliance with the user's
        policy. It does NOT evaluate a proposed trade (use check_trade_risk).

        Translating common questions into arguments:
          * "What's my biggest concentration risk?" -> no focus (read top_risks).
          * "Am I overexposed to AI stocks?"        -> focus={"tag": "ai"}.
          * "How much crypto do I hold?"            -> focus={"asset_class": "crypto"}.
          * "How much is in tech?"                  -> focus={"sector": "technology"}.
          * "How much NVDA do I have?"              -> focus={"symbol": "NVDA"}.

        portfolio: a snapshot object:
          {"as_of": "2026-07-01T15:30:00Z", "base_currency": "USD", "cash": 12500,
           "positions": [{"symbol": "NVDA", "quantity": 40, "price": 172.5,
                          "asset_class": "equity", "sector": "technology",
                          "tags": ["ai"]}]}
          asset_class/sector/tags are optional; AgentRisk fills gaps from bundled
          data and reports anything it cannot classify.

        Returns a report with: totals, positions_by_weight, breakdowns (by sector /
        asset class / tag), concentration (HHI + band), top_risks, an optional
        compliance audit, an optional focus spotlight, data_quality, and the v1
        limitations. Answer the user in your own words from these numbers; do not
        invent figures the report does not contain.
        """
        return _analyze(
            portfolio, focus=focus, analyses=analyses, policy_path=policy_path
        ).model_dump(mode="json")

    @mcp.tool()
    def check_trade_risk(
        portfolio: dict,
        trade: dict,
        policy_path: str | None = None,
        override: list[str] | None = None,
        override_reason: str | None = None,
    ) -> dict:
        """Validate a PROPOSED trade against the portfolio and policy BEFORE executing.

        ALWAYS call this before placing an order, and gate execution on the result:
          * proceed == false  -> do NOT execute; relay 'summary' to the user.
          * acknowledgements_required non-empty -> surface those warnings and get
            the user's OK before executing.
          * proceed == true and no acknowledgements -> you may execute; you may
            append 'summary' to the order confirmation shown to the user.

        trade: a proposal object:
          {"action": "buy", "symbol": "NVDA", "quantity": 15, "order_type": "market",
           "estimated_price": 172.5}
          For limit orders set order_type="limit" and limit_price. For options add an
          "option" block; set "uses_margin": true for margin/leverage orders.

        Returns a verdict: verdict (PASS|WARN|BLOCK|OVERRIDDEN), proceed (bool),
        summary (a one-line message suitable for an order confirmation), checks[]
        (per-rule detail), acknowledgements_required[], overrides[], and the
        evaluation context. AgentRisk fails closed: invalid input or a missing
        policy returns BLOCK.

        ONE-TIME BYPASS (the 'override' argument):
        When a trade is BLOCKED, each blocking entry in checks[] carries in its
        details: 'overridable' (bool), 'override_tier' ('soft'|'hard'|'none'), and
        'override_token' (the exact string to pass). A one-time bypass lets a single
        blocked trade through WITHOUT changing the policy. Rules for using it:
          * NEVER pass 'override' on your own initiative, and never when acting
            autonomously without a human. It requires explicit, in-the-moment human
            approval of that specific trade.
          * SOFT blocks (order size, concentration, min-cash, staleness): you may
            offer the user a one-time bypass directly. If they approve, call again
            with override=[the override_token] and an override_reason.
          * HARD blocks (block crypto/options/margin, never-trade): do NOT jump to a
            bypass. FIRST offer to update the policy with generate_risk_policy (a
            deliberate, logged configuration change). Only if the user explicitly
            declines the policy edit and insists on a one-time exception should you
            pass override for the hard token, always with an override_reason.
          * NONE tier (insufficient cash/holdings, invalid snapshot, no policy):
            cannot be bypassed. Do not attempt; fix the underlying problem instead.
        A successful bypass returns verdict OVERRIDDEN with proceed=true, lists what
        was bypassed in overrides[], and is recorded as a distinct audit event. Tell
        the user plainly that a guardrail was bypassed for this one trade.
        """
        return _check(
            portfolio, trade, policy_path=policy_path,
            override=override, override_reason=override_reason,
        ).model_dump(mode="json")

    @mcp.tool()
    def generate_risk_policy(
        mode: str = "create",
        preset: str | None = None,
        fields: dict | None = None,
        changes: dict | None = None,
        confirm: bool = False,
        policy_path: str | None = None,
    ) -> dict:
        """Create, update, or show the user's risk policy.

        You translate the user's words into structured fields; this tool never
        parses free text. It also never silently relaxes a guardrail: updates return
        a diff first and only write when confirm=true.

        mode="create": start a new policy from a preset plus explicit fields.
          preset: "conservative" | "balanced" (default) | "aggressive".
          Example: "no single stock over 25%, warn on options, block leverage":
            fields={"limits": {"max_single_position_pct": 25},
                    "asset_rules": {"options": "warn", "margin": "block"}}
          Returned policy is a PROPOSAL until you call again with confirm=true.

        mode="update": change an existing policy. Provide only what changes.
          Example: "lower max single stock to 20% and block crypto":
            changes={"limits": {"max_single_position_pct": 20},
                     "asset_rules": {"crypto": "block"}}
          The response includes a 'diff' with each change classified as tightening,
          loosening, or neutral. If any change is LOOSENING, show it to the user and
          get explicit approval before calling again with confirm=true.

        mode="show": return the current policy and a plain-English rule summary.

        Policy field reference (all percentages 0-100):
          limits.max_single_position_pct, limits.max_sector_pct{sector:pct},
          limits.max_tag_pct{tag:pct}, limits.max_asset_class_pct{class:pct},
          limits.warn_at_utilization; asset_rules.{crypto|options|margin} = allow|warn|block;
          order_rules.{max_order_pct_of_portfolio|max_order_value|min_cash_pct};
          restricted.{never_trade[],warn_list[]}; data_rules.max_snapshot_age_hours.

        Returns: mode, written, requires_confirmation, message, the policy object,
        its YAML, a plain-English summary[], and (for updates) the diff[].
        """
        return _policy(
            mode,
            preset=preset,
            fields=fields,
            changes=changes,
            confirm=confirm,
            policy_path=policy_path,
        ).model_dump(mode="json")

    return mcp


def main() -> None:
    """Console-script entry point: run the stdio MCP server."""
    build_server().run()


if __name__ == "__main__":  # pragma: no cover
    main()
