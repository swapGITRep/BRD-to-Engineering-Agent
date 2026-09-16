"""
skills/tech_radar.py
─────────────────────────────────────────────────────────────────────────────
Parses knowledge_base/corpus/org_standards/tech_radar.md into structured
entries. Backs the Tech Stack Recommender's check_tech_radar_status tool
(see agents/tech_stack_agent.py) — a real lookup against the actual KB file,
not a mock, so the tool's answer changes if the org updates the radar.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Dict, List, Optional

DEFAULT_PATH = Path(__file__).parent.parent / "knowledge_base" / "corpus" / "org_standards" / "tech_radar.md"

# "- Name — STATUS rest of the note" (STATUS one of the radar's four values)
_LINE_RE = re.compile(r"^-\s+(?P<name>[^—]+?)\s+—\s+(?P<status>ADOPT|TRIAL|HOLD|RETIRE)\b\s*(?P<note>.*)$")


@functools.lru_cache(maxsize=4)
def _entries(path: str) -> List[Dict[str, str]]:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        m = _LINE_RE.match(line.strip())
        if m:
            out.append({
                "technology": m.group("name").strip(),
                "status": m.group("status"),
                "note": m.group("note").strip().rstrip("."),
            })
    return out


def lookup_tech_radar_status(technology: str, path: Path | str = DEFAULT_PATH) -> Optional[Dict[str, str]]:
    """Case-insensitive substring match against the radar (either direction,
    so 'Postgres' matches 'PostgreSQL (Azure Database for ...)' and 'FastAPI'
    matches 'FastAPI'). Returns the first match, or None if the technology
    isn't on the radar at all."""
    if not technology or not technology.strip():
        return None
    q = technology.strip().lower()
    for entry in _entries(str(path)):
        name = entry["technology"].lower()
        if q in name or name in q:
            return entry
    return None
