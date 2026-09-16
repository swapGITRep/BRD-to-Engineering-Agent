#!/usr/bin/env python3
"""
scripts/run_eval.py
─────────────────────────────────────────────────────────────────────────────
Runs the full BRD pipeline across the labeled evaluation set
(data/eval_brds/labels.yaml) and reports, per BRD:
  - whether the pipeline reached the stage its label expects
  - Critic scores per agent (completeness/consistency/actionability/
    groundedness/overall) and the resulting quality badges
  - revision improvement — the actual before/after score for every artifact
    that was revised (not just a count), plus an aggregate average change
    across the whole set, both in the summary and in summary.json
  - whether the ingestion agent found at least as many requirements, and
    flagged at least as many as ambiguous, as the label expects

This is a real functional check, not just a smoke test: `expect` failures
(pipeline didn't complete, too few requirements, ambiguity wasn't flagged)
make the run exit non-zero, so this is CI-usable on any prompt/config change.
Quality scores and badges are reported but never pass/fail this script on
their own — a lower score is data about the system, not a bug in it.

Usage:
    python scripts/run_eval.py                          # the whole set
    python scripts/run_eval.py --only AMBIGUOUS_ANALYTICS,CONFLICTING_NFRS
    python scripts/run_eval.py --labels path/to/other_labels.yaml

Results land under output/eval/<run_id>/ — one JSON per BRD plus summary.md
and summary.json. Compare two run_ids' summary.json for real before/after
evidence across a prompt or config change.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import yaml

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from orchestration.state import SPECIALIST_AGENTS, Stage, revision_improvement  # noqa: E402

logger = logging.getLogger("run_eval")


def _plain(value: Any) -> Any:
    """orchestration.state's enums (Stage, Badge, ...) are (str, Enum): str()
    on one invokes Enum.__str__ and returns "Stage.COMPLETE", not the plain
    value "complete", even though the object IS a string for equality
    purposes. Prefer .value so reports read cleanly (see the identical fix
    in streamlit_app/jobs.py::_stage_str)."""
    return value.value if hasattr(value, "value") else value


def load_labels(path: Path) -> List[Dict[str, Any]]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def check_expectations(entry: Dict[str, Any], final: Dict[str, Any]) -> List[str]:
    """Return a list of failed-expectation strings (empty = all passed)."""
    expect = entry.get("expect", {}) or {}
    failures = []

    stage = final.get("current_stage")
    want_complete = expect.get("expect_complete", True)
    is_complete = stage == Stage.COMPLETE
    if want_complete and not is_complete:
        failures.append(f"expected pipeline to complete, got stage={_plain(stage)}")
    if not want_complete and is_complete:
        failures.append("expected pipeline NOT to complete, but it did")

    reqs = final.get("requirements", []) or []
    if "min_requirements" in expect and len(reqs) < expect["min_requirements"]:
        failures.append(f"expected >= {expect['min_requirements']} requirements, got {len(reqs)}")

    if "min_ambiguous" in expect:
        n_ambig = sum(1 for r in reqs if r.get("ambiguity_flag"))
        if n_ambig < expect["min_ambiguous"]:
            failures.append(f"expected >= {expect['min_ambiguous']} ambiguity-flagged requirements, got {n_ambig}")

    return failures


def summarize_agents(final: Dict[str, Any]) -> Dict[str, Any]:
    scores = final.get("critic_scores", {}) or {}
    revisions = final.get("revision_counts", {}) or {}
    badges = final.get("quality_badges", {}) or {}
    out = {}
    for agent in SPECIALIST_AGENTS:
        art = final.get(agent) or {}
        s = scores.get(agent, {})
        out[agent] = {
            "status": _plain(art.get("status", "—")),
            "badge": _plain(badges.get(agent, "—")),
            "revisions": revisions.get(agent, 0),
            "overall": s.get("overall"),
            "completeness": s.get("completeness"),
            "consistency": s.get("consistency"),
            "actionability": s.get("actionability"),
            "groundedness": s.get("groundedness"),
        }
    return out


def run_one(entry: Dict[str, Any], brd_config_path: str, llm_config_path: str) -> Dict[str, Any]:
    from orchestration.langgraph_workflow import run_pipeline  # lazy: heavy import, needs API key

    brd_id = entry["brd_id"]
    brd_path = str(PROJECT_ROOT / entry["file"])
    thread_id = str(uuid.uuid4())

    logger.info("▶ %-28s (%s)", brd_id, entry.get("category", "?"))
    t0 = time.monotonic()
    try:
        final = run_pipeline(
            brd_path=brd_path, brd_id=brd_id, thread_id=thread_id,
            brd_config_path=brd_config_path, llm_config_path=llm_config_path,
        )
        error = None
    except Exception as e:  # noqa: BLE001 - one bad run must not abort the whole eval set
        logger.error("✗ %s crashed: %s", brd_id, e)
        final = {"current_stage": "crashed", "requirements": []}
        error = str(e)
    elapsed = round(time.monotonic() - t0, 1)

    failures = check_expectations(entry, final) if error is None else [f"pipeline crashed: {error}"]
    result = {
        "brd_id": brd_id,
        "category": entry.get("category"),
        "tests": entry.get("tests", "").strip(),
        "elapsed_seconds": elapsed,
        "stage": _plain(final.get("current_stage")),
        "requirement_count": len(final.get("requirements", []) or []),
        "ambiguous_count": sum(1 for r in (final.get("requirements", []) or []) if r.get("ambiguity_flag")),
        "overall_badge": _plain((final.get("quality_badges", {}) or {}).get("_overall", "—")),
        "agents": summarize_agents(final),
        "revision_improvement": revision_improvement(final.get("score_history", {}) or {}),
        "expectation_failures": failures,
        "error": error,
    }

    status = "✓" if not failures else "✗"
    logger.info("%s %-28s stage=%-10s reqs=%-3d ambiguous=%-3d badge=%-6s (%ss)",
                status, brd_id, result["stage"], result["requirement_count"],
                result["ambiguous_count"], result["overall_badge"], elapsed)
    if failures:
        for f in failures:
            logger.warning("    expectation failed: %s", f)

    return result


def write_summary(results: List[Dict[str, Any]], out_dir: Path) -> None:
    total = len(results)
    passed = sum(1 for r in results if not r["expectation_failures"])

    lines = [
        f"# Eval run — {out_dir.name}",
        "",
        f"{passed}/{total} BRDs met their expectations.",
        "",
        "| BRD | Category | Stage | Reqs | Ambig. | Overall badge | Expectations |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        exp = "✓" if not r["expectation_failures"] else f"✗ ({len(r['expectation_failures'])})"
        lines.append(
            f"| {r['brd_id']} | {r['category']} | {r['stage']} | {r['requirement_count']} | "
            f"{r['ambiguous_count']} | {r['overall_badge']} | {exp} |"
        )

    lines += ["", "## Per-agent scores", "",
              "| BRD | Agent | Badge | Revisions | Overall | Completeness | Consistency | Actionability | Groundedness |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        for agent, a in r["agents"].items():
            def fmt(v):
                return "—" if v is None else f"{v:.2f}"
            lines.append(
                f"| {r['brd_id']} | {agent} | {a['badge']} | {a['revisions']} | {fmt(a['overall'])} | "
                f"{fmt(a['completeness'])} | {fmt(a['consistency'])} | {fmt(a['actionability'])} | {fmt(a['groundedness'])} |"
            )

    # Revision improvement — the concrete before/after evidence for the whole
    # set: not just "the loop ran N times" but what it actually moved.
    all_deltas: List[Dict[str, Any]] = []
    for r in results:
        for agent, d in r["revision_improvement"].items():
            all_deltas.append({"brd_id": r["brd_id"], "agent": agent, **d})

    lines += ["", "## Revision improvement", ""]
    if all_deltas:
        avg_delta = sum(d["delta"] for d in all_deltas) / len(all_deltas)
        total_revisions = sum(d["revisions"] for d in all_deltas)
        improved = sum(1 for d in all_deltas if d["delta"] > 0)
        lines += [
            f"{len(all_deltas)} artifact(s) revised across the set — {total_revisions} total revision(s), "
            f"{improved}/{len(all_deltas)} improved, average change **{avg_delta:+.3f}**.",
            "",
            "| BRD | Agent | Revisions | Before | After | Change |",
            "|---|---|---|---|---|---|",
        ]
        for d in all_deltas:
            lines.append(
                f"| {d['brd_id']} | {d['agent']} | {d['revisions']} | {d['first_overall']:.2f} | "
                f"{d['last_overall']:.2f} | {d['delta']:+.2f} |"
            )
    else:
        lines.append("No artifact needed a revision in this run — every deliverable passed on its first score.")

    failed = [r for r in results if r["expectation_failures"]]
    if failed:
        lines += ["", "## Expectation failures", ""]
        for r in failed:
            lines.append(f"- **{r['brd_id']}**: " + "; ".join(r["expectation_failures"]))

    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps({
        "run_id": out_dir.name, "total": total, "passed": passed,
        "revision_improvement": all_deltas, "results": results,
    }, indent=2, default=str), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--labels", default="data/eval_brds/labels.yaml")
    parser.add_argument("--only", default="", help="comma-separated brd_ids to run (default: the whole set)")
    parser.add_argument("--brd-config", default="config/brd_config.yaml")
    parser.add_argument("--llm-config", default="config/llm_config.yaml")
    parser.add_argument("--out", default="", help="output dir (default: output/eval/<timestamp>/)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    labels_path = PROJECT_ROOT / args.labels
    entries = load_labels(labels_path)
    if args.only:
        wanted = {b.strip() for b in args.only.split(",")}
        entries = [e for e in entries if e["brd_id"] in wanted]
        missing = wanted - {e["brd_id"] for e in entries}
        if missing:
            logger.warning("Not found in %s, skipping: %s", labels_path, ", ".join(sorted(missing)))

    if not entries:
        logger.error("No labeled BRDs selected — nothing to run.")
        return 2

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = PROJECT_ROOT / (args.out or f"output/eval/{run_id}")
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Running %d BRD(s) → %s", len(entries), out_dir)
    results = []
    for entry in entries:
        result = run_one(entry, args.brd_config, args.llm_config)
        results.append(result)
        (out_dir / f"{result['brd_id']}.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    write_summary(results, out_dir)

    passed = sum(1 for r in results if not r["expectation_failures"])
    logger.info("=" * 65)
    logger.info("%d/%d passed their expectations — full report: %s", passed, len(results), out_dir / "summary.md")
    logger.info("=" * 65)

    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
