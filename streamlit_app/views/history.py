"""Run History — browse and reload past BRD analyses from output/reports/."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from streamlit_app.lib import BADGE_ICON, list_run_manifests, load_historical_run

st.title("Run History")
st.caption("Every completed run leaves `<brd_id>_manifest.json`, `_response.md`, and "
           "`_deliverables.json` under `output/reports/` — this page lists them and can "
           "reload one into the viewer pages below.")


def render() -> None:
    runs = list_run_manifests()

    if not runs:
        st.info("No completed runs yet. Run one from **BRD Upload**.")
        st.page_link("views/upload.py", label="Go to BRD Upload", icon="📤")
        return

    current_id = (st.session_state.get("brd_result") or {}).get("brd_id")

    for run in runs:
        brd_id = run.get("brd_id", "?")
        overall = run.get("quality_badges", {}).get("_overall", "—")
        when = run.get("generated_at", "")
        try:
            when_fmt = datetime.fromisoformat(when.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M UTC")
        except ValueError:
            when_fmt = when

        with st.container(border=True):
            c1, c2, c3 = st.columns([5, 2, 1])
            with c1:
                title = run.get("project_name") or brd_id
                suffix = "  •  *currently loaded*" if brd_id == current_id else ""
                st.markdown(f"**{title}**{suffix}")
                st.caption(f"`{brd_id}` · {when_fmt} · "
                           f"{run.get('section_count', 0)} sections · {run.get('requirement_count', 0)} requirements")
                summary = run.get("brd_summary", "")
                if summary:
                    st.caption(summary)
            with c2:
                st.markdown(f"{BADGE_ICON.get(overall, '⚪')} **{str(overall).upper()}**")
                revs = sum(run.get("revision_counts", {}).values())
                st.caption(f"{revs} revision(s)")
            with c3:
                if st.button("Load", key=f"load_{brd_id}", disabled=(brd_id == current_id), width="stretch"):
                    loaded = load_historical_run(brd_id)
                    if loaded:
                        st.session_state.brd_result = loaded
                        st.success(f"Loaded {brd_id}")
                        st.rerun()
                    else:
                        st.error("Could not load this run — its report files are incomplete.")


render()
