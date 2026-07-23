"""Backend Engineer test authorship (spec §06 — the validation sandwich, 'pre') — one keyed beat.

§06's validation sandwich enforces proof *where the code is made*. The API-Verifier (Slice 3a) is the
'live' layer; this example proves the 'pre' layer: the engineer builds a feature, then DELEGATES test
authoring to its `test_author` subagent so the code's author is not the sole author of its tests. The
Test-Author writes honeycomb-shaped tests covering the happy path AND the error cases, runs them green,
and writes a durable `test_plan.json`. The DoD gates on a green `test_evidence` bundle AND a
`test_plan.json` with `authored: true` — so the independent tests must exist and pass, not be a claim.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/backend_engineer_testauthor_smoke.py

Skips cleanly (exit 0) when those env vars are unset. Exits non-zero if keyed but the tests were not
independently authored — a real assertion, not a demo.
"""

from __future__ import annotations

import asyncio
import os
import uuid

_EXAMPLE_COMPANY = str(uuid.uuid5(uuid.NAMESPACE_URL, "chorus-example"))  # one stable demo org
import subprocess
import sys
import tempfile
from pathlib import Path

from chorus.budgets import BudgetEnforcer
from chorus.events import Event, EventKind
from chorus.heartbeat import Scheduler
from chorus.ledger import Ledger, Task, TaskStatus
from chorus.lifecycle import assign_task
from chorus.observability import EventBus
from chorus.outcomes import Verifier
from chorus.roles import RoleRegistry, default_roles, role_beat_config
from chorus.workforce import Employee, LedgerWorkforce
from chorus_cli._beats import default_pricing_from_env
from chorus_employee import default_landers
from chorus_harness import EmployeeHarnessFactory

_TASK = (
    "In calculator.py add a function divide(a: float, b: float) -> float that returns a / b and raises "
    "ValueError('division by zero') when b == 0. Keep the existing add() function and its test. Then "
    "GET THE TESTS WRITTEN INDEPENDENTLY: delegate to your `test_author` subagent to author "
    "honeycomb-shaped tests for divide — covering the happy path AND the divide-by-zero error case — "
    "so the tests are written by something other than the code's author. Keep it dependency-free."
)


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


class _TraceBus(EventBus):
    """Prints tool calls + the verdict, so the build -> delegate-tests -> prove loop is visible."""

    def __init__(self) -> None:
        super().__init__(log_path=None)

    def emit(self, event: Event) -> None:
        p = event.payload
        if event.kind is EventKind.RUN_TOOL_USE:
            _log(f"    → {p.get('tool', '?')}  {str(p.get('input', ''))[:120]}")
        elif event.kind is EventKind.RUN_TOOL_RESULT:
            _log(f"    ← {p.get('tool', '?')} [{'ERR' if p.get('is_error') else 'ok'}]")
        elif event.kind is EventKind.RUN_EVALUATED:
            _log(f"    ⊢ evaluated: {p.get('outcome', p)}")


def _seed_service(path: Path) -> None:
    """A tiny valid Python repo with an existing, tested function the engineer extends."""
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "calculator.py").write_text(
        "def add(a: float, b: float) -> float:\n    return a + b\n", encoding="utf-8"
    )
    (path / "test_calculator.py").write_text(
        "from calculator import add\n\n\ndef test_add() -> None:\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "-c",
            "user.name=s",
            "-c",
            "user.email=s@x",
            "commit",
            "-m",
            "init",
        ],
        check=True,
        capture_output=True,
    )


def main() -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        _log("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    base = Path(tempfile.mkdtemp(prefix="chorus-backend-eng-testauthor-"))
    os.chdir(base)
    seed = base / "source"
    _seed_service(seed)

    ledger = Ledger.open(
        os.environ.get("CHORUS_LEDGER_DSN", "postgresql://localhost/chorus"),
        company_id=_EXAMPLE_COMPANY,
    )
    try:
        registry = RoleRegistry.from_plugins(default_roles())
        factory = EmployeeHarnessFactory(
            api_key=api_key,
            base_url=base_url,
            deployment=deployment,
            company_id="acme",
            roles=registry,
            pricing=default_pricing_from_env(),
            seed=seed,
        )
        ledger.employees.create(Employee(id="bex", name="Bex", role="backend_engineer"))

        cfg = role_beat_config(registry.get("backend_engineer").manifest)
        mat = factory.materialize(ledger.employees.get("bex"))  # type: ignore[arg-type]
        _log("=" * 72)
        _log("1. EMPLOYEE — materialized as backend_engineer (spec §06 — Test-Author, 'pre' layer)")
        _log(f"   subagents : {', '.join(sa.name for sa in cfg.subagents)}")
        _log(f"   worktree  : {mat.working_dir}")

        ledger.tasks.submit(Task(id="t1", intent=_TASK))
        assign_task(ledger, "t1", "bex")
        # The 'pre'-layer floor: a green unit bundle AND a test_plan.json the test_author wrote with
        # authored:true — so the tests for the change exist and pass, authored independently of the code.
        ledger.dod.create(
            "t1",
            Verifier.command(
                "test -f test_evidence/manifest.json && "
                'grep -q \'"verdict": "pass"\' test_evidence/manifest.json && '
                "test -f test_plan.json && "
                "grep -q '\"authored\": *true' test_plan.json",
                artifact_class="pr",
            ),
        )
        _log(
            "\n2. TASK assigned (DoD: green bundle AND a test_plan.json authored by test_author)"
            "\n   t1: " + _TASK
        )

        scheduler = Scheduler(
            ledger=ledger,
            workforce=LedgerWorkforce(ledger.employees),
            beat_runner_for=factory,
            budget_enforcer=BudgetEnforcer(ledger, company_id="acme"),
            roles=registry,
            landers=default_landers(factory.company_root),
            event_bus=_TraceBus(),
            max_concurrent_runs=1,
        )

        for n in range(1, 4):  # build + delegate tests + prove + land; headroom for a repair pass
            task = ledger.tasks.get("t1")
            if task is None or task.status in (TaskStatus.DONE, TaskStatus.BLOCKED):
                break
            _log(f"\n3.{n} TICK — kernel dispatches the backend_engineer beat")

            async def _pulse() -> None:
                await scheduler.tick_once()
                await scheduler.drain()

            asyncio.run(_pulse())
            run = ledger.runs.for_task("t1")[-1]
            dod = ledger.dod.get_for_task("t1")
            _log(f"   run: {run.status.value}   DoD: {dod.status.value if dod else '-'}")

        _log("\n" + "=" * 72 + "\n4. RESULT")
        final = ledger.tasks.get("t1")
        _log(f"   task status : {final.status.value if final else '?'}")
        artifacts = ledger.artifacts.list_for_task("t1")
        company_main = factory.company_root / "repo"
        landed = bool(artifacts)
        calc = company_main / "calculator.py"
        plan = company_main / "test_plan.json"
        plan_text = plan.read_text(encoding="utf-8") if plan.exists() else ""
        feature = calc.exists() and "divide" in calc.read_text(encoding="utf-8")
        authored = '"authored": true' in plan_text and "divide" in plan_text.lower()
        if landed:
            _log(
                f"   ★ PR ARTIFACT LANDED: {artifacts[0].type.value} ref={artifacts[0].resource_ref}"
            )
            _log(f"   divide() present in calculator.py: {feature}")
            _log(f"   test_plan.json authored by test_author (covers divide): {authored}")
            if plan_text:
                _log(f"   plan: {plan_text[:260]}")
        else:
            _log("   no artifact landed (DoD not green this run — see run/DoD status above).")

        ok = (
            landed
            and feature
            and authored
            and final is not None
            and final.status is (TaskStatus.DONE)
        )
        _log(
            "\n   → PASS: backend_engineer shipped a feature with independently authored tests."
            if ok
            else "\n   → FAIL: the tests were not independently authored."
        )
        return 0 if ok else 1
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
