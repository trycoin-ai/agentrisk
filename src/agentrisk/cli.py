"""Command-line interface for AgentRisk.

``agentrisk`` wraps the three library functions so you can create a policy, check a
trade, and analyze a portfolio from a shell or CI, with no Python required.

    agentrisk policy init --preset balanced --max-position 25 --block crypto --warn options
    agentrisk check buy 20 NVDA --at 120 --portfolio portfolio.json
    agentrisk analyze portfolio.json --focus tag:ai

``check`` exits non-zero when the verdict is BLOCK, so it composes in a shell:

    agentrisk check buy 5 AAPL --at 205 --portfolio p.json && echo "place the order"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .analyze import analyze_portfolio_risk
from .check import check_trade_risk
from .policy import generate_risk_policy
from .store import resolve_policy_path
from .version import __version__

ASSET_KINDS = ("crypto", "options", "margin")


# --------------------------------------------------------------------------- #
# Color helper (disabled when piped or NO_COLOR is set)                       #
# --------------------------------------------------------------------------- #


class _Style:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _w(self, code: str, s: str) -> str:
        return f"\033[{code}m{s}\033[0m" if self.enabled else s

    def bold(self, s: str) -> str:
        return self._w("1", s)

    def dim(self, s: str) -> str:
        return self._w("90", s)

    def green(self, s: str) -> str:
        return self._w("32", s)

    def red(self, s: str) -> str:
        return self._w("31", s)

    def yellow(self, s: str) -> str:
        return self._w("33", s)

    def cyan(self, s: str) -> str:
        return self._w("36", s)

    def badge(self, verdict: str) -> str:
        if not self.enabled:
            return f"[{verdict}]"
        code = {"PASS": "30;42", "WARN": "30;43", "BLOCK": "97;41",
                "OVERRIDDEN": "30;43"}.get(verdict, "7")
        return f"\033[{code}m {verdict} \033[0m"


C = _Style(sys.stdout.isatty() and os.environ.get("NO_COLOR") is None)


def _load_portfolio(path: str) -> Any:
    text = sys.stdin.read() if path == "-" else Path(path).read_text("utf-8")
    return json.loads(text)


# --------------------------------------------------------------------------- #
# policy                                                                      #
# --------------------------------------------------------------------------- #


def _policy_fields(args: argparse.Namespace) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if args.max_position is not None:
        fields["limits"] = {"max_single_position_pct": args.max_position}
    asset_rules: dict[str, str] = {}
    for kind in args.block or []:
        asset_rules[kind] = "block"
    for kind in args.warn or []:
        asset_rules[kind] = "warn"
    for kind in args.allow or []:
        asset_rules[kind] = "allow"
    if asset_rules:
        fields["asset_rules"] = asset_rules
    order_rules: dict[str, float] = {}
    if args.max_order is not None:
        order_rules["max_order_pct_of_portfolio"] = args.max_order
    if args.min_cash is not None:
        order_rules["min_cash_pct"] = args.min_cash
    if order_rules:
        fields["order_rules"] = order_rules
    if args.max_age is not None:
        fields["data_rules"] = {"max_snapshot_age_hours": args.max_age}
    return fields


def _display_path(path: str | None) -> str:
    if not path:
        return ""
    p = Path(path).absolute()
    try:
        return str(p.relative_to(Path.cwd()))
    except ValueError:
        pass
    try:
        return "~/" + str(p.relative_to(Path.home()))
    except ValueError:
        return str(p)


def cmd_policy_init(args: argparse.Namespace) -> int:
    target = resolve_policy_path(args.policy)
    if args.force and target.exists():
        target.unlink()
    try:
        res = generate_risk_policy(
            "create", preset=args.preset, fields=_policy_fields(args),
            confirm=True, policy_path=str(target),
        )
    except ValueError as exc:
        print(C.red(f"error: {exc}"), file=sys.stderr)
        return 2
    shown = _display_path(res.path)
    print(C.green(f"Policy written to {shown} (revision {res.policy['revision']}).") + "\n")
    for line in res.summary:
        print("  " + line)
    return 0


def cmd_policy_show(args: argparse.Namespace) -> int:
    res = generate_risk_policy("show", policy_path=args.policy)
    if not res.summary:
        print(C.dim(res.message))
        return 1
    print(C.bold(f"Policy at {_display_path(res.path)} (revision {res.policy['revision']})") + "\n")
    for line in res.summary:
        print("  " + line)
    return 0


# --------------------------------------------------------------------------- #
# check                                                                       #
# --------------------------------------------------------------------------- #


def cmd_check(args: argparse.Namespace) -> int:
    if args.at is None and args.limit is None:
        print(C.red("error: provide --at PRICE (market) or --limit PRICE"), file=sys.stderr)
        return 2
    try:
        portfolio = _load_portfolio(args.portfolio)
    except (OSError, json.JSONDecodeError) as exc:
        print(C.red(f"error reading portfolio: {exc}"), file=sys.stderr)
        return 2

    trade: dict[str, Any] = {"action": args.action, "symbol": args.symbol, "quantity": args.quantity}
    if args.limit is not None:
        trade["order_type"] = "limit"
        trade["limit_price"] = args.limit
    else:
        trade["order_type"] = "market"
        trade["estimated_price"] = args.at
    if args.margin:
        trade["uses_margin"] = True

    verdict = check_trade_risk(
        portfolio, trade, policy_path=args.policy,
        override=args.override or None, override_reason=args.reason,
    )

    if args.json:
        print(json.dumps(verdict.model_dump(mode="json"), indent=2))
        return 0 if verdict.proceed else 1

    print(f"{C.badge(verdict.verdict)}  {verdict.summary}\n")
    glyphs = {"block": C.red("x"), "warn": C.yellow("!"), "overridden": C.yellow("~")}
    for check in verdict.checks:
        if check.status.value in glyphs:
            print(f"  {glyphs[check.status.value]} {check.message}")
    if verdict.override_rejected:
        print(C.dim(f"  (cannot be bypassed: {', '.join(verdict.override_rejected)})"))
    return 0 if verdict.proceed else 1


# --------------------------------------------------------------------------- #
# analyze                                                                     #
# --------------------------------------------------------------------------- #


def _print_report(rep: Any) -> None:
    t = rep.totals
    print(C.bold("  Portfolio  ")
          + f"${t['value']:,.0f}   {t['position_count']} positions   {t['cash_pct']}% cash")
    con = rep.concentration
    if con:
        print(f"  {C.dim('Concentration')}  HHI {con['hhi']}  ({con['band'].replace('_', ' ')})")

    print("\n" + C.bold("  Top positions"))
    for row in rep.positions_by_weight[:6]:
        tail = "" if row["classified"] else C.dim("  unclassified")
        print(f"    {row['symbol']:<6} {row['pct']:5.1f}%   ${row['value']:>10,.0f}{tail}")

    sectors = {k: v for k, v in rep.breakdowns.get("by_sector", {}).items() if k != "unclassified"}
    if sectors:
        top = "   ".join(f"{k} {v}%" for k, v in list(sectors.items())[:4])
        print("\n" + C.bold("  By sector  ") + top)

    comp = rep.compliance
    if comp and comp.get("results"):
        print("\n" + C.bold("  Compliance vs policy"))
        marks = {"ok": C.green("ok  "), "near_limit": C.yellow("near"), "breached": C.red("OVER")}
        for r in comp["results"]:
            limit = "" if r["limit"] is None else f" (limit {r['limit']}%)"
            print(f"    [{marks[r['status']]}] {r['subject']} {r['current']}%{limit}")

    focus = rep.focus
    if focus and "exposure_pct" in focus:
        dim, val = next(iter(focus["query"].items()))
        print("\n" + C.bold(f"  Focus {dim}={val}  ") + f"{focus['exposure_pct']}% of portfolio")
        for part in focus.get("contributors", [])[:5]:
            print(f"    {part['symbol']:<6} {part['pct']}%")

    dq = rep.data_quality
    if dq.get("unclassified_pct"):
        print(C.dim(f"\n  {dq['unclassified_pct']}% of the portfolio is unclassified"))


def cmd_analyze(args: argparse.Namespace) -> int:
    try:
        portfolio = _load_portfolio(args.portfolio)
    except (OSError, json.JSONDecodeError) as exc:
        print(C.red(f"error reading portfolio: {exc}"), file=sys.stderr)
        return 2

    focus = None
    if args.focus:
        if ":" not in args.focus:
            print(C.red("error: --focus must be DIM:VALUE (e.g. tag:ai)"), file=sys.stderr)
            return 2
        dim, val = args.focus.split(":", 1)
        focus = {dim: val}

    rep = analyze_portfolio_risk(portfolio, focus=focus, policy_path=args.policy)
    if args.json:
        print(json.dumps(rep.model_dump(mode="json"), indent=2))
        return 0
    _print_report(rep)
    return 0


# --------------------------------------------------------------------------- #
# parser                                                                      #
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agentrisk",
        description="Pre-execution risk checks for AI trading agents.",
    )
    p.add_argument("--version", action="version", version=f"agentrisk {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    policy = sub.add_parser("policy", help="create or show your risk policy")
    psub = policy.add_subparsers(dest="subcommand", required=True)

    init = psub.add_parser("init", help="create a policy from a preset plus explicit rules")
    init.add_argument("--preset", choices=["conservative", "balanced", "aggressive"],
                      default="balanced")
    init.add_argument("--max-position", type=float, metavar="PCT",
                      help="max any single position, percent of portfolio")
    init.add_argument("--block", action="append", choices=ASSET_KINDS, metavar="KIND",
                      help="block crypto/options/margin (repeatable)")
    init.add_argument("--warn", action="append", choices=ASSET_KINDS, metavar="KIND",
                      help="warn on crypto/options/margin (repeatable)")
    init.add_argument("--allow", action="append", choices=ASSET_KINDS, metavar="KIND",
                      help="allow crypto/options/margin (repeatable)")
    init.add_argument("--max-order", type=float, metavar="PCT",
                      help="max single order, percent of portfolio")
    init.add_argument("--min-cash", type=float, metavar="PCT", help="minimum cash floor after buys")
    init.add_argument("--max-age", type=float, metavar="HOURS",
                      help="warn when a snapshot is older than this (default 24)")
    init.add_argument("--policy", metavar="PATH", help="where to write (default .agentrisk/policy.yaml)")
    init.add_argument("--force", action="store_true", help="overwrite an existing policy")
    init.set_defaults(func=cmd_policy_init)

    show = psub.add_parser("show", help="show the current policy in plain English")
    show.add_argument("--policy", metavar="PATH")
    show.set_defaults(func=cmd_policy_show)

    check = sub.add_parser("check", help="validate a proposed trade before execution")
    check.add_argument("action", choices=["buy", "sell"])
    check.add_argument("quantity", type=float)
    check.add_argument("symbol")
    check.add_argument("--at", type=float, metavar="PRICE", help="estimated market price")
    check.add_argument("--limit", type=float, metavar="PRICE", help="limit price")
    check.add_argument("--portfolio", required=True, metavar="PATH",
                       help="portfolio JSON file, or - for stdin")
    check.add_argument("--policy", metavar="PATH")
    check.add_argument("--margin", action="store_true", help="the order uses margin/leverage")
    check.add_argument("--override", action="append", metavar="TOKEN",
                       help="one-time bypass of a named block (repeatable)")
    check.add_argument("--reason", metavar="TEXT", help="reason recorded with an override")
    check.add_argument("--json", action="store_true", help="print the raw verdict as JSON")
    check.set_defaults(func=cmd_check)

    analyze = sub.add_parser("analyze", help="analyze a portfolio's risk")
    analyze.add_argument("portfolio", metavar="PATH", help="portfolio JSON file, or - for stdin")
    analyze.add_argument("--focus", metavar="DIM:VALUE",
                         help="spotlight one exposure, e.g. tag:ai, sector:technology, symbol:NVDA")
    analyze.add_argument("--policy", metavar="PATH")
    analyze.add_argument("--json", action="store_true", help="print the raw report as JSON")
    analyze.set_defaults(func=cmd_analyze)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
