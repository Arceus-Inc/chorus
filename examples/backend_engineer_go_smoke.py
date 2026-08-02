"""Backend Engineer Go smoke — stack-agnostic verify-on-stop (discover-not-assume).

The twin of ``backend_engineer_smoke.py``, but seeded with a **Go module** instead of a Python package.
Same employee, same Hermes-style Command DoD: ``go test ./...`` exits 0 and deliverable files exist.
No ``test_evidence/`` bundle required for this micro ticket.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/backend_engineer_go_smoke.py

Skips cleanly (exit 0) when those env vars are unset, or when the Go toolchain is absent. Exits non-zero
if keyed but the beat did not land a green Go bundle — a real assertion, not a demo.
"""

from __future__ import annotations

import asyncio
import os
import uuid

_EXAMPLE_COMPANY = str(uuid.uuid5(uuid.NAMESPACE_URL, "chorus-example"))  # one stable demo org
import shutil
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
    "In slugify.go add an exported function Slugify(s string) string that lowercases s, replaces every "
    "run of non-alphanumeric characters with a single '-', and strips any leading or trailing '-'. "
    'In slugify_test.go add a Go test asserting Slugify("Hello, World!") == "hello-world". '
    "Keep the existing Health() function and its test. Make the changes directly in those files and "
    "make `go test ./...` pass."
)

_SMOKE_DOD_COMMAND = "test -f slugify.go && test -f slugify_test.go && go test ./..."


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=False, capture_output=True, text=True
    ).stdout.rstrip()


class _TraceBus(EventBus):
    """Prints tool calls + the evaluator verdict, so the probe→implement→prove loop is visible."""

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
    """A tiny, valid Go module the Backend Engineer probes + extends (a real `go test` repo)."""
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "go.mod").write_text("module demo\n\ngo 1.21\n", encoding="utf-8")
    (path / "health.go").write_text(
        'package demo\n\nfunc Health() string {\n\treturn "ok"\n}\n', encoding="utf-8"
    )
    (path / "health_test.go").write_text(
        'package demo\n\nimport "testing"\n\n'
        'func TestHealth(t *testing.T) {\n\tif Health() != "ok" {\n\t\tt.Fatalf("want ok")\n\t}\n}\n',
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
    if shutil.which("go") is None:
        _log("skipping: the Go toolchain is not on PATH (this example needs `go test`)")
        return 0
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        _log("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    base = Path(tempfile.mkdtemp(prefix="chorus-backend-eng-go-"))
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
        _log("1. EMPLOYEE — materialized as backend_engineer (spec §03 — Go, discover-not-assume)")
        _log(f"   tools     : {', '.join(cfg.tools)}")
        _log(f"   sandbox   : {cfg.sandbox}   permission: {cfg.permission_mode}")
        _log(f"   worktree  : {mat.working_dir}")
        _log(f"   seeded    : {_git(mat.working_dir, 'ls-files')!r}")

        ledger.tasks.submit(Task(id="t1", intent=_TASK))
        assign_task(ledger, "t1", "bex")
        # Verify-on-stop: green go test and deliverable files — no test_evidence/ bundle for micro work.
        ledger.dod.create(
            "t1",
            Verifier.command(_SMOKE_DOD_COMMAND, artifact_class="pr"),
        )
        _log(
            f"\n2. TASK assigned (DoD: {_SMOKE_DOD_COMMAND!r})\n   t1: "
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
        ):  # one deliverable beat gates on the bundle + lands; headroom for repair
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
        slug = company_main / "slugify.go"
        shipped = slug.exists() and "Slugify" in slug.read_text(encoding="utf-8")
        if landed:
            _log(
                f"   ★ PR ARTIFACT LANDED: {artifacts[0].type.value} ref={artifacts[0].resource_ref}"
            )
            _log(f"   company main slugify.go present + integrated: {shipped}")
        else:
            _log("   no artifact landed (DoD not green this run — see run/DoD status above).")

        ok = landed and shipped and final is not None and final.status is TaskStatus.DONE
        _log(
            "\n   → PASS: backend_engineer shipped a proven Go PR (stack-agnostic)."
            if ok
            else "\n   → FAIL: nothing landed."
        )
        return 0 if ok else 1
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
