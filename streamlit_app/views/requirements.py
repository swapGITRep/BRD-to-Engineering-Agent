"""Parsed Requirements — metadata, classified requirements, sections."""
from __future__ import annotations

import streamlit as st

from streamlit_app.lib import require_result

st.title("Parsed Requirements")


def render() -> None:
    res = require_result()
    if not res:
        return

    meta = res.get("brd_metadata", {})
    st.subheader(meta.get("project_name") or res.get("brd_id"))
    st.write(res.get("brd_summary", ""))

    reqs = res.get("requirements", [])
    secs = res.get("brd_sections", [])
    m = st.columns(3)
    m[0].metric("Sections", len(secs))
    m[1].metric("Requirements", len(reqs))
    m[2].metric("Ambiguous", sum(1 for r in reqs if r.get("ambiguity_flag")))

    st.divider()

    with st.expander("Metadata", expanded=True):
        a, b = st.columns(2)
        a.markdown("**Stakeholders**"); a.write(meta.get("stakeholders") or "—")
        a.markdown("**Business goals**"); a.write(meta.get("business_goals") or "—")
        a.markdown("**Success metrics**"); a.write(meta.get("success_metrics") or "—")
        b.markdown("**Target dates**"); b.write(meta.get("target_dates") or "—")
        b.markdown("**Referenced systems**"); b.write(meta.get("referenced_systems") or "—")
        b.markdown("**Glossary**"); b.write(meta.get("glossary") or "—")

    st.subheader("Requirements")
    if reqs:
        types = sorted({r.get("type", "functional") for r in reqs})
        f1, f2 = st.columns([3, 1])
        pick = f1.multiselect("Type", types, default=types)
        only_amb = f2.toggle("Ambiguous only")
        rows = [
            {"ID": r.get("req_id"), "Section": r.get("section_id"), "Type": r.get("type"),
             "NFR": r.get("nfr_category") or "", "Priority": r.get("priority"),
             "⚠": "yes" if r.get("ambiguity_flag") else "", "Text": r.get("text")}
            for r in reqs
            if r.get("type", "functional") in pick and (not only_amb or r.get("ambiguity_flag"))
        ]
        st.dataframe(rows, hide_index=True, width="stretch")
    else:
        st.info("No requirements were classified.")

    st.subheader("Sections")
    for s in secs:
        with st.expander(f"{s.get('section_id')} · {s.get('title')}  (L{s.get('level')})"):
            st.text(s.get("raw_text", "") or "—")


render()
