"""Sync the bundled classification dataset with the Nasdaq Trader directory.

The dataset has two layers. The curated overlay (entries whose ``source`` is
``"curated"``) carries sectors and theme tags, is maintained by hand, and is never
touched here. The base layer (``source`` ``"nasdaqtrader"``) records an asset
class and a name for every other US-listed symbol, and this script makes it match
the current directory: new listings are added, symbols that are no longer listed
are removed, and names or asset classes that changed are updated. It also stamps
the dataset's ``version`` with the year and month of the sync, which every verdict
reports as ``classification_data_version``.

Runs at build time only; the shipped library makes no network calls.

Usage:
    python scripts/expand_seed.py --dry-run
    python scripts/expand_seed.py
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

NASDAQ_LISTED = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
OTHER_LISTED = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"

DATA_FILE = Path(__file__).resolve().parent.parent / "src/agentrisk/data/classifications.json"

# The only source this script owns. Curated entries, and any other source added
# later, are carried through untouched.
BASE_SOURCE = "nasdaqtrader"

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


def sync(instruments: dict[str, dict], universe: dict[str, dict]) -> tuple[dict[str, dict], dict]:
    """Return the synced instrument map and a summary of what changed.

    Entries the script does not own pass through unchanged. Base entries are
    rebuilt from the directory, keeping any sector or tags a base entry already
    carried so a hand edit that forgot to flip ``source`` is not silently lost.
    """
    kept = {s: e for s, e in instruments.items() if e.get("source") != BASE_SOURCE}
    base = {s: e for s, e in instruments.items() if e.get("source") == BASE_SOURCE}

    added: list[str] = []
    updated: list[tuple[str, str, str]] = []
    synced: dict[str, dict] = {}
    for sym, info in universe.items():
        if sym in kept:
            continue
        old = base.get(sym)
        entry = {
            "asset_class": info["asset_class"],
            "sector": old.get("sector") if old else None,
            "tags": list(old.get("tags", [])) if old else [],
            "name": info["name"],
            "source": BASE_SOURCE,
        }
        if old is None:
            added.append(sym)
        elif old.get("name") != entry["name"] or old.get("asset_class") != entry["asset_class"]:
            updated.append((sym, old.get("name", ""), entry["name"]))
        synced[sym] = entry
    removed = sorted(s for s in base if s not in universe)

    merged = dict(sorted({**kept, **synced}.items()))
    summary = {
        "kept": len(kept),
        "listed": len(universe),
        "added": sorted(added),
        "removed": removed,
        "updated": sorted(updated),
        "total": len(merged),
    }
    return merged, summary


def _preview(label: str, items: list, limit: int = 8) -> str:
    shown = ", ".join(str(i) if isinstance(i, str) else i[0] for i in items[:limit])
    more = f" ... and {len(items) - limit} more" if len(items) > limit else ""
    return f"{label:<34}{len(items):>6}  {shown}{more}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync the AgentRisk classification dataset.")
    ap.add_argument("--dry-run", action="store_true", help="report changes without writing")
    ap.add_argument("--out", default=str(DATA_FILE), help="path to classifications.json")
    ap.add_argument(
        "--version",
        default=datetime.now(timezone.utc).strftime("%Y.%m"),
        help="dataset version stamp to record (default: current UTC year.month)",
    )
    args = ap.parse_args()

    data = json.loads(Path(args.out).read_text("utf-8"))

    print("Fetching the Nasdaq Trader symbol directory ...", file=sys.stderr)
    universe = build_universe()
    merged, summary = sync(data["instruments"], universe)

    print(f"Entries not owned by this script:  {summary['kept']:>6}  (curated and other sources)")
    print(f"Symbols in the listed universe:    {summary['listed']:>6}")
    print(_preview("New listings added:", summary["added"]))
    print(_preview("Delisted symbols removed:", summary["removed"]))
    print(_preview("Names or classes updated:", summary["updated"]))
    print(f"Total after sync:                  {summary['total']:>6}")
    print(f"Version stamp:                     {data.get('version')} -> {args.version}")

    if args.dry_run:
        print("\n(dry run: nothing written)")
        return 0

    data["instruments"] = merged
    data["version"] = args.version
    data["source"] = (
        "AgentRisk curated seed dataset; asset classes for the broader US-listed "
        "universe derived from the public Nasdaq Trader symbol directory"
    )
    Path(args.out).write_text(json.dumps(data, indent=2) + "\n", "utf-8")
    print(f"\nWrote {args.out}")
    print("Next: pytest tests/test_seed_data.py, then AGENTRISK_REGEN=1 pytest tests/test_golden.py")
    print("(the version stamp is part of every verdict's engine metadata, so the goldens move).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
