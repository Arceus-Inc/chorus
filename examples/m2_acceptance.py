"""M2 acceptance, keyed end-to-end: two engineers + a dependency edge, with real dream beats.

The M2 headline proof, live: submit task A (→ engineer ada) and task B (→ engineer bob) with
``B depends_on A``. The dependency must gate **as data** — B is withheld from dispatch until A is
``done``, then the ``deps_resolved`` wake lets B run. Concurrency + budget gating are proven
deterministically in ``tests/heartbeat/test_m2_acceptance.py``; this exercises the dependency edge
against the model. Emits an HTML report.

Run keyed:  AZURE_OPENAI_API_KEY=… AZURE_OPENAI_BASE_URL=… AZURE_OPENAI_DEPLOYMENT=… \
            uv run python examples/m2_acceptance.py
"""

from __future__ import annotations

import asyncio
import html
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from chorus.budgets import BudgetEnforcer
from chorus.heartbeat import Scheduler
from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.lifecycle import assign_task
from chorus.memory import AppendOnlyMemoryWriter
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee, LedgerWorkforce
from chorus_cli._beats import default_pricing_from_env
from chorus_employee import default_landers
from chorus_harness import EmployeeHarnessFactory

_A = "Create a.py with a function double(x) that returns x * 2, and test_a.py with test_double asserting double(2) == 4."
_B = "Create b.py with a function triple(x) that returns x * 3, and test_b.py with test_triple asserting triple(2) == 6."
_REPORT = Path(__file__).resolve().parents[1] / "reports" / "m2-acceptance-report.html"


def _log(m: str) -> None:
    sys.stdout.write(m + "\n")
    sys.stdout.flush()


def _seed_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text("# project\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.name=s", "-c", "user.email=s@x", "commit", "-m", "init"],
        check=True, capture_output=True,
    )


def _write_report(checks: list[tuple[str, bool, str]], timeline: list[str]) -> None:
    ok = all(c[1] for c in checks)
    rows = "\n".join(
        f'<tr><td>{html.escape(n)}</td><td class="{"ok" if k else "bad"}">{"PASS" if k else "FAIL"}</td><td>{html.escape(d)}</td></tr>'
        for n, k, d in checks
    )
    tl = html.escape("\n".join(timeline))
    verdict = "M2 ACCEPTANCE PASS" if ok else "FAILURES PRESENT"
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>Chorus M2 Acceptance</title><style>
:root{{--bg:#f5f7fb;--panel:#fff;--ink:#17202a;--muted:#5f6b7a;--ok:#0a7a34;--bad:#b42318;--line:#d7deea;--accent:#0b5cab}}
body{{margin:0;background:radial-gradient(circle at top right,#dbeafe 0,var(--bg) 45%);color:var(--ink);font-family:Segoe UI,Tahoma,Arial,sans-serif;line-height:1.4}}main{{max-width:980px;margin:24px auto;padding:0 16px 32px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin-bottom:14px;box-shadow:0 8px 24px rgba(24,39,75,.06)}}
h1{{font-size:24px;margin:0 0 10px}}h2{{font-size:18px;color:var(--accent);margin:0 0 10px}}table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{text-align:left;border-bottom:1px solid var(--line);padding:8px 6px;vertical-align:top}}th{{color:var(--muted)}}.ok{{color:var(--ok);font-weight:700}}.bad{{color:var(--bad);font-weight:700}}pre{{background:#0f172a;color:#dbeafe;padding:12px;border-radius:10px;overflow-x:auto;font-size:12px}}.meta{{color:var(--muted)}}</style></head><body><main>
<div class="card"><h1>Chorus M2 — Acceptance (dependency edge, keyed)</h1><p class="meta">spec 11 §M2 · two engineers, <code>B depends_on A</code>, real dream beats. Concurrency + budget gating: see <code>tests/heartbeat/test_m2_acceptance.py</code>.</p><p><strong class="{"ok" if ok else "bad"}">{verdict}</strong></p></div>
<div class="card"><h2>Scenario</h2><p>Submit A → engineer <code>ada</code> and B → engineer <code>bob</code> with <code>B depends_on A</code>. Tick the kernel; B must stay withheld until A is <code>done</code>, then dispatch.</p></div>
<div class="card"><h2>Checks</h2><table><tr><th>Check</th><th>Result</th><th>Detail</th></tr>{rows}</table></div>
<div class="card"><h2>Tick timeline</h2><pre>{tl}</pre></div></main></body></html>"""
    _REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT.write_text(doc, encoding="utf-8")


def main() -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        _log("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    base = Path(tempfile.mkdtemp(prefix="chorus-m2-"))
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
        ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
        ledger.employees.create(Employee(id="bob", name="Bob", role="engineer"))
        ledger.tasks.submit(Task(id="A", intent=_A))
        ledger.tasks.submit(Task(id="B", intent=_B))
        ledger.dependencies.add("B", "A")  # B depends on A — the edge under test
        assign_task(ledger, "A", "ada")
        assign_task(ledger, "B", "bob")  # B assigned + woken, but blocked

        scheduler = Scheduler(
            ledger=ledger, workforce=LedgerWorkforce(ledger.employees),
            beat_runner_for=factory, budget_enforcer=BudgetEnforcer(ledger, company_id="acme"),
            roles=registry, landers=default_landers(factory.company_root),
            memory_writer=AppendOnlyMemoryWriter(factory.company_root / "memory"),
            max_concurrent_runs=2,
        )

        timeline: list[str] = []
        b_ever_ran_before_a_done = False
        a_done_tick: int | None = None
        b_first_run_tick: int | None = None

        for n in range(1, 7):
            a = ledger.tasks.get("A")
            b = ledger.tasks.get("B")
            if a and b and a.status in (TaskStatus.DONE, TaskStatus.BLOCKED) and b.status in (TaskStatus.DONE, TaskStatus.BLOCKED):
                break

            async def _pulse() -> None:
                await scheduler.tick_once()
                await scheduler.drain()

            asyncio.run(_pulse())

            a_done = ledger.tasks.get("A").status is TaskStatus.DONE  # type: ignore[union-attr]
            b_has_run = bool(ledger.runs.for_task("B"))
            if a_done and a_done_tick is None:
                a_done_tick = n
            if b_has_run and b_first_run_tick is None:
                b_first_run_tick = n
                if a_done_tick is None:  # B ran before A was ever done → dependency violated
                    b_ever_ran_before_a_done = True
            timeline.append(
                f"tick {n}: A={ledger.tasks.get('A').status.value} B={ledger.tasks.get('B').status.value} "  # type: ignore[union-attr]
                f"A_runs={len(ledger.runs.for_task('A'))} B_runs={len(ledger.runs.for_task('B'))}"
            )

        a_done = ledger.tasks.get("A").status is TaskStatus.DONE  # type: ignore[union-attr]
        checks: list[tuple[str, bool, str]] = [
            ("A dispatched first (has a run)", bool(ledger.runs.for_task("A")), f"A_runs={len(ledger.runs.for_task('A'))}"),
            ("B never ran before A was done (dependency gate)", not b_ever_ran_before_a_done,
             f"a_done_tick={a_done_tick} b_first_run_tick={b_first_run_tick}"),
            ("A reached done", a_done, str(ledger.tasks.get("A").status.value)),  # type: ignore[union-attr]
            ("B dispatched only after A done", (b_first_run_tick is None) or (a_done_tick is not None and b_first_run_tick >= a_done_tick),
             f"A done @ tick {a_done_tick}, B first ran @ tick {b_first_run_tick}"),
        ]
        _write_report(checks, timeline)

        _log("")
        for n, ok, d in checks:
            _log(f"   [{'PASS' if ok else 'FAIL'}] {n} — {d}")
        _log("")
        for line in timeline:
            _log("   " + line)
        _log(f"   report: {_REPORT}")
        return 0 if all(c[1] for c in checks) else 1
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
