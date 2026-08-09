"""The runnable example must keep producing the verdicts its comments claim.

``examples/agent_loop.py`` is the one example a reader is invited to run, and its
inline comments assert a verdict per trade. Those comments drifted once already:
the sample snapshot carries a fixed ``as_of``, so once it aged past the staleness
window every trade picked up a stale-data warning and three of the five comments
became wrong. Run the example here so that drift fails the suite instead.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "agent_loop.py"

# The verdicts the inline comments in the example promise, in order.
EXPECTED_VERDICTS = ["PASS", "BLOCK", "BLOCK", "WARN", "PASS"]


def _run_example() -> str:
    result = subprocess.run(
        [sys.executable, str(EXAMPLE)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"the example exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result.stdout


def test_example_verdicts_match_its_comments():
    output = _run_example()
    verdicts = re.findall(r"Verdict: (\w+)", output)
    assert verdicts == EXPECTED_VERDICTS, output


def test_example_snapshot_is_not_stale():
    # The staleness warning is the specific drift this test exists to catch, so
    # assert on it directly rather than only through the verdicts above.
    assert "snapshot is" not in _run_example()


def test_blocked_trades_are_never_executed():
    # The gate is the point of the example. A BLOCK must not reach the mock broker.
    output = _run_example()
    blocks = output.count("Verdict: BLOCK")
    assert blocks == EXPECTED_VERDICTS.count("BLOCK")
    assert output.count("Execution refused.") == blocks
