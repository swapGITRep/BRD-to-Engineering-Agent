#!/usr/bin/env python3
"""
scripts/verify_deliverables.py
─────────────────────────────────────────────────────────────────────────────
Re-validates a run's *saved* deliverables against the same pydantic schemas
invoke_json() checks live (skills/schemas.py) — the direct way to confirm
what actually landed on disk really satisfies each agent's contract, without
digging through logs or re-running the pipeline.

Note this is necessarily "did the persisted JSON pass schema validation" —
by construction, anything invoke_json() accepted already passed once; this
tool is for auditing saved runs after the fact (including runs from before
schema validation existed), or CI, not for catching something invoke_json()
would have missed.

Usage:
    python scripts/verify_deliverables.py output/deliverables/
    python scripts/verify_deliverables.py output/reports/<brd_id>_deliverables.json
    python scripts/verify_deliverables.py output/reports/*_deliverables.json

Exit code is non-zero if any agent's content fails validation — wire this
into CI on any change to an agent's schema or prompt.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, Tuple

from pydantic import ValidationError

from skills.schemas import AGENT_SCHEMAS


def _entries_from_bundle(path: Path) -> Iterator[Tuple[str, str, Dict[str, Any]]]:
    """<brd_id>_deliverables.json: {agent_key: {..., "content": {...}}, ...}"""
    data = json.loads(path.read_text(encoding="utf-8"))
    for agent_key, artifact in data.items():
        if agent_key in AGENT_SCHEMAS and isinstance(artifact, dict):
            yield str(path), agent_key, artifact.get("content", {})


def _entries_from_dir(path: Path) -> Iterator[Tuple[str, str, Dict[str, Any]]]:
    """output/deliverables/: one <agent>.json per agent, same artifact shape."""
    for f in sorted(path.glob("*.json")):
        agent_key = f.stem
        if agent_key in AGENT_SCHEMAS:
            artifact = json.loads(f.read_text(encoding="utf-8"))
            yield str(f), agent_key, artifact.get("content", {})


def _entries_from_single_agent_file(path: Path) -> Iterator[Tuple[str, str, Dict[str, Any]]]:
    """A lone <agent>.json (not inside output/deliverables/)."""
    agent_key = path.stem
    artifact = json.loads(path.read_text(encoding="utf-8"))
    yield str(path), agent_key, artifact.get("content", {})


def iter_entries(target: str) -> Iterator[Tuple[str, str, Dict[str, Any]]]:
    p = Path(target)
    if p.is_dir():
        yield from _entries_from_dir(p)
    elif p.name.endswith("_deliverables.json"):
        yield from _entries_from_bundle(p)
    elif p.stem in AGENT_SCHEMAS:
        yield from _entries_from_single_agent_file(p)
    else:
        print(f"skip (not a recognized deliverables file): {p}", file=sys.stderr)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    failures = 0
    checked = 0
    for target in sys.argv[1:]:
        for source, agent_key, content in iter_entries(target):
            checked += 1
            schema = AGENT_SCHEMAS[agent_key]
            try:
                schema.model_validate(content)
            except ValidationError as e:
                failures += 1
                print(f"✗ {source} :: {agent_key} — {e.error_count()} validation error(s)")
                for err in e.errors():
                    loc = ".".join(str(p) for p in err["loc"]) or "(root)"
                    print(f"    {loc}: {err['msg']}")
            else:
                print(f"✓ {source} :: {agent_key}")

    print(f"\n{checked - failures}/{checked} passed schema validation.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
