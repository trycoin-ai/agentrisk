# Contributing to AgentRisk

Thanks for helping build open risk infrastructure for agentic trading.

## Principles (please keep these intact)

- **The core stays pure.** No network calls, no LLM calls, no API keys in
  `src/agentrisk/` (except the optional MCP server, which contains no logic).
- **Deterministic and testable.** Same inputs, same output. New behavior needs
  tests; changes to verdict math or wording must update the golden fixtures.
- **Fail closed and never trap exits.** Preserve these safety behaviors.
- **All user-facing wording lives in `messages.py`** and must follow the language
  rules (never "safe" / "approved" / "recommended"; always attribute limits to the
  user).

## Dev setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check . && mypy
```

## Updating golden fixtures

If you intentionally change check math or a message template:

```bash
AGENTRISK_REGEN=1 pytest tests/test_golden.py
git diff tests/golden        # review every change as a diff
```

## Contributing classification data

Edit `src/agentrisk/data/classifications.json` (or `taxonomy.json`). Each instrument
needs a valid `asset_class`, a `sector` in the taxonomy (or `null`), `tags` from the
taxonomy, and a `source`. The lint in `tests/test_seed_data.py` enforces this. Theme
tags are subjective, so include a brief rationale in your PR.

## Scope

AgentRisk will never add: trade recommendations, signals, execution, performance
marketing, or telemetry. Features that require those are out of scope by design.

## Pull requests

Keep PRs focused, add tests, run the suite and linters, and update docs when
behavior changes. Issue templates exist for bug reports, classification corrections,
and rule requests.

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). Be kind.
