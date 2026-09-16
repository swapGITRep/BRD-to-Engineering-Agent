"""
orchestration/langgraph_workflow.py
─────────────────────────────────────────────────────────────────────────────
LangGraph workflow for the BRD analysis multi-agent pipeline.

    START → brd_ingest → orchestrator → engineering_plan → schedule
          → architecture → poc_plan → tech_stack → critic
                                                     │
                       (critic routes back to the earliest failing
                        specialist; that specialist routes straight
                        back to critic after revising)
                                                     ▼
                                                  assemble → END

  ✅ SqliteSaver checkpointing (resumable per thread_id)
  ✅ Critic-driven revision loop with a per-agent budget
  ✅ Non-blocking: a failed specialist still reaches assemble
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import logging
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import yaml
from dotenv import load_dotenv
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from agents.assemble_agent import assemble_node
from agents.brd_ingest_agent import brd_ingest_node
from agents.critic_agent import critic_node
from agents.engineering_plan_agent import engineering_plan_node
from agents.orchestrator_agent import orchestrator_node
from agents.poc_planner_agent import poc_planner_node
from agents.schedule_estimator_agent import schedule_estimator_node
from agents.solution_architect_agent import solution_architect_node
from agents.tech_stack_agent import tech_stack_node
from orchestration.state import SPECIALIST_AGENTS, BRDState, Stage, make_initial_state

load_dotenv()
logger = logging.getLogger(__name__)


def _configure_langsmith() -> bool:
    """Normalise LangSmith env vars and return whether tracing is active.

    Accepts either the LANGCHAIN_* or LANGSMITH_* spellings; if an API key is
    present we default tracing ON unless it was explicitly disabled.
    """
    api_key = os.environ.get("LANGCHAIN_API_KEY") or os.environ.get("LANGSMITH_API_KEY")
    if not api_key or api_key.strip().lower() in ("", "not-set", "changeme", "none"):
        return False
    os.environ.setdefault("LANGCHAIN_API_KEY", api_key)
    os.environ.setdefault("LANGSMITH_API_KEY", api_key)

    tracing = (os.environ.get("LANGCHAIN_TRACING_V2")
               or os.environ.get("LANGSMITH_TRACING") or "true").lower()
    on = tracing in ("true", "1", "yes")
    os.environ["LANGCHAIN_TRACING_V2"] = "true" if on else "false"
    os.environ["LANGSMITH_TRACING"] = "true" if on else "false"

    project = os.environ.get("LANGCHAIN_PROJECT") or os.environ.get("LANGSMITH_PROJECT") or "brd-dev-agent"
    os.environ["LANGCHAIN_PROJECT"] = project
    os.environ["LANGSMITH_PROJECT"] = project

    endpoint = os.environ.get("LANGCHAIN_ENDPOINT") or os.environ.get("LANGSMITH_ENDPOINT")
    if endpoint:
        os.environ["LANGCHAIN_ENDPOINT"] = endpoint
        os.environ["LANGSMITH_ENDPOINT"] = endpoint
    return on


LANGSMITH_ON = _configure_langsmith()

# Node names (specialist node names == their state keys / agent_plan entries)
N_INGEST   = "brd_ingest"
N_ORCH     = "orchestrator"
N_CRITIC   = "critic"
N_ASSEMBLE = "assemble"

RECURSION_LIMIT = 60   # base ~8 steps + up to (max_revisions * n_specialists) * 2


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
def _load_yaml(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        logger.warning("Config not found: %s", path)
        return {}
    return yaml.safe_load(p.read_text()) or {}


def load_configs(
    brd_config_path: str = "config/brd_config.yaml",
    llm_config_path: str = "config/llm_config.yaml",
) -> Dict[str, Any]:
    cfg = _load_yaml(brd_config_path)
    cfg["_llm_config"] = _load_yaml(llm_config_path)
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# Routers
# ─────────────────────────────────────────────────────────────────────────────
def route_after_ingest(state: BRDState) -> str:
    if state.get("current_stage") == Stage.FAILED:
        logger.error("❌ Ingest failed — aborting pipeline")
        return "__end__"
    return N_ORCH


def route_after_orchestrator(state: BRDState) -> str:
    pending = state.get("pending_revision")
    return pending if pending in SPECIALIST_AGENTS else "engineering_plan"


_STAGE_TO_NEXT = {
    Stage.SCHEDULE:     "schedule",
    Stage.ARCHITECTURE: "architecture",
    Stage.POC:          "poc_plan",
    Stage.TECH_STACK:   "tech_stack",
    Stage.CRITIQUE:     N_CRITIC,
}


def route_after_specialist(state: BRDState) -> str:
    """One router for all five specialists — dispatch purely on current_stage.

    A revision run always lands in Stage.CRITIQUE (set by finish()/fail()), so it
    goes straight back to the Critic; a normal run carries the next stage.
    """
    return _STAGE_TO_NEXT.get(state.get("current_stage"), N_CRITIC)


def route_after_critic(state: BRDState) -> str:
    pending = state.get("pending_revision")
    return pending if pending in SPECIALIST_AGENTS else N_ASSEMBLE


# ─────────────────────────────────────────────────────────────────────────────
# Graph
# ─────────────────────────────────────────────────────────────────────────────
def build_workflow(checkpointer: SqliteSaver | None = None) -> Any:
    g = StateGraph(BRDState)

    g.add_node(N_INGEST, brd_ingest_node)
    g.add_node(N_ORCH, orchestrator_node)
    g.add_node("engineering_plan", engineering_plan_node)
    g.add_node("schedule", schedule_estimator_node)
    g.add_node("architecture", solution_architect_node)
    g.add_node("poc_plan", poc_planner_node)
    g.add_node("tech_stack", tech_stack_node)
    g.add_node(N_CRITIC, critic_node)
    g.add_node(N_ASSEMBLE, assemble_node)

    g.add_edge(START, N_INGEST)
    g.add_conditional_edges(N_INGEST, route_after_ingest, {N_ORCH: N_ORCH, "__end__": END})

    specialist_targets = {
        "engineering_plan": "engineering_plan", "schedule": "schedule",
        "architecture": "architecture", "poc_plan": "poc_plan",
        "tech_stack": "tech_stack", N_CRITIC: N_CRITIC,
    }
    g.add_conditional_edges(N_ORCH, route_after_orchestrator, specialist_targets)
    for node in ("engineering_plan", "schedule", "architecture", "poc_plan", "tech_stack"):
        g.add_conditional_edges(node, route_after_specialist, specialist_targets)

    g.add_conditional_edges(
        N_CRITIC, route_after_critic,
        {**{a: a for a in SPECIALIST_AGENTS}, N_ASSEMBLE: N_ASSEMBLE},
    )
    g.add_edge(N_ASSEMBLE, END)

    return g.compile(checkpointer=checkpointer) if checkpointer else g.compile()


# ─────────────────────────────────────────────────────────────────────────────
# Singleton app
# ─────────────────────────────────────────────────────────────────────────────
# LangGraph's Pregel loop dispatches checkpoint reads/writes from its own
# internal worker thread(s) even within a single synchronous .invoke() call —
# not necessarily the thread that called .invoke(). So the connection can't
# be bound to "the calling thread" (a thread-local connection breaks with
# "SQLite objects created in a thread can only be used in that same thread"
# the moment LangGraph's internal executor touches it from a different
# thread); check_same_thread=False on one shared connection is the pattern
# SqliteSaver is actually designed around. The remaining real hazard is two
# independent top-level operations overlapping on that shared connection —
# the background job thread's .invoke() (writing a checkpoint per node) and
# the Streamlit UI thread's get_thread_state() (polling for live progress) —
# which busy_timeout resolves by retrying instead of failing immediately.
# That retry only works reliably because CHECKPOINT_DB is local container
# disk, not Azure Files: SQLite's locking is unreliable over SMB, where a
# busy_timeout retry has no reliable lock-release signal to wait on.
_app = None
_checkpointer = None


def _get_checkpointer() -> SqliteSaver:
    global _checkpointer
    if _checkpointer is None:
        db_path = os.environ.get("CHECKPOINT_DB", "checkpoints/langgraph_states.db")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
        conn.execute("PRAGMA busy_timeout = 30000")
        _checkpointer = SqliteSaver(conn)
    return _checkpointer


def get_app() -> Any:
    global _app
    if _app is None:
        _app = build_workflow(checkpointer=_get_checkpointer())
        logger.info("✅ BRD workflow compiled with SqliteSaver checkpointing")
    return _app


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────
def run_pipeline(
    brd_path: str = "",
    brd_text: str = "",
    brd_id: str = "",
    thread_id: str = "",
    brd_config_path: str = "config/brd_config.yaml",
    llm_config_path: str = "config/llm_config.yaml",
    resume_thread: bool = False,
    app: Any = None,
) -> BRDState:
    """Run the full BRD analysis pipeline. `app` may be injected for testing."""
    os.makedirs("logs", exist_ok=True)
    log_path = f"logs/brd_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    root = logging.getLogger()
    # Ensure agent INFO logs are actually emitted (Streamlit leaves root at WARNING).
    level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    root.setLevel(min(root.level or level, level))
    fh = logging.FileHandler(log_path)
    fh.setFormatter(fmt)
    root.addHandler(fh)
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
               for h in root.handlers):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)
    logger.info("📝 Run log: %s", log_path)

    framework_config = load_configs(brd_config_path, llm_config_path)
    thread_id = thread_id or str(uuid.uuid4())
    brd_id = brd_id or (Path(brd_path).stem.upper() if brd_path else f"BRD-{uuid.uuid4().hex[:6].upper()}")

    run_config = {"configurable": {"thread_id": thread_id}, "recursion_limit": RECURSION_LIMIT}
    application = app or get_app()

    if resume_thread:
        snap = application.get_state(run_config)
        if snap and snap.values:
            logger.info("🔄 Resuming thread %s from step %s", thread_id, snap.values.get("current_step"))
            return application.invoke(None, run_config)

    initial = make_initial_state(
        brd_id=brd_id, thread_id=thread_id, framework_config=framework_config,
        brd_path=brd_path, brd_raw_text=brd_text,
    )

    logger.info("=" * 65)
    logger.info("🚀 BRD PIPELINE START — %s (thread %s)", brd_id, thread_id)
    logger.info("   LangSmith tracing: %s%s", "ON" if LANGSMITH_ON else "OFF",
                f" (project={os.environ.get('LANGCHAIN_PROJECT')})" if LANGSMITH_ON else "")
    logger.info("=" * 65)

    final = application.invoke(initial, run_config)

    if LANGSMITH_ON:
        try:
            from langchain_core.tracers.langchain import wait_for_all_tracers
            wait_for_all_tracers()
        except Exception:  # noqa: BLE001
            pass

    logger.info("=" * 65)
    logger.info("🏁 PIPELINE COMPLETE — stage=%s", final.get("current_stage"))
    for agent in SPECIALIST_AGENTS:
        art = final.get(agent) or {}
        badge = final.get("quality_badges", {}).get(agent, "—")
        logger.info("   %-18s %-8s badge=%s rev=%s", agent, art.get("status", "—"), badge, art.get("revision", 0))
    logger.info("   overall badge : %s", final.get("quality_badges", {}).get("_overall", "—"))
    logger.info("   errors        : %d", len(final.get("errors", [])))
    logger.info("=" * 65)
    return final


def get_thread_state(thread_id: str) -> BRDState | None:
    try:
        snap = get_app().get_state({"configurable": {"thread_id": thread_id}})
        return snap.values if snap else None
    except Exception:  # noqa: BLE001
        return None


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    brd_file = sys.argv[1] if len(sys.argv) > 1 else "data/sample_brds/payments_reconciliation_brd.md"
    tid = sys.argv[2] if len(sys.argv) > 2 else ""

    result = run_pipeline(brd_path=brd_file, thread_id=tid or "", resume_thread=bool(tid))
    print(f"\n✅ Done — stage: {result.get('current_stage')}")
    print(f"   Overall badge: {result.get('quality_badges', {}).get('_overall', 'N/A')}")
    print(f"   Report: output/reports/{result.get('brd_id')}_response.md")
    print(f"   Thread: {result.get('thread_id')}")
