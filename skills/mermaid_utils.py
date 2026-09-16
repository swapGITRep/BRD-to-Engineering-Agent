"""
skills/mermaid_utils.py
─────────────────────────────────────────────────────────────────────────────
Best-effort clean-up of LLM-generated Mermaid so common mistakes (unquoted node
labels containing parentheses, commas, pipes, colons, <br>, quotes) don't break
the parser. Not a full Mermaid grammar — a pragmatic pre-pass. Callers should
still degrade gracefully if rendering fails.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import re

_RISKY = re.compile(r'[()\[\]{}<>|:;,"@#&/\\]')

# (open, close, inner-forbidden-class) for single-char node shapes [text] (text) {text}
_SHAPES = (
    ("[", "]", r"\[\]\n"),
    ("(", ")", r"()\n"),
    ("{", "}", r"{}\n"),
)


def _quote(text: str) -> str:
    t = text.strip()
    if len(t) >= 2 and t[0] == '"' and t[-1] == '"':
        return text
    if not t or not _RISKY.search(t):
        return text
    return '"' + t.replace('"', "'").replace("\n", " ") + '"'


def sanitize_mermaid(code: str) -> str:
    """Return Mermaid source with risky node labels quoted and edge labels cleaned."""
    if not code or not code.strip():
        return "graph TD; A[No diagram provided];"

    code = code.strip().replace("```mermaid", "").replace("```", "").strip()

    # `graph TD;` → `graph TD` (a trailing ';' on the directive trips some builds)
    code = re.sub(r"^(\s*(?:graph|flowchart)\s+\w+)\s*;", r"\1", code)

    # Quote node-shape labels that contain risky characters.
    for o, c, forbidden in _SHAPES:
        pattern = re.compile(re.escape(o) + r"([^" + forbidden + r"]*?)" + re.escape(c))
        code = pattern.sub(lambda m, o=o, c=c: o + _quote(m.group(1)) + c, code)

    # `subgraph Multi Word Title` → `subgraph "Multi Word Title"`
    code = re.sub(
        r'(?m)^(\s*subgraph\s+)(?!")([^\[\n"]*\s[^\[\n"]*?)\s*$',
        lambda m: f'{m.group(1)}"{m.group(2).strip()}"',
        code,
    )

    # Edge labels |text| — strip characters that break the parser.
    code = re.sub(
        r"\|([^|\n]*)\|",
        lambda m: "|" + re.sub(r"\s{2,}", " ", re.sub(r"[()\[\]{}\"]", " ", m.group(1))).strip() + "|",
        code,
    )

    # Ensure a graph directive on the first non-empty line.
    first = next((ln for ln in code.splitlines() if ln.strip()), "")
    if not re.match(r"^\s*(graph|flowchart|sequenceDiagram|classDiagram|erDiagram|stateDiagram)", first):
        code = "graph TD\n" + code

    return code.strip()
