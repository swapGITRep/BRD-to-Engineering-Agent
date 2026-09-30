"""Eval Runs — scripts/run_eval.py's own labeled-set results, from output/eval/."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

import streamlit as st

from streamlit_app.lib import BADGE_ICON, list_eval_runs, load_historical_run

st.title("Eval Runs")
st.caption(
    "`scripts/run_eval.py` runs the real pipeline against the labeled set in "
    "`data/eval_brds/labels.yaml` and checks each BRD's actual behavior against "
    "its `expect` block — a different question from Run History's per-run quality "
    "scores. Each BRD it runs *also* leaves a normal entry in Run History; this page "
    "is the eval harness's own pass/fail view of the whole set."
)


def _fmt_run_id(run_id: str) -> str:
    try:
        return datetime.strptime(run_id, "%Y%m%dT%H%M%SZ").strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return run_id


def _render_agents_table(agents: Dict[str, Any]) -> None:
    rows = []
    for agent, a in agents.items():
        def fmt(v):
            return "—" if v is None else f"{v:.2f}"
        rows.append({
            "Agent": agent,
            "Badge": f"{BADGE_ICON.get(a.get('badge', ''), '⚪')} {a.get('badge', '—')}",
            "Revisions": a.get("revisions", 0),
            "Overall": fmt(a.get("overall")),
            "Complete": fmt(a.get("completeness")),
            "Consistent": fmt(a.get("consistency")),
            "Actionable": fmt(a.get("actionability")),
            "Grounded": fmt(a.get("groundedness")),
        })
    st.dataframe(rows, hide_index=True, width="stretch")


def render() -> None:
    runs = list_eval_runs()

    if not runs:
        st.info("No eval runs yet.")
        st.code("python scripts/run_eval.py", language="bash")
        return

    current_id = (st.session_state.get("brd_result") or {}).get("brd_id")

    for run in runs:
        run_id = run.get("run_id", "?")
        total = run.get("total", 0)
        passed = run.get("passed", 0)
        all_passed = passed == total and total > 0

        with st.container(border=True):
            c1, c2 = st.columns([5, 2])
            with c1:
                st.markdown(f"**Eval run** · `{run_id}`")
                st.caption(_fmt_run_id(run_id))
            with c2:
                icon = "🟢" if all_passed else "🔴"
                st.markdown(f"{icon} **{passed}/{total} passed**")

            results = run.get("results", [])
            rows = []
            for r in results:
                exp_failures = r.get("expectation_failures") or []
                rows.append({
                    "BRD": r.get("brd_id"),
                    "Category": r.get("category"),
                    "Stage": r.get("stage"),
                    "Overall badge": f"{BADGE_ICON.get(r.get('overall_badge', ''), '⚪')} {r.get('overall_badge', '—')}",
                    "Reqs": r.get("requirement_count", 0),
                    "Ambiguous": r.get("ambiguous_count", 0),
                    "Elapsed (s)": r.get("elapsed_seconds", "—"),
                    "Expectations": "✓" if not exp_failures else f"✗ ({len(exp_failures)})",
                })
            st.dataframe(rows, hide_index=True, width="stretch")

            failed = [r for r in results if r.get("expectation_failures")]
            if failed:
                with st.expander(f"⚠️ {len(failed)} BRD(s) failed an expectation", expanded=True):
                    for r in failed:
                        st.markdown(f"**{r.get('brd_id')}**")
                        for f in r["expectation_failures"]:
                            st.markdown(f"- {f}")

            with st.expander("Per-agent scores"):
                for r in results:
                    st.markdown(f"**{r.get('brd_id')}**")
                    _render_agents_table(r.get("agents", {}))

            deltas = run.get("revision_improvement", [])
            with st.expander(f"Revision improvement ({len(deltas)} artifact(s) revised)"):
                if deltas:
                    avg_delta = sum(d["delta"] for d in deltas) / len(deltas)
                    improved = sum(1 for d in deltas if d["delta"] > 0)
                    st.caption(
                        f"{improved}/{len(deltas)} improved · average change **{avg_delta:+.3f}**"
                    )
                    st.dataframe(
                        [
                            {"BRD": d["brd_id"], "Agent": d["agent"], "Revisions": d["revisions"],
                             "Before": f"{d['first_overall']:.2f}", "After": f"{d['last_overall']:.2f}",
                             "Change": f"{d['delta']:+.2f}"}
                            for d in deltas
                        ],
                        hide_index=True, width="stretch",
                    )
                else:
                    st.caption("No artifact needed a revision in this run.")

            with st.expander("Load a BRD from this run into the viewer pages"):
                for r in results:
                    brd_id = r.get("brd_id")
                    loadable = load_historical_run(brd_id) is not None
                    lc1, lc2 = st.columns([4, 1])
                    lc1.caption(brd_id)
                    with lc2:
                        if st.button(
                            "Load", key=f"eval_load_{run_id}_{brd_id}",
                            disabled=not loadable or brd_id == current_id,
                            width="stretch",
                        ):
                            loaded = load_historical_run(brd_id)
                            if loaded:
                                st.session_state.brd_result = loaded
                                st.success(f"Loaded {brd_id}")
                                st.rerun()
                    if not loadable:
                        lc1.caption("_(no matching output/reports/ entry — may have failed before assemble)_")


render()
