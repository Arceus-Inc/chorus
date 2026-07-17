"""Backend Engineer mutation-testing verification (spec §11 test library — tests-are-real gate).

Every prior smoke run trusted a green `pytest -q`: proof the tests PASS, not proof they would FAIL if
the code were wrong. Those are different claims — a test that calls a function but asserts almost
nothing passes forever, including when the behaviour breaks. This example forces the deeper gate:
mutation testing. The task carries real boundary logic (a `clamp` with `<`/`>`/`==` edges — a rich
mutant surface), and the DoD requires a `mutation` gate in the test_evidence bundle that actually ran
a mutation tool (mutmut) scoped to the changed module and passed only because the tests KILLED the
injected faults. A vacuous test suite (green coverage, no real assertions) cannot satisfy it — a
surviving mutant fails the gate.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/backend_engineer_mutation_smoke.py

Skips cleanly (exit 0) when those env vars are unset. Exits non-zero if keyed but the tests were not
proven real by a passing mutation gate — a real assertion, not a demo.
"""

from __future__ import annotations

import asyncio
import json
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
    "In clamp.py add a function clamp(value: float, low: float, high: float) -> float that returns "
    "value when it is within [low, high]; low when value < low; high when value > high. Raise "
    "ValueError('low must not exceed high') if low > high. "
    "Then PROVE THE TESTS ARE REAL with mutation testing (load the `mutation-testing` skill for the "
    "method). Write a pytest suite in test_clamp.py strong enough to reach a 100% kill rate on "
    "clamp.py — it must cover the in-range case, BOTH boundaries (value == low and value == high), "
    "both clamp directions (below low, above high), and the low > high ValueError. Then `pip install "
    "mutmut`, run it scoped to clamp.py, and add a `mutation` gate to your `test_evidence` call whose "
    "command FAILS (exits non-zero) if any mutant survives — so a green test_evidence/manifest.json "
    "carries a passing `mutation` gate as proof the tests would go RED on a regression."
)


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


class _TraceBus(EventBus):
    """Prints tool calls + the verdict, so the build -> prove-tests-real -> land loop is visible."""

    def __init__(self) -> None:
        super().__init__(log_path=None)

    def emit(self, event: Event) -> None:
        p = event.payload
        if event.kind is EventKind.RUN_TOOL_USE:
            _log(f"    → {p.get('tool', '?')}  {str(p.get('input', ''))[:150]}")
        elif event.kind is EventKind.RUN_TOOL_RESULT:
            _log(f"    ← {p.get('tool', '?')} [{'ERR' if p.get('is_error') else 'ok'}]")
        elif event.kind is EventKind.RUN_EVALUATED:
            _log(f"    ⊢ evaluated: {p.get('outcome', p)}")


def _seed_repo(path: Path) -> None:
    """A tiny valid Python repo the Backend Engineer probes + grows a mutation-proven module into."""
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text(
        "# clamp lib\n\nA tiny numeric helper. Tests are proven real with mutation testing.\n",
        encoding="utf-8",
    )
    (path / "test_placeholder.py").write_text(
        "def test_placeholder() -> None:\n    assert True\n", encoding="utf-8"
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


def _mutation_gate_passed(manifest_path: Path) -> bool:
    """True iff the bundle carries a gate whose name mentions mutation and whose status is pass."""
    if not manifest_path.exists():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    gates = manifest.get("gates", [])
    mutation_gates = [g for g in gates if "mutat" in str(g.get("name", "")).lower()]
    return bool(mutation_gates) and all(g.get("status") == "pass" for g in mutation_gates)


def main() -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        _log("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    base = Path(tempfile.mkdtemp(prefix="chorus-backend-eng-mutation-"))
    os.chdir(base)
    seed = base / "source"
    _seed_repo(seed)

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
        _log(
            "1. EMPLOYEE — materialized as backend_engineer (spec §11 — mutation gate, tests-are-real)"
        )
        _log(f"   subagents : {', '.join(sa.name for sa in cfg.subagents)}")
        _log(f"   worktree  : {mat.working_dir}")

        ledger.tasks.submit(Task(id="t1", intent=_TASK))
        assign_task(ledger, "t1", "bex")
        # The tests-are-real floor: a green unit bundle whose gates INCLUDE a passing `mutation` gate.
        # The python3 check asserts a mutation-named gate exists and passed — a vacuous suite can be
        # green on `pytest -q` but cannot survive injected faults, so it cannot satisfy this.
        ledger.dod.create(
            "t1",
            Verifier.command(
                "test -f test_evidence/manifest.json && "
                'grep -q \'"verdict": "pass"\' test_evidence/manifest.json && '
                "python3 -c \"import json,sys; m=json.load(open('test_evidence/manifest.json')); "
                "g=[x for x in m['gates'] if 'mutat' in str(x.get('name','')).lower()]; "
                "sys.exit(0 if g and all(x.get('status')=='pass' for x in g) else 1)\"",
                artifact_class="pr",
            ),
        )
        _log(
            "\n2. TASK assigned (DoD: green bundle carrying a PASSING mutation gate)\n   t1: "
            + _TASK
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

        for n in range(
            1, 4
        ):  # build + author strong tests + mutation-prove + land; headroom for a pass
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
        clamp = company_main / "clamp.py"
        manifest = company_main / "test_evidence" / "manifest.json"
        mutation_proven = _mutation_gate_passed(manifest)
        if landed:
            _log(
                f"   ★ PR ARTIFACT LANDED: {artifacts[0].type.value} ref={artifacts[0].resource_ref}"
            )
            _log(f"   clamp.py present: {clamp.exists()}")
            _log(f"   test_evidence carries a PASSING mutation gate: {mutation_proven}")
            if manifest.exists():
                gates = json.loads(manifest.read_text(encoding="utf-8")).get("gates", [])
                _log(f"   gates: {[(g.get('name'), g.get('status')) for g in gates]}")
        else:
            _log("   no artifact landed (DoD not green this run — see run/DoD status above).")

        ok = (
            landed
            and clamp.exists()
            and mutation_proven
            and final is not None
            and final.status is TaskStatus.DONE
        )
        _log(
            "\n   → PASS: backend_engineer shipped code whose TESTS were proven real by a mutation gate."
            if ok
            else "\n   → FAIL: the tests were not proven real by a passing mutation gate."
        )
        return 0 if ok else 1
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
