"""Expand the bundled classification dataset from the Nasdaq Trader directory.

Adds asset_class and a name for every US-listed symbol that is missing. Curated
entries (the ones carrying sectors and theme tags) are never overwritten. Runs at
build time only; the shipped library makes no network calls.

Usage:
    python scripts/expand_seed.py --dry-run
    python scripts/expand_seed.py
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

NASDAQ_LISTED = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
OTHER_LISTED = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"

DATA_FILE = Path(__file__).resolve().parent.parent / "src/agentrisk/data/classifications.json"

_ALLOWED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.")


def _fetch(url: str) -> list[str]:
    req = urllib.request.Request(url, headers={"User-Agent": "agentrisk-seed-builder"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - fixed, trusted URL
        return resp.read().decode("utf-8", errors="replace").splitlines()


def _clean_symbol(sym: str) -> str | None:
    sym = sym.strip().upper()
    if not sym or any(ch not in _ALLOWED for ch in sym):
        return None
    return sym


def _parse(lines: list[str], sym_i: int, name_i: int, etf_i: int, test_i: int) -> dict[str, dict]:
    """Parse a pipe-delimited Nasdaq Trader file into {symbol: {asset_class, name}}."""
    out: dict[str, dict] = {}
    for line in lines[1:]:  # skip header row
        if line.startswith("File Creation Time"):
            continue
        parts = line.split("|")
        if len(parts) <= max(sym_i, name_i, etf_i, test_i):
            continue
        if parts[test_i].strip().upper() == "Y":  # skip test issues
            continue
        sym = _clean_symbol(parts[sym_i])
        if sym is None:
            continue
        asset_class = "etf" if parts[etf_i].strip().upper() == "Y" else "equity"
        out[sym] = {"asset_class": asset_class, "name": parts[name_i].strip()}
    return out


def build_universe() -> dict[str, dict]:
    # nasdaqlisted: Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot|ETF|NextShares
    nasdaq = _parse(_fetch(NASDAQ_LISTED), sym_i=0, name_i=1, etf_i=6, test_i=3)
    # otherlisted: ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot|Test Issue|NASDAQ Symbol
    other = _parse(_fetch(OTHER_LISTED), sym_i=0, name_i=1, etf_i=4, test_i=6)
    universe = {**other, **nasdaq}  # Nasdaq wins ties; both are fine
    return universe


def main() -> int:
    ap = argparse.ArgumentParser(description="Expand the AgentRisk classification dataset.")
    ap.add_argument("--dry-run", action="store_true", help="report changes without writing")
    ap.add_argument("--out", default=str(DATA_FILE), help="path to classifications.json")
    args = ap.parse_args()

    data = json.loads(Path(args.out).read_text("utf-8"))
    instruments: dict[str, dict] = data["instruments"]
    curated_before = len(instruments)

    print("Fetching the Nasdaq Trader symbol directory ...", file=sys.stderr)
    universe = build_universe()

    added = 0
    for sym, info in universe.items():
        if sym in instruments:
            continue  # never overwrite a curated entry
        instruments[sym] = {
            "asset_class": info["asset_class"],
            "sector": None,
            "tags": [],
            "name": info["name"],
            "source": "nasdaqtrader",
        }
        added += 1

    total = len(instruments)
    print(f"Curated entries preserved: {curated_before}")
    print(f"Symbols in listed universe: {len(universe)}")
    print(f"New symbols added:          {added}")
    print(f"Total after merge:          {total}")

    if args.dry_run:
        print("\n(dry run: nothing written)")
        return 0

    data["instruments"] = dict(sorted(instruments.items()))
    data["source"] = (
        "AgentRisk curated seed dataset; asset classes for the broader US-listed "
        "universe derived from the public Nasdaq Trader symbol directory"
    )
    Path(args.out).write_text(json.dumps(data, indent=2) + "\n", "utf-8")
    print(f"\nWrote {args.out}")
    print("Run `pytest tests/test_seed_data.py` to lint the result.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
