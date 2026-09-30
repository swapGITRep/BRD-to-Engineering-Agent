"""BRD Upload — file / sample / paste, then run."""
from __future__ import annotations

import streamlit as st

from streamlit_app.lib import (
    MAX_UPLOAD_BYTES,
    MIN_BRD_CHARS,
    SAMPLE_DIR,
    render_job_watcher,
    render_stage_tracker,
    run_analysis,
)

st.title("BRD Upload")
st.caption("Supported formats: .md · .txt · .docx · .pdf")
st.caption(
    f"Guardrails: up to {MAX_UPLOAD_BYTES // (1024 * 1024)} MB per upload · "
    f"at least {MIN_BRD_CHARS} characters of content · "
    "credentials and PII are scanned and redacted before anything reaches a model"
)

job_active = render_job_watcher()

tab_file, tab_sample, tab_paste = st.tabs(["Upload file", "Sample BRD", "Paste text"])

with tab_file:
    up = st.file_uploader("BRD file", type=["md", "txt", "docx", "pdf"], key="u_file", disabled=job_active)
    if st.button("Run analysis", key="r_file", type="primary", disabled=job_active):
        if run_analysis(uploaded_file=up):
            st.rerun()

with tab_sample:
    samples = sorted(p.name for p in SAMPLE_DIR.glob("*.md"))
    if samples:
        choice = st.radio("Sample BRDs", samples, key="u_sample", disabled=job_active)
        with st.expander("Preview", expanded=False):
            st.markdown((SAMPLE_DIR / choice).read_text())
        if st.button("Run analysis", key="r_sample", type="primary", disabled=job_active):
            if run_analysis(sample_name=choice):
                st.rerun()
    else:
        st.info("No sample BRDs found under `data/sample_brds/`.")

with tab_paste:
    txt = st.text_area("BRD text", height=340, key="u_paste",
                       placeholder="# 1. Overview\n…", disabled=job_active)
    if st.button("Run analysis", key="r_paste", type="primary", disabled=job_active):
        if run_analysis(pasted_text=txt):
            st.rerun()

if not job_active:
    st.divider()
    render_stage_tracker(st.session_state.get("brd_result"))
