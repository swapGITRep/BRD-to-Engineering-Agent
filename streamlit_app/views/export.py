"""Export — download the assembled response doc and deliverables."""
from __future__ import annotations

import json

import streamlit as st

from streamlit_app.lib import DELIVERABLES, require_result

st.title("Export")


def render() -> None:
    res = require_result()
    if not res:
        return

    brd_id = res.get("brd_id", "brd")
    doc = res.get("brd_response_doc", "")

    c = st.columns(3)
    with c[0]:
        st.download_button("⬇️ Response document (.md)", doc or "_(none)_",
                           file_name=f"{brd_id}_response.md", mime="text/markdown",
                           type="primary", disabled=not doc, width="stretch")
    with c[1]:
        st.download_button("⬇️ Deliverables (.json)",
                           json.dumps({k: res.get(k) for k, _ in DELIVERABLES}, indent=2),
                           file_name=f"{brd_id}_deliverables.json", mime="application/json",
                           width="stretch")
    with c[2]:
        st.download_button("⬇️ Parsed BRD (.json)",
                           json.dumps({"brd_id": brd_id, "metadata": res.get("brd_metadata", {}),
                                       "sections": res.get("brd_sections", []),
                                       "requirements": res.get("requirements", [])}, indent=2),
                           file_name=f"{brd_id}_parsed.json", mime="application/json",
                           width="stretch")

    st.caption("Written to disk each run: "
               f"`output/reports/{brd_id}_response.md` · `output/deliverables/*.json` · "
               f"`output/parsed/{brd_id}_parsed.json`")

    if doc:
        st.divider()
        st.subheader("Preview")
        st.markdown(doc)
    else:
        st.warning("No assembled response document — the pipeline did not reach the assemble stage.")


render()
