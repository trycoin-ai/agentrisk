"""One version, recorded in one place at a time.

A release has to bump the version in the package, the packaging metadata, the MCP
registry entry, the plugin manifests, and the golden fixtures. Miss one and the
repository ships a contradiction: a plugin advertising a version the package is
not, or a registry entry pointing at a package index version that does not exist.

Rather than pin a hand-written list that goes stale, this discovers every recorded
version and reports the whole set, so a location added later is covered without
anyone remembering to update this file.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:
    tomllib = pytest.importorskip("tomli", reason="needs tomllib or tomli to read pyproject")

from agentrisk import __version__

REPO = Path(__file__).resolve().parent.parent

# These record the bundled classification data's release, not the package's, and
# move on a completely different schedule.
DATA_VERSION_KEYS = {"classification_data_version", "schema_version"}
DATA_PATHS = ("src/agentrisk/data/",)

# A floor, not a fixture: discovery finding fewer files than this means the walk
# broke, which would make the whole test silently vacuous.
KNOWN_VERSIONED_FILES = {
    "pyproject.toml",
    "server.json",
    "src/agentrisk/version.py",
    ".claude-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
}


def _tracked_files(*suffixes: str) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", *[f"*{s}" for s in suffixes]],
        cwd=REPO, capture_output=True, text=True, check=True,
    )
    return [REPO / line for line in out.stdout.split("\n") if line]


def _walk_json(obj, path: str = ""):
    """Yield (keypath, value) for every version-looking scalar key."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            here = f"{path}.{key}" if path else key
            if "version" in key.lower() and not isinstance(value, (dict, list)):
                yield here, value
            yield from _walk_json(value, here)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from _walk_json(value, f"{path}[{index}]")


def _discover() -> list[tuple[str, str, str]]:
    """Every (relative path, key path, value) recording the package version."""
    found: list[tuple[str, str, str]] = []

    for path in _tracked_files(".json"):
        rel = path.relative_to(REPO).as_posix()
        if any(rel.startswith(p) for p in DATA_PATHS):
            continue
        for keypath, value in _walk_json(json.loads(path.read_text("utf-8"))):
            if keypath.rsplit(".", 1)[-1] in DATA_VERSION_KEYS:
                continue
            found.append((rel, keypath, str(value)))

    pyproject = REPO / "pyproject.toml"
    with pyproject.open("rb") as handle:
        found.append(("pyproject.toml", "project.version",
                      tomllib.load(handle)["project"]["version"]))

    # version.py is the source of truth the rest are compared against, so read it
    # from the file rather than trusting the already-imported value.
    text = (REPO / "src/agentrisk/version.py").read_text("utf-8")
    literal = text.split("__version__", 1)[1].split("=", 1)[1].strip().strip('"\'')
    found.append(("src/agentrisk/version.py", "__version__", literal))

    return sorted(found)


def _report(found) -> str:
    return "\n".join(f"  {value:>10}  {path} :: {keypath}" for path, keypath, value in found)


def test_every_recorded_version_matches_the_package():
    found = _discover()
    mismatched = [entry for entry in found if entry[2] != __version__]
    assert not mismatched, (
        f"expected every recorded version to be {__version__}\n"
        f"mismatched:\n{_report(mismatched)}\n\nall discovered:\n{_report(found)}"
    )


def test_discovery_still_covers_the_known_files():
    files = {path for path, _, _ in _discover()}
    missing = KNOWN_VERSIONED_FILES - files
    assert not missing, (
        f"discovery stopped finding versions in: {sorted(missing)}. "
        "Either the file moved or the walk is broken, and this test would now "
        f"pass vacuously. Found: {sorted(files)}"
    )


def test_golden_fixtures_are_regenerated_with_the_release():
    # The goldens are compared whole in test_golden.py, engine metadata included,
    # so a version bump without AGENTRISK_REGEN=1 leaves them failing.
    goldens = [entry for entry in _discover() if entry[0].startswith("tests/golden/")]
    assert goldens, "expected the golden fixtures to record an engine version"
    stale = [entry for entry in goldens if entry[2] != __version__]
    assert not stale, (
        "golden fixtures still record an older version; regenerate them with\n"
        f"    AGENTRISK_REGEN=1 pytest tests/test_golden.py\n{_report(stale)}"
    )
