"""Knowledge Base — browse the corpus and personas that ground every agent."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Tuple

import streamlit as st

from skills import rag_retriever as rag
from streamlit_app.lib import DELIVERABLES, rag_chunk_config, result

st.title("Knowledge Base")
st.caption(
    "The corpus and persona files every agent is grounded in. This page is "
    "read-only — the files below ship inside the deployed image, so an edit "
    "here would need a code change and redeploy to take effect."
)

_DOC_TYPE_LABELS: Dict[str, str] = {
    "template": "Templates",
    "pattern": "Patterns",
    "org_standard": "Org Standards",
    "past_brd": "Past BRDs",
}
_AGENT_NAMES: Dict[str, str] = dict(DELIVERABLES)


def _cited_docs(res: Dict[str, Any] | None) -> Dict[str, List[Tuple[str, str]]]:
    """doc filename -> [(agent display name, chunk ord), ...] cited in the
    current session's run, parsed from each artifact's citations list."""
    if not res:
        return {}
    out: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for agent_key, agent_name in _AGENT_NAMES.items():
        art = res.get(agent_key) or {}
        for ref in art.get("citations", []) or []:
            key = ref.strip().lstrip("[").rstrip("]")
            if key.startswith("KB:"):
                key = key[3:]
            doc, _, ord_ = key.partition("#")
            if doc:
                out[doc].append((agent_name, ord_ or "?"))
    return out


def _weight_callouts(doc_type: str) -> str:
    """'Weighted higher for: Engineering Plan (1.35x), Schedule (1.25x)'."""
    hits = []
    for agent_key, weights in rag.AGENT_DOC_WEIGHTS.items():
        mult = weights.get(doc_type, 1.0)
        if mult > 1.0 and agent_key in _AGENT_NAMES:
            hits.append((mult, _AGENT_NAMES[agent_key]))
    hits.sort(reverse=True)
    if not hits:
        return ""
    return "Weighted higher for: " + ", ".join(f"{name} ({m:g}x)" for m, name in hits)


def _render_doc(path, doc_type: str, chunk_tokens: int, overlap_tokens: int, cited: Dict) -> None:
    text = path.read_text(encoding="utf-8")
    chunks = rag.chunk_text(text, chunk_tokens, overlap_tokens)
    hits = cited.get(path.name, [])

    label = f"📄 {path.name}"
    if hits:
        label += f"  ·  ✅ cited in current run ({len(hits)})"
    with st.expander(label):
        meta_cols = st.columns(3)
        meta_cols[0].caption(f"{len(text):,} chars")
        meta_cols[1].caption(f"{len(chunks)} chunk(s) at {chunk_tokens}/{overlap_tokens} tok")
        callout = _weight_callouts(doc_type)
        if callout:
            meta_cols[2].caption(callout)

        if hits:
            st.success(
                "Cited by: " + ", ".join(f"{name} (chunk #{ord_})" for name, ord_ in hits)
            )

        st.markdown(text)

        if len(chunks) > 1:
            with st.expander(f"Show as {len(chunks)} retrieval chunks"):
                for i, c in enumerate(chunks):
                    st.caption(f"`KB:{path.name}#{i}`")
                    st.text(c)


res = result()
cited = _cited_docs(res)
chunk_tokens, overlap_tokens = rag_chunk_config()

all_files = sorted(rag.CORPUS_DIR.rglob("*.md")) if rag.CORPUS_DIR.is_dir() else []
persona_files = sorted(rag.PERSONA_DIR.glob("*.md")) if rag.PERSONA_DIR.is_dir() else []

m = st.columns(4)
m[0].metric("Corpus docs", len(all_files))
m[1].metric("Personas", len(persona_files))
total_chunks = sum(
    len(rag.chunk_text(p.read_text(encoding="utf-8"), chunk_tokens, overlap_tokens))
    for p in all_files
)
m[2].metric("Total chunks", total_chunks)
m[3].metric("Cited this run", sum(len(v) for v in cited.values()) if res else "—")

st.divider()

query = st.text_input("Filter by filename or content", placeholder="e.g. estimation, tech radar, poc")
query_l = query.strip().lower()

tab_order = ["template", "pattern", "org_standard", "past_brd"]
tabs = st.tabs([_DOC_TYPE_LABELS[t] for t in tab_order] + ["Personas"])

for tab, doc_type in zip(tabs[:-1], tab_order):
    with tab:
        folder = [sub for sub, dt in rag._DOC_TYPES.items() if dt == doc_type][0]
        files = sorted((rag.CORPUS_DIR / folder).glob("*.md"))
        shown = 0
        for path in files:
            if query_l and query_l not in path.name.lower() and query_l not in path.read_text(encoding="utf-8").lower():
                continue
            shown += 1
            _render_doc(path, doc_type, chunk_tokens, overlap_tokens, cited)
        if not files:
            st.info("No documents in this category.")
        elif shown == 0:
            st.info(f"No documents match “{query}”.")

with tabs[-1]:
    st.caption("One persona per specialist agent — the system-prompt voice each draft is written in.")
    persona_agent = {
        "engineering_plan_generator": "Engineering Plan",
        "schedule_estimator": "Schedule & Estimates",
        "solution_architect": "Solution Architecture",
        "poc_planner": "Proof-of-Concept Plan",
        "tech_stack_recommender": "Technology Stack Options",
        "critic": "Critic",
    }
    shown = 0
    for path in persona_files:
        text = path.read_text(encoding="utf-8")
        if query_l and query_l not in path.stem.lower() and query_l not in text.lower():
            continue
        shown += 1
        agent_label = persona_agent.get(path.stem, path.stem)
        with st.expander(f"🎭 {path.name}  ·  used by {agent_label}"):
            st.markdown(text)
    if not persona_files:
        st.info("No persona files found.")
    elif shown == 0:
        st.info(f"No personas match “{query}”.")
