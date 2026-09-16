"""tests/test_mermaid_utils.py — sanitize_mermaid."""
from __future__ import annotations

from skills.mermaid_utils import sanitize_mermaid


def test_quotes_parenthesised_label():
    out = sanitize_mermaid("graph TD; A[Web Client (SPA)]-->|HTTP|B[BFF]")
    assert 'A["Web Client (SPA)"]' in out
    assert "|HTTP|" in out


def test_quotes_label_with_colon():
    out = sanitize_mermaid("graph LR\n A[User] --> D[Login: retry]")
    assert 'D["Login: retry"]' in out


def test_leaves_clean_labels_alone():
    src = "graph TD\n A[User] --> B[Dashboard]"
    assert sanitize_mermaid(src) == src


def test_strips_parens_from_edge_labels():
    out = sanitize_mermaid("graph TD\n A -->|Sync (REST)| B[svc]")
    assert "(REST)" not in out
    assert "|Sync REST|" in out


def test_does_not_double_quote():
    out = sanitize_mermaid('graph TD\n A["already quoted (x)"] --> B[y]')
    assert out.count('"already quoted') == 1


def test_prepends_directive_when_missing():
    out = sanitize_mermaid("A[x] --> B[y]")
    assert out.startswith("graph TD")


def test_empty_input_gives_placeholder():
    assert "No diagram" in sanitize_mermaid("")


def test_strips_code_fences():
    out = sanitize_mermaid("```mermaid\ngraph TD\n A[x]-->B[y]\n```")
    assert "```" not in out


def test_strips_trailing_semicolon_on_directive():
    out = sanitize_mermaid("graph TD;\n A[x]-->B[y]")
    assert out.splitlines()[0] == "graph TD"


def test_quotes_multiword_subgraph_title():
    out = sanitize_mermaid("graph TD\n subgraph Design System\n H[Lib]\n end")
    assert 'subgraph "Design System"' in out


def test_single_word_subgraph_untouched():
    src = "graph TD\n subgraph Core\n H[Lib]\n end"
    assert 'subgraph "Core"' not in sanitize_mermaid(src)
