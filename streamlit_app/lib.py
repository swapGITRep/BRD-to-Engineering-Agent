"""
streamlit_app/lib.py
─────────────────────────────────────────────────────────────────────────────
Shared helpers for the Streamlit UI: path setup, theme, session state,
pipeline execution, sidebar, and render utilities used across views.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st
import yaml

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SAMPLE_DIR = ROOT / "data" / "sample_brds"
LLM_CONFIG_PATH = ROOT / "config" / "llm_config.yaml"
REPORT_DIR = ROOT / "output" / "reports"
PARSED_DIR = ROOT / "output" / "parsed"
EVAL_DIR = ROOT / "output" / "eval"

APP_NAME = "Charter"
APP_TAGLINE = "Turns a Business Requirements Document into a scored, build-ready delivery plan."
APP_ICON = "🧭"

# Pipeline stages, in order, for the progress tracker.
STAGES: List[tuple[str, str]] = [
    ("ingest", "Ingest"),
    ("orchestrate", "Orchestrate"),
    ("engineering_plan", "Plan"),
    ("schedule", "Schedule"),
    ("architecture", "Architecture"),
    ("poc", "PoC"),
    ("tech_stack", "Tech stack"),
    ("critique", "Critic"),
    ("assemble", "Assemble"),
    ("complete", "Complete"),
]
_STAGE_ORDER = {name: i for i, (name, _) in enumerate(STAGES)}

BADGE_ICON = {"green": "🟢", "amber": "🟡", "red": "🔴"}
BADGE_HEX = {"green": "#16a34a", "amber": "#d97706", "red": "#dc2626"}

DELIVERABLES: List[tuple[str, str]] = [
    ("engineering_plan", "Engineering Plan"),
    ("schedule", "Schedule & Estimates"),
    ("architecture", "Solution Architecture"),
    ("poc_plan", "Proof-of-Concept Plan"),
    ("tech_stack", "Technology Stack Options"),
]

# agent state-key → (display name, llm_config agent name used by get_llm)
AGENT_LLM_NAMES: List[tuple[str, str, str]] = [
    ("brd_ingest", "BRD Ingest & Parse", "brd_ingest"),
    ("orchestrator", "Orchestrator", "orchestrator"),
    ("engineering_plan", "Engineering Plan Generator", "engineering_plan_generator"),
    ("schedule", "Schedule Estimator", "schedule_estimator"),
    ("architecture", "Solution Architect", "solution_architect"),
    ("poc_plan", "PoC Planner", "poc_planner"),
    ("tech_stack", "Tech Stack Recommender", "tech_stack_recommender"),
    ("critic", "Critic", "critic"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Theme
# ─────────────────────────────────────────────────────────────────────────────
def inject_css() -> None:
    st.markdown(
        """
        <style>
          /* Brand accent + header tokens. base/light values on bare :root, dark
             overrides only under prefers-color-scheme so the app follows the
             OS/browser setting -- no [theme] block in config.toml, since even
             just setting primaryColor there disables Streamlit's own automatic
             light/dark switching (live-verified against Streamlit 1.64). The
             accent itself is reasserted below on stBaseButton-primary, since
             Streamlit's native theme has no accent color without that config
             key. */
          :root {
            --accent:#4f46e5; --accent-2:#7c6cf6;
            --header-bg:#ffffff; --header-border:rgba(15,23,42,0.08);
            --header-title:#0f172a; --header-tagline:#64748b; --header-sep:#cbd5e1;
          }
          @media (prefers-color-scheme: dark) {
            :root {
              --header-bg:#262730; --header-border:rgba(255,255,255,0.08);
              --header-title:#fafafa; --header-tagline:#9ca3af; --header-sep:#4b5563;
            }
          }
          [data-testid="stBaseButton-primary"] {
            background-color: var(--accent); border-color: var(--accent); color: #ffffff;
          }
          [data-testid="stBaseButton-primary"]:hover {
            background-color: var(--accent-2); border-color: var(--accent-2); color: #ffffff;
          }
          /* Reserve space so the fixed header/footer bars never cover content. */
          .block-container { padding-top: 7.5rem; padding-bottom: 6rem; max-width: 1180px; }
          section[data-testid="stSidebar"] > div { padding-top: 7.5rem; padding-bottom: 6rem; }
          @media (max-width: 680px) {
            .block-container { padding-top: 7rem; padding-bottom: 5rem; }
            section[data-testid="stSidebar"] > div { padding-top: 7rem; padding-bottom: 5rem; }
          }
          h1, h2, h3 { letter-spacing: -0.01em; }
          [data-testid="stMetric"] {
            background: rgba(128,128,128,0.06);
            border: 1px solid rgba(128,128,128,0.14);
            border-radius: 12px; padding: 14px 16px;
          }
          [data-testid="stMetricLabel"] { opacity: 0.7; font-size: 0.8rem; }
          section[data-testid="stSidebar"] { border-right: 1px solid rgba(128,128,128,0.14); }
          .pill {
            display:inline-block; padding:2px 10px; border-radius:999px;
            font-size:0.75rem; font-weight:600; border:1px solid currentColor;
          }
          .kb-card {
            border:1px solid rgba(128,128,128,0.16); border-radius:12px;
            padding:14px 16px; margin-bottom:10px;
          }
          .stepper { display:flex; gap:4px; flex-wrap:wrap; }
          .step {
            flex:1 1 88px; min-width:88px; text-align:center; font-size:0.72rem;
            padding:8px 4px; border-radius:9px; border:1px solid rgba(128,128,128,0.16);
          }
          .step .dot { font-size:1rem; display:block; margin-bottom:2px; }
          .step.done { border-color:#16a34a55; background:#16a34a12; }
          .step.active { border-color:var(--accent); background:#4f46e518; font-weight:600; }
          .step.err { border-color:#dc262655; background:#dc262612; }

          /* Fixed header bar — pinned to the top of the viewport, above the sidebar too.
             Colors come from the --header-* tokens above (light by default, dark
             under prefers-color-scheme), so this bar follows the OS/browser
             theme instead of clashing with it. z-index is above Streamlit's own
             header (999990) AND its mobile sidebar overlay (999991) so the bar
             stays on top when the sidebar drawer is opened on narrow screens.
             A single compact row (icon badge + name + tagline) reads as a real app
             top bar rather than a stacked banner. */
          .app-header-fixed {
            position: fixed; top: 60px; left: 0; right: 0; z-index: 1000000;
            height: 52px; display: flex; align-items: center;
            background: var(--header-bg);
            padding: 0 1.5rem;
            border-bottom: 1px solid var(--header-border);
            box-shadow: 0 1px 3px rgba(15,23,42,0.05);
          }
          .app-header-inner {
            display: flex; align-items: center; gap: 10px;
            width: 100%; max-width: 1180px; margin: 0 auto;
            overflow: hidden; white-space: nowrap;
          }
          .app-header-badge {
            flex: none; display: inline-flex; align-items: center; justify-content: center;
            width: 30px; height: 30px; border-radius: 8px;
            background: linear-gradient(135deg, var(--accent), var(--accent-2));
            box-shadow: 0 1px 2px rgba(79,70,229,0.4);
            font-size: 1rem; line-height: 1;
          }
          .app-header-title { flex: none; font-size: 1.05rem; font-weight: 800; letter-spacing:-0.01em; color:var(--header-title); }
          .app-header-sep { flex: none; color: var(--header-sep); }
          .app-header-tagline {
            font-size:0.85rem; color:var(--header-tagline); font-weight: 400;
            overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
          }
          @media (max-width: 680px) {
            .app-header-sep, .app-header-tagline { display: none; }
          }

          /* Fixed footer bar — pinned to the bottom of the viewport, above the sidebar too.
             The agent/model line is dropped on narrow screens (kept only in the
             sidebar-free desktop layout) so the bar's height stays small and
             predictable instead of growing unbounded as it line-wraps; the
             max-height + hidden overflow below is a hard backstop either way. */
          .app-footer {
            position: fixed; bottom: 0; left: 0; right: 0; z-index: 1000000;
            background: #1e1b3a;
            padding: 8px 1.25rem 10px;
            border-top: 1px solid rgba(0,0,0,0.2);
            font-size:0.75rem; color:#cbd5e1; line-height:1.5;
            max-height: 6.5rem; overflow: hidden;
          }
          .app-footer b { color:#f1f5f9; }
          .app-footer-build { color:#8b87b8; font-family: monospace; }
          @media (max-width: 680px) {
            .app-footer-agents { display: none; }
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────────────
def init_state() -> None:
    st.session_state.setdefault("brd_result", None)
    st.session_state.setdefault("brd_running", False)
    st.session_state.setdefault("active_job_id", None)
    st.session_state.setdefault("progress_dialog_open", True)
    if "run_history" not in st.session_state:
        # Session state resets on every restart; seed the "recent runs" list
        # from the on-disk manifests so it survives restarts too.
        st.session_state.run_history = [
            {"brd_id": m.get("brd_id", ""), "current_stage": "complete",
             "quality_badges": m.get("quality_badges", {})}
            for m in reversed(list_run_manifests())
        ]


def result() -> Optional[Dict[str, Any]]:
    return st.session_state.get("brd_result")


def require_result() -> Optional[Dict[str, Any]]:
    res = result()
    if not res:
        st.info("No analysis yet — run one from **BRD Upload**.")
        st.page_link("views/upload.py", label="Go to BRD Upload", icon="📤")
        return None
    return res


# ─────────────────────────────────────────────────────────────────────────────
# Model configuration (read-only display)
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _llm_config() -> Dict[str, Any]:
    try:
        return yaml.safe_load(LLM_CONFIG_PATH.read_text()) or {}
    except Exception:  # noqa: BLE001
        return {}


def rag_chunk_config() -> tuple[int, int]:
    """(chunk_tokens, chunk_overlap) exactly as RagRetriever reads them, so a
    KB preview can mirror the retriever's real chunk boundaries."""
    cfg = _llm_config().get("rag", {})
    return int(cfg.get("chunk_tokens", 800)), int(cfg.get("chunk_overlap", 100))


def agent_model_rows() -> List[Dict[str, str]]:
    from skills.llm_factory import resolve_llm_params

    cfg = _llm_config()
    rows = []
    for _key, display, llm_name in AGENT_LLM_NAMES:
        p = resolve_llm_params(llm_name, cfg)
        rows.append({"Agent": display, "Model": p["model"], "Temp": f"{p['temperature']:g}"})
    return rows


def api_key_present() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def langsmith_status() -> tuple[bool, bool, str]:
    """(key_ok, tracing_on, project) — mirrors the detection logic in
    orchestration.langgraph_workflow._configure_langsmith() read-only, so the
    sidebar can show accurate status without importing that (heavy, agent-
    loading) module just to render a pill before any run has happened."""
    api_key = os.environ.get("LANGCHAIN_API_KEY") or os.environ.get("LANGSMITH_API_KEY") or ""
    key_ok = bool(api_key.strip()) and api_key.strip().lower() not in ("not-set", "changeme", "none")
    if not key_ok:
        return False, False, ""
    tracing = (os.environ.get("LANGCHAIN_TRACING_V2") or os.environ.get("LANGSMITH_TRACING") or "true").lower()
    tracing_on = tracing in ("true", "1", "yes")
    project = os.environ.get("LANGCHAIN_PROJECT") or os.environ.get("LANGSMITH_PROJECT") or "brd-dev-agent"
    return key_ok, tracing_on, project


def jira_status() -> tuple[bool, str]:
    """(configured, project) for the PoC Planner's check_related_jira_tickets
    tool. Mirrors skills.jira_tickets._config()'s "site + email + token all
    set" check, read-only and duplicated here rather than imported — same
    reasoning as langsmith_status(): the sidebar renders before any run and
    shouldn't need to reach into an agent-adjacent module just for a pill.
    Keep this in sync if _config()'s required fields ever change."""
    site  = os.environ.get("JIRA_SITE_URL", "").strip()
    email = os.environ.get("JIRA_EMAIL", "").strip()
    token = os.environ.get("JIRA_API_TOKEN", "").strip()
    configured = bool(site and email and token) and token.lower() not in ("not-set", "changeme", "none")
    return configured, os.environ.get("JIRA_PROJECT", "").strip()


# ─────────────────────────────────────────────────────────────────────────────
# App header / footer (rendered once per page, around st.navigation)
# ─────────────────────────────────────────────────────────────────────────────
def render_app_header() -> None:
    st.markdown(
        "<div class='app-header-fixed'><div class='app-header-inner'>"
        f"<span class='app-header-badge'>{APP_ICON}</span>"
        f"<span class='app-header-title'>{APP_NAME}</span>"
        "<span class='app-header-sep'>·</span>"
        f"<span class='app-header-tagline'>{APP_TAGLINE}</span>"
        "</div></div>",
        unsafe_allow_html=True,
    )


def app_build() -> str:
    """Deployed build/revision label: the image tag we set as APP_BUILD at
    deploy time, falling back to the Azure Container Apps auto-injected
    revision name, then to "local" for a laptop run."""
    return (
        os.environ.get("APP_BUILD")
        or os.environ.get("CONTAINER_APP_REVISION")
        or "local"
    )


def render_app_footer() -> None:
    import datetime as _dt

    agents = " · ".join(f"<b>{r['Agent']}</b> ({r['Model']})" for r in agent_model_rows())
    year = _dt.datetime.now().year
    st.markdown(
        "<div class='app-footer'>"
        f"<div class='app-footer-agents'><b>Agents &amp; models</b> — {agents}</div>"
        f"<div style='margin-top:4px'>© {year} {APP_NAME}. Internal engineering tool — "
        "built with LangGraph, Retrieval-Augmented Generation, and OpenAI. Not for external distribution. "
        f"<span class='app-footer-build'>Build {app_build()}</span>"
        "</div></div>",
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────
def render_sidebar_footer() -> None:
    with st.sidebar:
        st.divider()
        ok = api_key_present()
        st.markdown(
            f"<span class='pill' style='color:{'#16a34a' if ok else '#dc2626'}'>"
            f"{'●' if ok else '○'} OPENAI_API_KEY {'detected' if ok else 'missing'}</span>",
            unsafe_allow_html=True,
        )
        if not ok:
            st.caption("Add it to `.env` and restart.")

        key_ok, tracing_on, project = langsmith_status()
        if key_ok and tracing_on:
            ls_color, ls_dot, ls_text = "#16a34a", "●", f"LangSmith tracing ON — {project}"
        elif key_ok:
            ls_color, ls_dot, ls_text = "#d97706", "●", "LangSmith key detected, tracing OFF"
        else:
            ls_color, ls_dot, ls_text = "#6b7280", "○", "LangSmith not configured"
        st.markdown(
            f"<span class='pill' style='color:{ls_color};margin-top:6px'>{ls_dot} {ls_text}</span>",
            unsafe_allow_html=True,
        )
        if not key_ok:
            st.caption("Optional — add `LANGCHAIN_API_KEY` to `.env` to enable tracing.")
        elif not tracing_on:
            st.caption("Set `LANGCHAIN_TRACING_V2=true` in `.env` to enable it.")

        jira_ok, jira_project = jira_status()
        if jira_ok:
            jira_color, jira_dot = "#16a34a", "●"
            jira_text = f"Jira ticket check ON — {jira_project}" if jira_project else "Jira ticket check ON — unscoped"
        else:
            jira_color, jira_dot, jira_text = "#6b7280", "○", "Jira ticket check not configured"
        st.markdown(
            f"<span class='pill' style='color:{jira_color};margin-top:6px'>{jira_dot} {jira_text}</span>",
            unsafe_allow_html=True,
        )
        if not jira_ok:
            st.caption("Optional — add `JIRA_SITE_URL`/`JIRA_EMAIL`/`JIRA_API_TOKEN` to `.env` to enable it.")

        hist = st.session_state.get("run_history", [])
        if hist:
            st.divider()
            st.markdown(f"**Recent runs** ({len(hist)})")
            for r in reversed(hist[-6:]):
                b = r.get("quality_badges", {}).get("_overall", "—")
                st.caption(f"{BADGE_ICON.get(b, '⚪')} `{r.get('brd_id', '?')}` — {r.get('current_stage', '?')}")


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline execution
# ─────────────────────────────────────────────────────────────────────────────
def _derive_brd_id(name: str) -> str:
    """A readable, filesystem/id-safe brd_id from an original filename or label."""
    import re as _re

    stem = Path(name).stem
    slug = _re.sub(r"[^A-Za-z0-9]+", "_", stem).strip("_").upper()[:48]
    return slug or "BRD"


_TITLE_LINE_RE = re.compile(r"^#{1,6}\s*(.+)$")
# This project's house style opens every BRD with the same boilerplate title
# ("# Business Requirements Document — <the actual title>") -- strip it so
# the derived id reflects the distinctive part, not the same prefix on every
# pasted BRD.
_BOILERPLATE_TITLE_RE = re.compile(r"^business requirements document\s*[—\-:]*\s*", re.IGNORECASE)


def _derive_brd_id_from_text(text: str) -> str:
    """A readable brd_id from pasted text's first heading/line, for the one
    entry path _derive_brd_id() can't cover -- pasted text has no filename to
    slugify, so brd_id previously stayed empty and fell through to
    run_pipeline()'s random `BRD-<hex>` fallback every time. Deliberately not
    routed through _derive_brd_id() itself: that uses Path(name).stem, which
    would silently truncate a title containing "." (e.g. "v2.0") by treating
    everything after the last dot as a fake file extension.

    Returns "" (not "BRD") when no usable title line exists, so callers can
    tell "nothing to derive from" apart from "derived, happens to be short" —
    and the empty string preserves the existing random-fallback behavior for
    text with no heading, rather than colliding every such run onto "BRD"."""
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        m = _TITLE_LINE_RE.match(line)
        title = m.group(1).strip() if m else line
        title = _BOILERPLATE_TITLE_RE.sub("", title).strip()
        slug = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_").upper()[:48]
        return slug
    return ""


MAX_UPLOAD_BYTES = 15 * 1024 * 1024   # 15 MB — generous for a text-based BRD
MIN_BRD_CHARS = 200                    # below this it isn't a real requirements document


def run_analysis(*, uploaded_file=None, pasted_text: str = "", sample_name: str = "") -> bool:
    """Start the pipeline as a background job. Returns True if a job was started.

    The run executes in a daemon thread (see streamlit_app/jobs.py), so this
    call returns immediately — it does not block the script, and navigating
    away afterward cannot cancel or lose the run. Progress is picked up by
    render_job_watcher() on any page, in any session.

    Validates before ever starting the background job — a size cap, a content
    floor, and (for .docx/.pdf) actually extracting the text with the same
    load_document() the real pipeline uses, so a validation pass here is a
    guarantee the pipeline can read the file too, not a separate, looser
    check that can diverge from what ingestion actually does.
    """
    import streamlit_app.jobs as jobs
    from skills.brd_parser import load_document

    if not api_key_present():
        st.error("`OPENAI_API_KEY` is not set. Add it to `.env` and restart the app.")
        return False

    brd_path, brd_text, brd_id = "", "", ""
    if uploaded_file is not None:
        if uploaded_file.size == 0:
            st.error("That file is empty.")
            return False
        if uploaded_file.size > MAX_UPLOAD_BYTES:
            st.error(f"That file is {uploaded_file.size / (1024 * 1024):.1f} MB — the limit for "
                     f"a BRD upload is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
            return False

        brd_id = _derive_brd_id(uploaded_file.name)
        suffix = Path(uploaded_file.name).suffix.lower()
        if suffix in (".md", ".txt"):
            brd_text = uploaded_file.getvalue().decode("utf-8", errors="replace")
            if len(brd_text.strip()) < MIN_BRD_CHARS:
                st.error(f"That file has only {len(brd_text.strip())} characters of content — "
                         f"too little to be a real BRD (need at least {MIN_BRD_CHARS}).")
                return False
        else:
            # Keep the id derived from the real filename — a tempfile's random
            # name would otherwise become the brd_id (e.g. "TMP2HZ0PN4R").
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            tmp.write(uploaded_file.getvalue())
            tmp.close()
            try:
                extracted = load_document(tmp.name)
            except Exception as e:  # noqa: BLE001 - surface as a clear upload error, not a job crash
                st.error(f"Couldn't read that {suffix} file: {e}")
                os.unlink(tmp.name)
                return False
            if len(extracted.strip()) < MIN_BRD_CHARS:
                st.error(f"That file has only {len(extracted.strip())} characters of extractable "
                         f"text — too little to be a real BRD (need at least {MIN_BRD_CHARS}).")
                os.unlink(tmp.name)
                return False
            brd_path = tmp.name
    elif sample_name:
        brd_path = str(SAMPLE_DIR / sample_name)
        brd_id = _derive_brd_id(sample_name)
    elif pasted_text.strip():
        if len(pasted_text.strip()) < MIN_BRD_CHARS:
            st.error(f"That's only {len(pasted_text.strip())} characters — too little to be a "
                     f"real BRD (need at least {MIN_BRD_CHARS}).")
            return False
        brd_text = pasted_text
        brd_id = _derive_brd_id_from_text(pasted_text)

    if not brd_path and not brd_text:
        st.error("Provide a BRD: upload a file, pick a sample, or paste text.")
        return False

    job_id = jobs.start_job(brd_path=brd_path, brd_text=brd_text, brd_id=brd_id)
    st.session_state.active_job_id = job_id
    st.session_state.brd_running = True
    st.session_state.progress_dialog_open = True
    st.toast(f"Started — running in the background as `{brd_id or job_id}`. "
             "Feel free to navigate around; progress shows on Dashboard.", icon="🚀")
    return True


def _elapsed_str(started_at: Optional[str]) -> str:
    from datetime import datetime, timezone

    if not started_at:
        return "—"
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return "—"
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    secs = max(int((datetime.now(timezone.utc) - started).total_seconds()), 0)
    mins, secs = divmod(secs, 60)
    return f"{mins}m {secs:02d}s"


def _close_progress_dialog() -> None:
    st.session_state.progress_dialog_open = False


@st.dialog("Analysis in progress", width="large", icon="🧭", on_dismiss=_close_progress_dialog)
def _progress_dialog(job: Dict[str, Any]) -> None:
    """The overlay shown while a job runs: current stage, a progress bar,
    elapsed time, and the full stepper — refreshed every 2s via its own
    st.rerun(). Dismissible: closing it just switches to the slim inline
    banner in render_job_watcher(), it does not stop or hide the run."""
    import time

    import streamlit_app.jobs as jobs

    stage = jobs.live_stage(job)
    stage_label = dict(STAGES).get(stage, (stage or "starting").replace("_", " ").title())
    idx = _STAGE_ORDER.get(stage, 0)
    label = job.get("brd_id") or job.get("job_id", "")

    st.markdown(f"**{label}**")
    st.progress(min((idx + 1) / len(STAGES), 1.0), text=f"Step {idx + 1} of {len(STAGES)} — {stage_label}")

    c1, c2 = st.columns(2)
    c1.metric("Elapsed", _elapsed_str(job.get("started_at")))
    c2.metric("Current stage", stage_label)

    render_stage_tracker({"current_stage": stage})

    st.caption(
        "Typically takes 8–10 minutes. You can close this dialog and browse "
        "other pages — the analysis keeps running in the background regardless."
    )
    time.sleep(2)
    st.rerun()


def render_job_watcher(auto_refresh: bool = True) -> bool:
    """Show live progress for the in-flight job (this session's, or any other
    session's/tab's — job state lives on disk, not in st.session_state).

    While running, shows a modal overlay (st.dialog) with the current stage,
    a progress bar, elapsed time, and the full stepper — refreshed every 2s.
    Dismissing it (or clicking away) swaps in a slim one-line banner with a
    "View progress" button, so browsing other pages never re-traps the user
    behind the modal; the run itself is unaffected either way.

    Auto-loads the result into brd_result the moment a watched job completes.
    Returns True while a job is running (callers use this to disable inputs).
    """
    import streamlit_app.jobs as jobs

    job_id = st.session_state.get("active_job_id")
    if not job_id:
        lj = jobs.latest_job()
        if lj and lj.get("status") == "running":
            job_id = lj["job_id"]
            st.session_state.active_job_id = job_id

    if not job_id:
        return False

    job = jobs.get_job(job_id)
    if not job:
        st.session_state.active_job_id = None
        return False

    if job.get("status") == "running":
        if auto_refresh and st.session_state.get("progress_dialog_open", True):
            _progress_dialog(job)
        else:
            stage = jobs.live_stage(job)
            stage_label = dict(STAGES).get(stage, (stage or "starting").replace("_", " ").title())
            label = job.get("brd_id") or job_id
            c1, c2 = st.columns([5, 1])
            c1.info(f"🔄 **Analysis running** — `{label}` · {stage_label}. Safe to browse other pages.")
            if c2.button("View progress", key="reopen_progress_dialog"):
                st.session_state.progress_dialog_open = True
                st.rerun()
        return True

    # Job just finished (this rerun is the first to see it) — resolve it.
    st.session_state.brd_running = False
    st.session_state.active_job_id = None
    if job.get("status") == "complete":
        loaded = load_historical_run(job.get("brd_id", ""))
        if loaded:
            st.session_state.brd_result = loaded
            st.session_state.run_history.append(loaded)
            ob = job.get("overall_badge", "—")
            st.success(f"✅ Analysis complete — overall readiness {BADGE_ICON.get(ob, '⚪')} {ob}")
    else:
        st.error(f"❌ Analysis failed: {job.get('error') or 'unknown error'}")
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Render helpers
# ─────────────────────────────────────────────────────────────────────────────
def render_stage_tracker(res: Optional[Dict[str, Any]]) -> None:
    cur = str((res or {}).get("current_stage", ""))
    cur_idx = _STAGE_ORDER.get(cur, -1)
    failed = cur == "failed"
    complete = cur == "complete"

    html = ["<div class='stepper'>"]
    for name, label in STAGES:
        idx = _STAGE_ORDER[name]
        if failed:
            cls, dot = ("err", "🟥") if idx <= 1 else ("", "⬜")
        elif complete or idx < cur_idx:
            cls, dot = "done", "✅"
        elif idx == cur_idx:
            cls, dot = "active", "🔄"
        else:
            cls, dot = "", "⬜"
        html.append(f"<div class='step {cls}'><span class='dot'>{dot}</span>{label}</div>")
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)

    errs = (res or {}).get("errors") or []
    if errs:
        with st.expander(f"⚠️ {len(errs)} pipeline error(s)"):
            for e in errs:
                st.code(e, language="text")


def overall_badge_banner(res: Dict[str, Any]) -> None:
    ob = res.get("quality_badges", {}).get("_overall", "—")
    hexc = BADGE_HEX.get(ob, "#6b7280")
    st.markdown(
        f"<div style='display:flex;align-items:center;gap:10px;margin:2px 0 10px'>"
        f"<span style='width:12px;height:12px;border-radius:50%;background:{hexc};display:inline-block'></span>"
        f"<span style='font-size:1.05rem;font-weight:700'>Overall readiness: {ob.upper()}</span></div>",
        unsafe_allow_html=True,
    )


def scorecard_df(res: Dict[str, Any]):
    scores = res.get("critic_scores", {})
    badges = res.get("quality_badges", {})
    return [
        {
            "Deliverable": title,
            "Badge": f"{BADGE_ICON.get(badges.get(key, ''), '⚪')} {badges.get(key, '—')}",
            "Overall": round(s["overall"], 2) if (s := scores.get(key)) else None,
            "Complete": round(s["completeness"], 2) if s else None,
            "Consistent": round(s["consistency"], 2) if s else None,
            "Actionable": round(s["actionability"], 2) if s else None,
            "Grounded": round(s["groundedness"], 2) if s else None,
            "Revs": (s or {}).get("scored_revision"),
        }
        for key, title in DELIVERABLES
    ]


def render_mermaid(code: str, height: int = 460) -> None:
    import json as _json

    import streamlit.components.v1 as components

    from skills.mermaid_utils import sanitize_mermaid

    clean = sanitize_mermaid(code or "")
    src = _json.dumps(clean)
    html = """
<div id="wrap"></div>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>
<script>
(function(){
  var src = %s;
  function fail(msg){
    document.getElementById('wrap').innerHTML =
      '<div style="background:#fff5f5;border:1px solid #fca5a5;border-radius:6px;padding:10px;'
      + 'font:12px/1.5 ui-monospace,monospace;white-space:pre-wrap">'
      + '&#9888; ' + msg + '\\n\\n' + src.replace(/</g,'&lt;') + '</div>';
  }
  function go(){
    try {
      mermaid.initialize({startOnLoad:false, theme:'default', securityLevel:'loose'});
      mermaid.render('m'+Date.now(), src)
        .then(function(r){ document.getElementById('wrap').innerHTML = r.svg; })
        .catch(function(e){ fail((e && (e.message || e.str)) || 'parse error'); });
    } catch(e){ fail((e && e.message) || String(e)); }
  }
  if (window.mermaid) { go(); }
  else {
    var t = setInterval(function(){ if (window.mermaid){ clearInterval(t); go(); } }, 60);
    setTimeout(function(){ if (!window.mermaid){ clearInterval(t); fail('mermaid.js failed to load'); } }, 6000);
  }
})();
</script>
""" % src
    components.html(html, height=height, scrolling=True)
    with st.expander("Diagram source"):
        st.code(clean, language="mermaid")


# ─────────────────────────────────────────────────────────────────────────────
# Run history (backed by output/reports/<brd_id>_manifest.json)
# ─────────────────────────────────────────────────────────────────────────────
def list_run_manifests() -> List[Dict[str, Any]]:
    """All past runs with an assembled report, newest first."""
    if not REPORT_DIR.exists():
        return []
    runs = []
    for p in REPORT_DIR.glob("*_manifest.json"):
        try:
            runs.append(json.loads(p.read_text()))
        except Exception:  # noqa: BLE001 - a corrupt manifest shouldn't break the list
            continue
    runs.sort(key=lambda r: r.get("generated_at", ""), reverse=True)
    return runs


def load_historical_run(brd_id: str) -> Optional[Dict[str, Any]]:
    """Reconstruct a viewable result dict for a past run from its saved files."""
    manifest_path = REPORT_DIR / f"{brd_id}_manifest.json"
    deliverables_path = REPORT_DIR / f"{brd_id}_deliverables.json"
    if not manifest_path.exists() or not deliverables_path.exists():
        return None

    manifest = json.loads(manifest_path.read_text())
    deliverables = json.loads(deliverables_path.read_text())

    doc_path = REPORT_DIR / f"{brd_id}_response.md"
    doc = doc_path.read_text(encoding="utf-8") if doc_path.exists() else ""

    sections, requirements, metadata = [], [], {"project_name": manifest.get("project_name", "")}
    parsed_path = PARSED_DIR / f"{brd_id}_parsed.json"
    if parsed_path.exists():
        try:
            parsed = json.loads(parsed_path.read_text())
            sections = parsed.get("sections", [])
            requirements = parsed.get("requirements", [])
            metadata = parsed.get("metadata", metadata)
        except Exception:  # noqa: BLE001
            pass

    return {
        "brd_id": brd_id,
        "thread_id": manifest.get("thread_id", ""),
        "brd_summary": manifest.get("brd_summary", ""),
        "brd_metadata": metadata,
        "brd_sections": sections,
        "requirements": requirements,
        "critic_scores": manifest.get("critic_scores", {}),
        "quality_badges": manifest.get("quality_badges", {}),
        "revision_counts": manifest.get("revision_counts", {}),
        "confidentiality_notes": manifest.get("confidentiality_notes", []),
        "errors": manifest.get("errors", []),
        "brd_response_doc": doc,
        "current_stage": "complete",
        "current_step": "loaded_from_history",
        **{k: deliverables.get(k) for k, _ in DELIVERABLES},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Eval runs (backed by output/eval/<run_id>/summary.json)
# ─────────────────────────────────────────────────────────────────────────────
def list_eval_runs() -> List[Dict[str, Any]]:
    """All scripts/run_eval.py runs with a summary.json, newest first.

    A run_id is a sortable UTC timestamp (YYYYmmddTHHMMSSZ), so sorting by
    folder name descending is newest-first -- unless --out gave it a custom
    name, in which case this is best-effort rather than a hard guarantee."""
    if not EVAL_DIR.exists():
        return []
    runs = []
    for p in sorted(EVAL_DIR.glob("*/summary.json"), reverse=True):
        try:
            data = json.loads(p.read_text())
            data.setdefault("run_id", p.parent.name)
            runs.append(data)
        except Exception:  # noqa: BLE001 - a corrupt summary shouldn't break the list
            continue
    return runs
