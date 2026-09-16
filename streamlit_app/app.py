"""
streamlit_app/app.py
─────────────────────────────────────────────────────────────────────────────
Charter — single entrypoint. Navigation is defined once with st.navigation
(no duplicated auto-discovered pages). A shared header/footer wraps every page.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import streamlit as st

from streamlit_app.lib import APP_ICON, APP_NAME, APP_TAGLINE

st.set_page_config(
    page_title=APP_NAME,
    page_icon=APP_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={"About": f"**{APP_NAME}** — {APP_TAGLINE}"},
)

from streamlit_app.lib import (  # noqa: E402
    init_state, inject_css, render_app_footer, render_app_header, render_sidebar_footer,
)

inject_css()
init_state()
render_app_header()

nav = st.navigation(
    {
        "Analyze": [
            st.Page("views/dashboard.py", title="Dashboard", icon="🏠", default=True),
            st.Page("views/upload.py", title="BRD Upload", icon="📤"),
            st.Page("views/history.py", title="Run History", icon="🕓"),
        ],
        "Results": [
            st.Page("views/requirements.py", title="Parsed Requirements", icon="📑"),
            st.Page("views/deliverables.py", title="Deliverables", icon="📦"),
            st.Page("views/quality.py", title="Quality Report", icon="🏅"),
            st.Page("views/export.py", title="Export", icon="⬇️"),
        ],
    }
)

render_sidebar_footer()
nav.run()
render_app_footer()
