"""Deliverables — one tab per specialist output."""
from __future__ import annotations

import json

import streamlit as st

from streamlit_app.lib import BADGE_ICON, DELIVERABLES, render_mermaid, require_result

st.title("Deliverables")


def render() -> None:
    res = require_result()
    if not res:
        return

    badges = res.get("quality_badges", {})
    scores = res.get("critic_scores", {})

    tabs = st.tabs([f"{BADGE_ICON.get(badges.get(k, ''), '⚪')} {title}" for k, title in DELIVERABLES])

    for tab, (key, title) in zip(tabs, DELIVERABLES):
        with tab:
            art = res.get(key)
            if not art or art.get("status") != "ok":
                st.error("Not produced — the agent failed. See the Quality Report and run errors.")
                continue

            s = scores.get(key)
            if s:
                c = st.columns(5)
                c[0].metric("Overall", f"{s['overall']:.2f}")
                c[1].metric("Complete", f"{s['completeness']:.2f}")
                c[2].metric("Consistent", f"{s['consistency']:.2f}")
                c[3].metric("Actionable", f"{s['actionability']:.2f}")
                c[4].metric("Grounded", f"{s['groundedness']:.2f}")
                if s.get("issues") and badges.get(key) != "green":
                    st.warning("**Open Critic notes**\n\n" + "\n".join(f"- {i}" for i in s["issues"]))

            content = art.get("content", {})

            if key == "architecture" and content.get("mermaid"):
                st.markdown("##### Architecture diagram")
                render_mermaid(str(content["mermaid"]))

            if key == "engineering_plan" and art.get("self_review"):
                with st.expander("🪞 Reflection self-review"):
                    st.json(art["self_review"])

            st.markdown("##### Structured content")
            st.json(content)

            if art.get("citations"):
                st.caption("Grounding: " + " · ".join(f"`{c}`" for c in art["citations"]))

            st.download_button(
                f"Download {key}.json", json.dumps(art, indent=2),
                file_name=f"{res.get('brd_id')}_{key}.json", mime="application/json",
                key=f"dl_{key}",
            )


render()
