"""
skills/brd_parser.py
─────────────────────────────────────────────────────────────────────────────
Capability 1 — BRD Ingestion & Parsing.

  load_document(path)              → normalized plain text (.docx/.pdf/.md/.txt)
  extract_sections(text)           → [BRDSection]           (heading-based, no LLM)
  classify_requirements(secs, llm) → [Requirement]          (one LLM call / section)
  tag_metadata(secs, llm)          → dict                   (one LLM call)

Both LLM replies are validated against a pydantic schema (skills/schemas.py)
and retried once with the exact problem fed back — the same guarantee the
specialist agents get from invoke_json().

The LLM object passed in only needs an `.invoke(messages) -> obj.content` method,
so it can be a real `ChatOpenAI` or a test double.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from langchain_core.messages import HumanMessage, SystemMessage

from orchestration.state import BRDSection, Requirement
from skills.json_utils import invoke_validated_json
from skills.schemas import ProjectMetadata, RequirementsResponse

logger = logging.getLogger(__name__)

SUPPORTED_EXTS = {".md", ".txt", ".docx", ".pdf"}

_VALID_TYPES = {
    "functional", "non_functional", "constraint", "assumption", "out_of_scope",
}
_VALID_NFR = {
    "performance", "security", "scalability", "availability", "compliance", "usability",
}
_VALID_PRIORITY = {"must", "should", "could", "wont"}

_MIN_SECTION_CHARS = 20  # sections shorter than this are not sent for classification


# ─────────────────────────────────────────────────────────────────────────────
# 1. Document loading
# ─────────────────────────────────────────────────────────────────────────────
def load_document(path: str) -> str:
    """Load a BRD file and return normalized plain text."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"BRD file not found: {path}")
    ext = p.suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise ValueError(
            f"Unsupported BRD format '{ext}'. Supported: {sorted(SUPPORTED_EXTS)}"
        )

    if ext in (".md", ".txt"):
        text = p.read_text(encoding="utf-8", errors="replace")
    elif ext == ".docx":
        text = _load_docx(p)
    else:  # .pdf
        text = _load_pdf(p)

    return _normalize(text)


def _load_docx(p: Path) -> str:
    try:
        import docx  # python-docx
    except ImportError as e:  # pragma: no cover - env guard
        raise RuntimeError("python-docx is required to read .docx BRDs") from e
    document = docx.Document(str(p))
    lines: List[str] = []
    for para in document.paragraphs:
        style = (para.style.name or "").lower() if para.style else ""
        text = para.text.strip()
        if not text:
            continue
        if style.startswith("heading"):
            level = "".join(ch for ch in style if ch.isdigit()) or "1"
            lines.append(f"{'#' * min(int(level), 6)} {text}")
        else:
            lines.append(text)
    return "\n".join(lines)


def _load_pdf(p: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover - env guard
        raise RuntimeError("pypdf is required to read .pdf BRDs") from e
    reader = PdfReader(str(p))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Section extraction (heading-based, deterministic)
# ─────────────────────────────────────────────────────────────────────────────
_MD_HEADING  = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_NUM_HEADING = re.compile(r"^\s*(\d+(?:\.\d+){0,5})\.?\s+(\S.{0,200})$")
# Verbs that mark a line as a requirement statement rather than a section title.
_REQUIREMENT_VERB = re.compile(r"\b(must|shall|should|will|may|can|able to)\b", re.I)

_MAX_HEADING_LEN = 64


def _looks_like_title(text: str) -> bool:
    """A heading title is short, verb-free, and not sentence-punctuated."""
    return (
        1 <= len(text) <= _MAX_HEADING_LEN
        and not text.endswith((".", ",", ";", ":"))
        and _REQUIREMENT_VERB.search(text) is None
    )


def _heading_level(line: str) -> tuple[int, str] | None:
    """Return (level, title) if `line` is a heading, else None."""
    m = _MD_HEADING.match(line)
    if m:
        return len(m.group(1)), m.group(2).strip()

    m = _NUM_HEADING.match(line)
    if m:
        token, title = m.group(1), m.group(2).strip()
        if _looks_like_title(title):
            return token.count(".") + 1, title
        return None

    stripped = line.strip()
    if (
        3 <= len(stripped) <= _MAX_HEADING_LEN
        and stripped == stripped.upper()
        and any(c.isalpha() for c in stripped)
        and sum(c.isdigit() for c in stripped) <= 2
        and 1 <= len(stripped.split()) <= 8
        and not stripped.endswith((".", ":", ";", ","))
        and _REQUIREMENT_VERB.search(stripped) is None
    ):
        return 1, stripped.title()

    return None


def extract_sections(text: str) -> List[BRDSection]:
    """Split BRD text into heading-delimited sections."""
    lines = text.split("\n")
    sections: List[BRDSection] = []
    counter = 0

    def _flush(title: str, level: int, body: List[str]) -> None:
        nonlocal counter
        raw = "\n".join(body).strip()
        if not title and not raw:
            return
        counter += 1
        sections.append(
            BRDSection(
                section_id=f"S{counter:03d}",
                title=title or "Preamble",
                level=level,
                raw_text=raw,
                page_range="",
            )
        )

    cur_title, cur_level, cur_body = "", 1, []
    for line in lines:
        h = _heading_level(line)
        if h is None:
            cur_body.append(line)
            continue
        _flush(cur_title, cur_level, cur_body)
        cur_level, cur_title = h
        cur_body = []
    _flush(cur_title, cur_level, cur_body)

    return sections


# ─────────────────────────────────────────────────────────────────────────────
# 3. Requirement classification (LLM)
# ─────────────────────────────────────────────────────────────────────────────
_CLASSIFY_SYSTEM = """You are a requirements analyst. Given one section of a Business
Requirements Document, extract every ATOMIC requirement it states.

For each requirement return an object:
{
  "text": "<single, self-contained requirement statement>",
  "type": "functional | non_functional | constraint | assumption | out_of_scope",
  "nfr_category": "performance | security | scalability | availability | compliance | usability | null",
  "priority": "must | should | could | wont",
  "ambiguity_flag": true | false
}

Rules:
- Split compound sentences into separate requirements.
- "type" = non_functional only for quality attributes; set nfr_category accordingly (else null).
- ambiguity_flag = true when the statement is vague, unmeasurable, or contradictory.
- If the section states no requirements, return an empty list.

Return ONLY JSON: {"requirements": [ ... ]}
"""


def classify_requirements(sections: List[BRDSection], llm: Any) -> List[Requirement]:
    """Classify requirements section-by-section. Returns a flat, id-assigned list."""
    out: List[Requirement] = []
    for section in sections:
        if len(section["raw_text"]) < _MIN_SECTION_CHARS:
            continue
        try:
            parsed = invoke_validated_json(
                llm,
                [
                    SystemMessage(content=_CLASSIFY_SYSTEM),
                    HumanMessage(content=(
                        f"SECTION TITLE: {section['title']}\n\n"
                        f"SECTION TEXT:\n{section['raw_text']}"
                    )),
                ],
                schema=RequirementsResponse,
                label=f"brd_ingest:classify:{section['section_id']}",
            )
        except Exception as e:  # noqa: BLE001 - one bad section must not abort ingest
            logger.warning("classify_requirements failed for %s: %s", section["section_id"], e)
            continue

        for raw in parsed["requirements"]:
            coerced = _coerce_requirement(raw, section["section_id"], len(out) + 1)
            if coerced:
                out.append(coerced)

    logger.info("Classified %d requirement(s) across %d section(s)", len(out), len(sections))
    return out


def _coerce_requirement(raw: Dict[str, Any], section_id: str, ordinal: int) -> Requirement | None:
    text = str(raw.get("text", "")).strip()
    if not text:
        return None

    nfr = raw.get("nfr_category")
    nfr = str(nfr).strip().lower() if nfr not in (None, "", "null") else None
    if nfr not in _VALID_NFR:
        nfr = None

    rtype = str(raw.get("type", "functional")).strip().lower()
    if rtype in _VALID_NFR:
        # The model put an NFR *category* in the `type` field (seen live:
        # type="security"). Its intent is unambiguous — a non-functional
        # requirement of that category — so map it rather than let the
        # fallback below silently relabel it "functional". An explicit,
        # valid nfr_category on the same item is the more specific field
        # and wins.
        logger.info("R%03d: type %r is an NFR category — mapped to non_functional/%s",
                    ordinal, rtype, nfr or rtype)
        nfr = nfr or rtype
        rtype = "non_functional"
    elif rtype not in _VALID_TYPES:
        logger.warning("R%03d: unrecognised requirement type %r — treated as 'functional'",
                       ordinal, raw.get("type"))
        rtype = "functional"
    if rtype != "non_functional":
        nfr = None

    priority = str(raw.get("priority", "should")).strip().lower()
    if priority not in _VALID_PRIORITY:
        logger.warning("R%03d: unrecognised priority %r — treated as 'should'",
                       ordinal, raw.get("priority"))
        priority = "should"

    return Requirement(
        req_id=f"R{ordinal:03d}",
        section_id=section_id,
        text=text,
        type=rtype,
        nfr_category=nfr,
        priority=priority,
        ambiguity_flag=bool(raw.get("ambiguity_flag", False)),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Metadata tagging (LLM)
# ─────────────────────────────────────────────────────────────────────────────
_METADATA_SYSTEM = """You extract structured metadata from a Business Requirements
Document. Return ONLY this JSON object (use [] / "" when absent):
{
  "project_name": "",
  "stakeholders": ["role or name"],
  "target_dates": [{"label": "", "date": ""}],
  "business_goals": [""],
  "success_metrics": [""],
  "glossary": [{"term": "", "definition": ""}],
  "referenced_systems": [""]
}
"""

_METADATA_KEYS = (
    "project_name", "stakeholders", "target_dates", "business_goals",
    "success_metrics", "glossary", "referenced_systems",
)


def tag_metadata(sections: List[BRDSection], llm: Any) -> Dict[str, Any]:
    """Extract project-level metadata from the whole BRD."""
    doc = "\n\n".join(f"## {s['title']}\n{s['raw_text']}" for s in sections)[:16000]
    try:
        parsed = invoke_validated_json(
            llm,
            [
                SystemMessage(content=_METADATA_SYSTEM),
                HumanMessage(content=f"BRD:\n{doc}"),
            ],
            schema=ProjectMetadata,
            label="brd_ingest:metadata",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("tag_metadata failed: %s", e)
        parsed = ProjectMetadata().model_dump()

    return {key: parsed[key] for key in _METADATA_KEYS}
