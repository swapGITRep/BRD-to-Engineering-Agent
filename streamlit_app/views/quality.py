"""Quality Report — Critic scorecards, badges, revision history."""
from __future__ import annotations

import streamlit as st

from streamlit_app.lib import (
    BADGE_ICON, DELIVERABLES, overall_badge_banner, require_result, scorecard_df,
)

st.title("Quality Report")


def render() -> None:
    res = require_result()
    if not res:
        return

    overall_badge_banner(res)
    st.caption("green ≥ 0.80 · amber ≥ 0.60 · red < 0.60 — weighted across "
               "completeness, consistency, actionability, groundedness.")

    st.subheader("Scorecard")
    st.dataframe(scorecard_df(res), hide_index=True, width="stretch")

    st.subheader("Per-deliverable detail")
    scores = res.get("critic_scores", {})
    badges = res.get("quality_badges", {})
    counts = res.get("revision_counts", {})

    for key, title in DELIVERABLES:
        s = scores.get(key)
        label = (f"{BADGE_ICON.get(badges.get(key, ''), '⚪')} {title} — "
                 f"{('%.2f' % s['overall']) if s else 'not scored'} · {counts.get(key, 0)} revision(s)")
        with st.expander(label):
            if not s:
                st.write("No Critic score recorded.")
                continue
            cols = st.columns(4)
            for col, dim in zip(cols, ("completeness", "consistency", "actionability", "groundedness")):
                col.progress(min(1.0, float(s[dim])), text=f"{dim.title()} {s[dim]:.2f}")
            st.write(f"**Verdict:** `{s['verdict']}`")
            if s.get("issues"):
                st.markdown("**Issues raised**")
                for i in s["issues"]:
                    st.markdown(f"- {i}")
            else:
                st.success("No open issues.")

    if res.get("errors"):
        st.subheader("Run errors")
        for e in res["errors"]:
            st.code(e, language="text")


render()
