"""Deterministic R9-0 probe — debug profile rerank without LLM or scheduler.

uv run python examples/episodic_rerank_probe.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dream.tools._context import ToolExecutionContext

from chorus.heartbeat import BeatContext
from chorus.memory import EpisodicStore, SprintDelta
from chorus.memory._recall_service import EpisodicRecallService
from chorus_tools._recall import RecallTool


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _body(text: str) -> str:
    return json.dumps({"kind": "role.text", "role": "generator", "text": text})


def _delta(**over: object) -> SprintDelta:
    now = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
    base: dict[str, object] = dict(
        run_id="r_1",
        task_id="t_1",
        employee_id="bex",
        scope="project",
        intent="slugify",
        outcome="done",
        score=1.0,
        created_at=now,
        role="backend_engineer",
        recorded_at=now,
        body=_body("slugify"),
    )
    base.update(over)
    return SprintDelta(**base)  # type: ignore[arg-type]


async def _run_checks() -> list[tuple[str, bool, str]]:
    tmp = Path(tempfile.mkdtemp(prefix="chorus-rerank-probe-"))
    store = EpisodicStore(tmp / "memory")
    now = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
    store.append(
        _delta(
            run_id="r_fail",
            outcome="needs_changes",
            intent="slugify regression",
            body=_body("slugify regression failed"),
            recorded_at=now - timedelta(days=3),
        )
    )
    store.append(
        _delta(
            run_id="r_ok",
            outcome="done",
            intent="slugify works",
            body=_body("slugify works"),
            recorded_at=now - timedelta(days=1),
        )
    )
    work = tmp / "work"
    work.mkdir()
    BeatContext(task_id="t_probe", run_id="r_probe", employee_id="bex").write(work)
    ctx = ToolExecutionContext(working_dir=work, session_id="probe")
    tool = RecallTool(EpisodicRecallService(store))

    debug_result = await tool.execute({"query": "slugify regression", "profile": "debug"}, ctx)
    debug_struct = debug_result.structured or {}
    debug_top = debug_struct.get("hits", [{}])[0] if debug_struct.get("hits") else {}
    debug_ok = (
        debug_result.is_error is False
        and debug_struct.get("profile") == "debug"
        and debug_top.get("outcome") == "needs_changes"
        and debug_top.get("run_id") == "r_fail"
    )

    general_result = await tool.execute({"query": "slugify", "profile": "general"}, ctx)
    general_struct = general_result.structured or {}
    general_top = general_struct.get("hits", [{}])[0] if general_struct.get("hits") else {}
    general_ok = (
        general_result.is_error is False
        and general_struct.get("profile") == "general"
        and general_top.get("run_id") == "r_ok"
    )

    refuse_result = await tool.execute({"profile": "debug"}, ctx)
    refuse_ok = refuse_result.is_error is True and "task_id" in refuse_result.content.lower()

    task_result = await tool.execute({"task_id": "t_1", "profile": "debug"}, ctx)
    task_struct = task_result.structured or {}
    task_ids = [hit.get("run_id") for hit in task_struct.get("hits", [])]
    task_ok = task_result.is_error is False and task_ids[0] == "r_fail"

    return [
        ("debug query promotes failure", debug_ok, str(debug_top.get("run_id", "?"))),
        ("general query keeps recent done", general_ok, str(general_top.get("run_id", "?"))),
        ("debug without scope refused", refuse_ok, refuse_result.content[:60]),
        ("debug task thread failure first", task_ok, str(task_ids)),
    ]


def main() -> int:
    import asyncio

    checks = asyncio.run(_run_checks())
    _log("=" * 60)
    _log("EPISODIC RERANK PROBE (R9-0)")
    _log("=" * 60)
    all_ok = True
    for name, ok, detail in checks:
        _log(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")
        all_ok = all_ok and ok
    report = Path(__file__).resolve().parent.parent / "reports" / "episodic-rerank-probe.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(
            {"checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks]}, indent=2
        ),
        encoding="utf-8",
    )
    _log(f"\nreport: {report}")
    _log(f"\n{'ALL CHECKS PASS' if all_ok else 'SOME CHECKS FAILED'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
