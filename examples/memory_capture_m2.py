"""M2 memory capture, keyed end-to-end: a real engineer beat lands one episodic sprint delta.

Proves spec 07 §3 with a **real** dream beat: run one Engineer beat through the kernel with an
``EpisodicStore`` injected, then verify that exactly one provenance-stamped ``sprint_delta``
record landed under the project scope — and that **dream's own scanner** reads it back (the
``MemoryWriter`` / ``MemoryStore`` contract holds). Emits an HTML verification report.

Run keyed:  AZURE_OPENAI_API_KEY=… AZURE_OPENAI_BASE_URL=… AZURE_OPENAI_DEPLOYMENT=… \
            uv run python examples/memory_capture_m2.py
"""

from __future__ import annotations

import asyncio
import html
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from dream.memory._scan import scan_memory_dir

from chorus.budgets import BudgetEnforcer
from chorus.heartbeat import Scheduler
from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.lifecycle import assign_task
from chorus.memory import EpisodicStore
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee, LedgerWorkforce
from chorus_cli._beats import default_pricing_from_env
from chorus_employee import default_landers
from chorus_harness import EmployeeHarnessFactory

_TASK = (
    "In calc.py add a function subtract(a, b) that returns a - b. In test_calc.py add a test "
    "test_subtract asserting subtract(3, 1) == 2. Keep the existing add function and its test."
)
_REPORT = Path(__file__).resolve().parents[1] / "reports" / "m2-memory-capture-report.html"


def _log(msg: str) -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _seed_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (path / "test_calc.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n", encoding="utf-8"
    )
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.name=s", "-c", "user.email=s@x", "commit", "-m", "init"],
        check=True,
        capture_output=True,
    )


def _write_report(checks: list[tuple[str, bool, str]], record_text: str) -> None:
    rows = "\n".join(
        f'<tr><td>{html.escape(name)}</td><td class="{"ok" if ok else "bad"}">'
        f'{"PASS" if ok else "FAIL"}</td><td>{html.escape(detail)}</td></tr>'
        for name, ok, detail in checks
    )
    verdict = "ALL CHECKS PASS" if all(ok for _, ok, _ in checks) else "FAILURES PRESENT"
    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Chorus M2 Memory Capture Verification</title><style>
:root{{--bg:#f5f7fb;--panel:#fff;--ink:#17202a;--muted:#5f6b7a;--ok:#0a7a34;--bad:#b42318;--line:#d7deea;--accent:#0b5cab}}
body{{margin:0;background:radial-gradient(circle at top right,#dbeafe 0,var(--bg) 45%);color:var(--ink);font-family:Segoe UI,Tahoma,Arial,sans-serif;line-height:1.4}}
main{{max-width:980px;margin:24px auto;padding:0 16px 32px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin-bottom:14px;box-shadow:0 8px 24px rgba(24,39,75,.06)}}
h1{{font-size:24px;margin:0 0 10px}}h2{{font-size:18px;color:var(--accent);margin:0 0 10px}}
table{{width:100%;border-collapse:collapse;margin-top:8px;font-size:14px}}
th,td{{text-align:left;border-bottom:1px solid var(--line);padding:8px 6px;vertical-align:top}}
th{{color:var(--muted);font-weight:600}}.ok{{color:var(--ok);font-weight:700}}.bad{{color:var(--bad);font-weight:700}}
pre{{background:#0f172a;color:#dbeafe;padding:12px;border-radius:10px;overflow-x:auto;font-size:12px}}
.meta{{color:var(--muted);font-size:13px}}</style></head><body><main>
<div class="card"><h1>Chorus M2 — Memory Capture Verification</h1>
<p class="meta">spec 07 §3 · one append-only episodic <code>sprint_delta</code> per beat, with provenance,
read back by dream's own scanner.</p>
<p><strong class="{"ok" if verdict.startswith("ALL") else "bad"}">{verdict}</strong></p></div>
<div class="card"><h2>Scenario</h2><p>Run one real Engineer beat (add <code>subtract</code> + a test)
through the kernel with an <code>EpisodicStore</code> injected; verify the captured memory record.</p></div>
<div class="card"><h2>Checks</h2><table><tr><th>Check</th><th>Result</th><th>Detail</th></tr>
{rows}</table></div>
<div class="card"><h2>The captured record</h2><pre>{html.escape(record_text)}</pre></div>
</main></body></html>"""
    _REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT.write_text(doc, encoding="utf-8")


def main() -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        _log("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    base = Path(tempfile.mkdtemp(prefix="chorus-memory-"))
    os.chdir(base)
    seed = base / "source"
    _seed_repo(seed)

    ledger = SqliteLedger.open(":memory:")
    try:
        registry = RoleRegistry.from_plugins(default_roles())
        factory = EmployeeHarnessFactory(
            api_key=api_key, base_url=base_url, deployment=deployment,
            company_id="acme", roles=registry, pricing=default_pricing_from_env(), seed=seed,
        )
        memory_root = factory.company_root / "memory"
        writer = EpisodicStore(memory_root)
        ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
        ledger.tasks.submit(Task(id="t1", intent=_TASK))
        assign_task(ledger, "t1", "ada")

        scheduler = Scheduler(
            ledger=ledger, workforce=LedgerWorkforce(ledger.employees),
            beat_runner_for=factory, budget_enforcer=BudgetEnforcer(ledger, company_id="acme"),
            roles=registry, landers=default_landers(factory.company_root),
            memory_writer=writer, max_concurrent_runs=1,
        )

        _log("running one keyed engineer beat with memory capture …")
        for _ in range(3):
            if ledger.tasks.get("t1").status in (TaskStatus.DONE, TaskStatus.BLOCKED):  # type: ignore[union-attr]
                break

            async def _pulse() -> None:
                await scheduler.tick_once()
                await scheduler.drain()

            asyncio.run(_pulse())

        run_id = ledger.runs.for_task("t1")[-1].id
        project_dir = memory_root / "project"
        records = scan_memory_dir(project_dir)
        rec = records[0] if records else None
        rec_text = (rec.source.read_text(encoding="utf-8") if rec and rec.source else "(no record written)")
        fm = rec.frontmatter if rec else {}

        checks: list[tuple[str, bool, str]] = [
            ("one episodic record written", len(records) == 1, f"{len(records)} record(s) under {project_dir}"),
            ("named by the run id (provenance)", bool(rec) and rec.id == run_id, f"id={rec.id if rec else '-'} run={run_id}"),
            ("kind = sprint_delta", fm.get("kind") == "sprint_delta", str(fm.get("kind"))),
            ("provenance: task_id", fm.get("task_id") == "t1", str(fm.get("task_id"))),
            ("provenance: employee_id", fm.get("employee_id") == "ada", str(fm.get("employee_id"))),
            ("outcome recorded", fm.get("outcome") in ("done", "needs_changes", "blocked"), str(fm.get("outcome"))),
            ("dream's scanner reads it back", bool(rec) and bool(rec.content), "scan_memory_dir parsed the record"),
        ]
        _write_report(checks, rec_text)

        _log("")
        for name, ok, detail in checks:
            _log(f"   [{'PASS' if ok else 'FAIL'}] {name} — {detail}")
        _log("")
        _log(f"   task status : {ledger.tasks.get('t1').status.value}")  # type: ignore[union-attr]
        _log(f"   memory record: {project_dir / (run_id + '.md')}")
        _log(f"   report      : {_REPORT}")
        return 0 if all(ok for _, ok, _ in checks) else 1
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
