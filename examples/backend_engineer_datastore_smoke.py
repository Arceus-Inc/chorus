"""Backend Engineer real-datastore verification (spec §16 Slice 3b) — durability, judged independently.

Slice 3a proved the API-Verifier can boot a *stateless* service and get live 200s. But a stateless
boot+curl cannot catch a mock — an in-memory fake passes POST->GET within one process too. This example
raises the bar to the spec's real claim: "correctness proven against a real system, because a suite that
passes on mocks proves the mocks." The engineer builds a STATEFUL service backed by a real SQLite file,
then delegates to the api_verifier, which proves DURABILITY: it writes a record, RESTARTS the service
against the same datastore, and reads it back — data that survives a restart persisted to a real store;
data that vanishes was a mock. The DoD gates on a green unit bundle AND a passing api_verdict.json whose
checks include the persistence proof.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/backend_engineer_datastore_smoke.py

Skips cleanly (exit 0) when those env vars are unset. Exits non-zero if keyed but persistence was not
proven — a real assertion, not a demo.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from chorus.budgets import BudgetEnforcer
from chorus.events import Event, EventKind
from chorus.heartbeat import Scheduler
from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.lifecycle import assign_task
from chorus.observability import EventBus
from chorus.outcomes import Verifier
from chorus.roles import RoleRegistry, default_roles, role_beat_config
from chorus.workforce import Employee, LedgerWorkforce
from chorus_cli._beats import default_pricing_from_env
from chorus_employee import default_landers
from chorus_harness import EmployeeHarnessFactory

_TASK = (
    "Build a STATEFUL HTTP service in app.py using ONLY the Python standard library (http.server + "
    "sqlite3) — no pip installs. It must start with `python app.py` and listen on the port in the PORT "
    "environment variable (default 8000). It persists to a SQLite file at the path in the DB_PATH "
    "environment variable (default demo.db), creating the table on startup if absent. Routes: "
    '`GET /health` returns 200 `ok`; `POST /items` with a JSON body {"name": "<text>"} inserts an '
    "item and returns 201 with the created item as JSON (an id + the name); `GET /items` returns 200 "
    "with a JSON array of all items. The data MUST survive a process restart (it is a real file, not "
    "in-memory). Put the storage logic in a small store.py module and add a pytest test in "
    "test_store.py that inserts an item and reads it back. Keep it dependency-free."
)


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


class _TraceBus(EventBus):
    """Prints tool calls + the verdict, so the build -> prove -> durability-verify loop is visible."""

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
    """A tiny valid Python repo the Backend Engineer probes + grows into a stateful service."""
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text(
        "# demo service\n\nRun with `python app.py` (honours PORT and DB_PATH env vars).\n",
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


def main() -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        _log("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    base = Path(tempfile.mkdtemp(prefix="chorus-backend-eng-datastore-"))
    os.chdir(base)
    seed = base / "source"
    _seed_service(seed)

    ledger = SqliteLedger.open(":memory:")
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
        _log("1. EMPLOYEE — materialized as backend_engineer (spec §16 Slice 3b — real datastore)")
        _log(f"   subagents : {', '.join(sa.name for sa in cfg.subagents)}")
        _log(f"   worktree  : {mat.working_dir}")

        ledger.tasks.submit(Task(id="t1", intent=_TASK))
        assign_task(ledger, "t1", "bex")
        # The real-datastore floor: a green unit bundle AND a passing api_verdict.json whose checks
        # include the durability proof. A `persist`-named check means the api_verifier actually wrote,
        # restarted, and re-read — a mock in-memory store cannot survive that.
        ledger.dod.create(
            "t1",
            Verifier.command(
                "test -f test_evidence/manifest.json && "
                'grep -q \'"verdict": "pass"\' test_evidence/manifest.json && '
                "test -f api_verdict.json && "
                "grep -q '\"passed\": *true' api_verdict.json && "
                "grep -qi persist api_verdict.json",
                artifact_class="pr",
            ),
        )
        _log(
            "\n2. TASK assigned (DoD: green bundle AND a passing api_verdict.json with a persistence "
            "check)\n   t1: " + _TASK
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

        for n in range(1, 4):  # build + unit + durability-verify + land; headroom for a repair pass
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
        app = company_main / "app.py"
        verdict_path = company_main / "api_verdict.json"
        verdict_text = verdict_path.read_text(encoding="utf-8") if verdict_path.exists() else ""
        proven = (
            app.exists() and '"passed": true' in verdict_text and "persist" in verdict_text.lower()
        )
        if landed:
            _log(
                f"   ★ PR ARTIFACT LANDED: {artifacts[0].type.value} ref={artifacts[0].resource_ref}"
            )
            _log(f"   stateful service app.py present: {app.exists()}")
            _log(f"   api_verdict.json proves persistence-across-restart: {proven}")
            if verdict_text:
                _log(f"   verdict: {verdict_text[:280]}")
        else:
            _log("   no artifact landed (DoD not green this run — see run/DoD status above).")

        ok = landed and proven and final is not None and final.status is TaskStatus.DONE
        _log(
            "\n   → PASS: backend_engineer shipped a service whose persistence was proven against a real store."
            if ok
            else "\n   → FAIL: durability against a real datastore was not proven."
        )
        return 0 if ok else 1
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
