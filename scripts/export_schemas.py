"""Export JSON Schemas for the public models into ./schemas/.

These schemas power editor tooling and document the tool inputs/outputs. Run:

    python scripts/export_schemas.py
"""

from __future__ import annotations

import json
from pathlib import Path

from agentrisk.models import Policy, Portfolio, RiskReport, Trade, Verdict

OUT = Path(__file__).resolve().parent.parent / "schemas"
MODELS = {
    "portfolio": Portfolio,
    "trade": Trade,
    "policy": Policy,
    "verdict": Verdict,
    "risk_report": RiskReport,
}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, model in MODELS.items():
        schema = model.model_json_schema()
        (OUT / f"{name}.schema.json").write_text(json.dumps(schema, indent=2) + "\n")
        print(f"wrote schemas/{name}.schema.json")


if __name__ == "__main__":
    main()
