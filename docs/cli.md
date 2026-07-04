# CLI reference

The `agentrisk` command wraps the three tools for shell and CI use. It reads a
portfolio from a JSON file (or `-` for stdin) and a policy from a file or the
default location (`./.agentrisk/policy.yaml`, overridable with `AGENTRISK_HOME` or
`--policy`). It is installed with the package (`pip install agentrisk`).

Colors are used on a terminal and disabled when output is piped or `NO_COLOR` is set.

## Try it

Run all three commands against the bundled example portfolio from a checkout:

```bash
git clone https://github.com/trycoin-ai/agentrisk.git && cd agentrisk
pip install -e .
agentrisk policy init --preset balanced --max-position 25 --block crypto --block margin --warn options
agentrisk check buy 20 NVDA --at 120 --portfolio examples/sample_portfolio.json
agentrisk analyze examples/sample_portfolio.json --focus tag:ai
```

The `check` command exits non-zero here because the buy breaks the 25% single-name
limit.

## `agentrisk policy`

Create or show your risk policy.

```bash
# create a policy from a preset plus explicit rules
agentrisk policy init --preset balanced --max-position 25 \
  --block crypto --block margin --warn options --min-cash 5 --max-order 10

# show the current policy in plain English
agentrisk policy show
```

`init` flags: `--preset {conservative|balanced|aggressive}`, `--max-position PCT`,
`--block/--warn/--allow {crypto|options|margin}` (repeatable), `--max-order PCT`,
`--min-cash PCT`, `--max-age HOURS`, `--policy PATH`, `--force`.

## `agentrisk check`

Validate a proposed trade before execution. **Exits non-zero when the verdict is
BLOCK**, so it composes in a shell:

```bash
agentrisk check buy 20 NVDA --at 120 --portfolio portfolio.json && echo "no policy violation"
```

Positional: `action` (`buy`/`sell`), `quantity`, `symbol`. Flags: `--at PRICE`
(market) or `--limit PRICE`, `--portfolio PATH`, `--policy PATH`, `--margin`,
`--override TOKEN` (repeatable), `--reason TEXT`, `--json`.

A blocked trade prints the block tokens you can bypass in its detail lines; pass one
to `--override` (with a `--reason`) to allow a single trade through without changing
the policy. See [policy-reference.md](policy-reference.md) for the override tiers.

## `agentrisk analyze`

Report a portfolio's risk.

```bash
agentrisk analyze portfolio.json
agentrisk analyze portfolio.json --focus tag:ai
```

Positional: `portfolio` (JSON file or `-`). Flags: `--focus DIM:VALUE`
(`tag:ai`, `sector:technology`, `asset_class:crypto`, `symbol:NVDA`), `--policy PATH`,
`--json`.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success; for `check`, the trade may proceed (PASS / WARN / OVERRIDDEN). |
| 1 | `check` returned BLOCK (do not execute), or `policy show` found no policy. |
| 2 | Usage or input error (bad arguments, unreadable portfolio). |
