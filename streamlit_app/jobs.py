"""
streamlit_app/jobs.py
─────────────────────────────────────────────────────────────────────────────
Background job runner for the BRD pipeline.

Decouples pipeline execution from any single Streamlit script run: clicking
"Run analysis" starts run_pipeline() in a daemon thread and returns
immediately. Job bookkeeping lives in small JSON files under output/jobs/,
not in st.session_state — so navigating away, refreshing, or closing the
browser tab never loses progress. Any session (this one or a fresh one) can
poll a job's status and adopt it. Live in-progress stage comes from
LangGraph's own SqliteSaver checkpoint for the run's thread_id — no need to
duplicate progress tracking.

Limitation: a job's thread lives only as long as this Streamlit process. A
full app/process restart (not just a page/tab event) does end in-flight
jobs — this is a background thread within one process, not an external task
queue. That trade-off is deliberate: it fixes the bug class we actually hit
(a long-running script getting cancelled by navigation) without the cost of
standing up a real queue/worker for a single-instance internal tool.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

JOBS_DIR = Path(__file__).parent.parent / "output" / "jobs"


# ─────────────────────────────────────────────────────────────────────────────
# Storage — atomic writes so a concurrent read never sees a half-written file
# ─────────────────────────────────────────────────────────────────────────────
def _path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def _write(job_id: str, data: Dict[str, Any]) -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path(job_id).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(_path(job_id))  # atomic on POSIX and Windows (py3.3+)


def _read(job_id: str) -> Dict[str, Any]:
    p = _path(job_id)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a mid-write read glitch shouldn't crash the UI
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Background execution
# ─────────────────────────────────────────────────────────────────────────────
def _run(job_id: str, brd_path: str, brd_text: str, brd_id: str, thread_id: str) -> None:
    from orchestration.langgraph_workflow import run_pipeline

    started_at = _read(job_id).get("started_at")
    try:
        res = run_pipeline(brd_path=brd_path, brd_text=brd_text, brd_id=brd_id, thread_id=thread_id)
        failed = res.get("current_stage") == "failed"
        _write(job_id, {
            "job_id": job_id, "thread_id": thread_id,
            "brd_id": res.get("brd_id", brd_id),
            "project_name": (res.get("brd_metadata") or {}).get("project_name", ""),
            "status": "failed" if failed else "complete",
            "current_stage": _stage_str(res.get("current_stage", "")),
            "overall_badge": res.get("quality_badges", {}).get("_overall", "—"),
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "error": "Pipeline failed during ingestion." if failed else None,
        })
    except Exception as e:  # noqa: BLE001 - must not let the thread die silently
        _write(job_id, {
            "job_id": job_id, "thread_id": thread_id, "brd_id": brd_id,
            "project_name": "",
            "status": "failed",
            "current_stage": "failed",
            "overall_badge": "—",
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "error": f"{e}\n\n{traceback.format_exc(limit=6)}",
        })


def start_job(*, brd_path: str = "", brd_text: str = "", brd_id: str = "") -> str:
    """Kick off a pipeline run in the background. Returns a job_id immediately."""
    job_id = uuid.uuid4().hex[:12]
    thread_id = str(uuid.uuid4())
    _write(job_id, {
        "job_id": job_id, "thread_id": thread_id, "brd_id": brd_id,
        "project_name": "",
        "status": "running",
        "current_stage": "ingest",
        "overall_badge": "—",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "error": None,
    })
    threading.Thread(
        target=_run, args=(job_id, brd_path, brd_text, brd_id, thread_id), daemon=True,
    ).start()
    return job_id


# ─────────────────────────────────────────────────────────────────────────────
# Status
# ─────────────────────────────────────────────────────────────────────────────
def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    data = _read(job_id)
    return data or None


def _stage_str(value: Any) -> str:
    """orchestration.state.Stage is a (str, Enum): equality/hashing against
    plain strings like "ingest" works fine, but str(Stage.INGEST) invokes
    Enum.__str__ and returns "Stage.INGEST" rather than the plain value —
    the str mixin doesn't win over Enum's own __str__ override. Callers here
    need the plain value (to match STAGES/_STAGE_ORDER keys in lib.py), so
    prefer .value when present."""
    return value.value if hasattr(value, "value") else str(value)


def live_stage(job: Dict[str, Any]) -> str:
    """Best-effort *current* stage for a running job, read from LangGraph's own
    checkpoint for that thread — no separate progress-tracking needed."""
    if job.get("status") != "running":
        return job.get("current_stage", "")
    thread_id = job.get("thread_id")
    if not thread_id:
        return job.get("current_stage", "")
    try:
        from orchestration.langgraph_workflow import get_thread_state
        state = get_thread_state(thread_id)
        if state and state.get("current_stage"):
            return _stage_str(state["current_stage"])
    except Exception:  # noqa: BLE001 - live progress is best-effort
        pass
    return job.get("current_stage", "")


def latest_job() -> Optional[Dict[str, Any]]:
    """The most recently started job on disk, or None."""
    if not JOBS_DIR.exists():
        return None
    files = sorted(JOBS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data:
                return data
        except Exception:  # noqa: BLE001
            continue
    return None
