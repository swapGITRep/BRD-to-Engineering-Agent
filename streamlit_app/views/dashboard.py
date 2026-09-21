"""Dashboard — KPIs, pipeline status, quick run."""
from __future__ import annotations

import streamlit as st

from streamlit_app.lib import (
    BADGE_ICON, DELIVERABLES, SAMPLE_DIR,
    overall_badge_banner, render_job_watcher, render_stage_tracker, run_analysis, scorecard_df,
)

st.title("Multi-agent BRD Analysis")
st.caption("Parse a BRD → ground agents in org knowledge (RAG) → generate plan, schedule, "
           "architecture, PoC, and tech-stack options → score and revise.")

job_active = render_job_watcher()

res = st.session_state.get("brd_result")

# ── KPIs ────────────────────────────────────────────────────────────────────
reqs = len(res.get("requirements", [])) if res else 0
delivered = sum(1 for k, _ in DELIVERABLES if res and (res.get(k) or {}).get("status") == "ok") if res else 0
scores = list((res.get("critic_scores", {}) if res else {}).values())
avg_q = f"{sum(s['overall'] for s in scores) / len(scores):.2f}" if scores else "—"
revs = sum((res.get("revision_counts", {}) if res else {}).values())
overall = (res.get("quality_badges", {}) if res else {}).get("_overall", "—")

k = st.columns(5)
k[0].metric("Requirements parsed", reqs)
k[1].metric("Deliverables", f"{delivered} / 5")
k[2].metric("Avg quality", avg_q)
k[3].metric("Revision rounds", revs)
k[4].metric("Overall readiness", f"{BADGE_ICON.get(overall, '⚪')} {overall}")

st.divider()

# ── Pipeline status (the watcher above already shows a live one while a job
#    is running, so this static view only needs to cover the idle state). ───
if not job_active:
    st.subheader("Pipeline")
    render_stage_tracker(res)
    st.divider()

# ── Quick run ───────────────────────────────────────────────────────────────
st.subheader("Quick run")
c1, c2 = st.columns([3, 2])
with c1:
    up = st.file_uploader("Upload a BRD", type=["md", "txt", "docx", "pdf"],
                          key="dash_up", disabled=job_active)
with c2:
    samples = ["— none —"] + sorted(p.name for p in SAMPLE_DIR.glob("*.md"))
    sample = st.selectbox("…or load a sample", samples, key="dash_sample", disabled=job_active)

if st.button("Run analysis", type="primary", disabled=job_active, key="dash_run"):
    if run_analysis(uploaded_file=up, sample_name="" if sample == "— none —" else sample):
        st.rerun()

st.caption("More input options (paste text, sample previews) on the **BRD Upload** page. "
           "Once started, an analysis runs in the background — browse freely while it works.")

# ── Latest run ──────────────────────────────────────────────────────────────
if not job_active and res and res.get("current_stage") != "failed":
    st.divider()
    st.subheader("Latest run")
    st.markdown(f"**{res.get('brd_metadata', {}).get('project_name') or res.get('brd_id')}** — "
                f"{res.get('brd_summary', '')}")
    overall_badge_banner(res)
    st.dataframe(scorecard_df(res), hide_index=True, width="stretch")
    st.page_link("views/deliverables.py", label="Open deliverables", icon="📦")
