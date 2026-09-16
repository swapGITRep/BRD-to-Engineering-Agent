#!/usr/bin/env python3
"""
scripts/patch_streamlit_index.py
─────────────────────────────────────────────────────────────────────────────
Streamlit serves one static index.html (shipped inside the installed
streamlit package) before any of our Python or JS runs. st.set_page_config()
only sets document.title client-side, after the React app boots — so a
link-preview bot (Slack, Teams, WhatsApp, iMessage, LinkedIn) that fetches
the raw HTML without executing JavaScript never sees it. It sees Streamlit's
own default <title>Streamlit</title> and no description or Open Graph tags
at all — which is exactly what shows up when the deployed URL is pasted
somewhere.

This patches that static file in place (idempotent — checks a marker before
writing, safe to re-run) so the raw HTML itself already carries the real app
name, description, and Open Graph / Twitter Card meta tags. Run once at
image-build time (see Dockerfile) and by run.sh for local parity.

APP_NAME/APP_TAGLINE are duplicated from streamlit_app/lib.py on purpose:
this script runs standalone at build time, and importing the Streamlit app
module here would also import its @st.dialog-decorated functions, which
expect an active Streamlit script run rather than a bare python invocation.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import re
from pathlib import Path

import streamlit

APP_NAME = "Charter"
APP_TAGLINE = "Turns a Business Requirements Document into a scored, build-ready delivery plan."

MARKER = "<!-- charter:meta -->"

META_BLOCK = f"""{MARKER}
    <title>{APP_NAME} — BRD to Delivery Plan</title>
    <meta name="description" content="{APP_TAGLINE}" />
    <meta property="og:type" content="website" />
    <meta property="og:site_name" content="{APP_NAME}" />
    <meta property="og:title" content="{APP_NAME}" />
    <meta property="og:description" content="{APP_TAGLINE}" />
    <meta property="og:image" content="./favicon.png" />
    <meta name="twitter:card" content="summary" />
    <meta name="twitter:title" content="{APP_NAME}" />
    <meta name="twitter:description" content="{APP_TAGLINE}" />
"""


def main() -> None:
    index_path = Path(streamlit.__file__).parent / "static" / "index.html"
    html = index_path.read_text(encoding="utf-8")

    if MARKER in html:
        print(f"[patch_streamlit_index] already patched: {index_path}")
        return

    if "<title>" not in html:
        raise SystemExit(
            f"[patch_streamlit_index] no <title> tag found in {index_path} — "
            "Streamlit's static template may have changed shape"
        )

    html = re.sub(r"[ \t]*<title>.*?</title>[ \t]*\n", "    " + META_BLOCK, html, count=1, flags=re.DOTALL)
    index_path.write_text(html, encoding="utf-8")
    print(f"[patch_streamlit_index] patched: {index_path}")


if __name__ == "__main__":
    main()
