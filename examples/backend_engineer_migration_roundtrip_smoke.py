"""Backend Engineer migration round-trip verification (spec §11 test library — safe-exit gate).

Every prior datastore run proved the service *reads and writes* a real engine. This one proves the
harder, deploy-time property: a schema migration can be ROLLED BACK. A migration that only applies
forward is a one-way door — a bad deploy has no exit but a lossy restore. The task ships a schema
change (add a `status` column to an `orders` table) and the DoD requires a `migration` gate in the
test_evidence bundle that actually booted a real Postgres container and ran the full round-trip:
apply → write → roll back (asserting the column is gone and prior data intact) → re-apply. A
forward-only migration, or one proven against SQLite, cannot satisfy it.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/backend_engineer_migration_roundtrip_smoke.py

Needs a container runtime (docker/podman) on PATH for the engineer to boot Postgres. Skips cleanly
(exit 0) when the Azure env vars are unset. Exits non-zero if keyed but the round-trip was not proven.
"""

from __future__ import annotations

import asyncio
import json
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
    "The repo has an initial schema migration at migrations/001_init.up.sql that creates an `orders` "
    "table (columns: id, total). Add migration 002 that adds a nullable `status TEXT` column to "
    "`orders`, WITH a matching down migration that removes it (author both the up and the down). "
    "Then PROVE IT ROUND-TRIPS against a REAL Postgres — this sandbox has a container runtime (try "
    "`docker info`, then `podman info`; boot a real `postgres` image, NEVER SQLite for a Postgres "
    "migration). Load the `migration-roundtrip` skill for the method. Write a round-trip script "
    "(migration_roundtrip.sh or .py) that: boots Postgres in a container and waits for it healthy; "
    "applies 001 then 002 and asserts the `status` column exists (query information_schema); inserts "
    "an order row carrying a status; rolls back 002 and asserts the `status` column is GONE and the "
    "`orders` table plus its prior rows are intact; then re-applies 002 and asserts it succeeds. Add "
    "a `migration` gate to your `test_evidence` call that runs this script and exits non-zero if any "
    "schema/data assertion fails — so a green test_evidence/manifest.json carries the round-trip as "
    "proof the deploy has a safe exit. This is a schema/DDL task; no HTTP service is required."
)


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


class _TraceBus(EventBus):
    """Prints tool calls + the verdict, so the migrate -> round-trip -> land loop is visible."""

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
    """A repo with an initial migration the Backend Engineer adds a reversible 002 onto."""
    path.mkdir(parents=True)
    (path / "migrations").mkdir()
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text(
        "# orders schema\n\nRaw SQL migrations under migrations/ (NNN_name.up.sql / .down.sql).\n",
        encoding="utf-8",
    )
    (path / "migrations" / "001_init.up.sql").write_text(
        "CREATE TABLE orders (\n"
        "  id     SERIAL PRIMARY KEY,\n"
        "  total  NUMERIC(10, 2) NOT NULL\n"
        ");\n",
        encoding="utf-8",
    )
    (path / "migrations" / "001_init.down.sql").write_text("DROP TABLE orders;\n", encoding="utf-8")
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


def _migration_gate_passed(manifest_path: Path) -> bool:
    """True iff the bundle carries a gate whose name mentions migration and whose status is pass."""
    if not manifest_path.exists():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    gates = manifest.get("gates", [])
    mig = [g for g in gates if "migrat" in str(g.get("name", "")).lower()]
    return bool(mig) and all(g.get("status") == "pass" for g in mig)


def main() -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        _log("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    base = Path(tempfile.mkdtemp(prefix="chorus-backend-eng-migration-"))
    os.chdir(base)
    seed = base / "source"
    _seed_repo(seed)

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
        _log(
            "1. EMPLOYEE — materialized as backend_engineer (spec §11 — migration round-trip, safe exit)"
        )
        _log(f"   subagents : {', '.join(sa.name for sa in cfg.subagents)}")
        _log(f"   worktree  : {mat.working_dir}")

        ledger.tasks.submit(Task(id="t1", intent=_TASK))
        assign_task(ledger, "t1", "bex")
        # The safe-exit floor: a green bundle whose gates INCLUDE a passing `migration` gate, AND a
        # down migration for 002 on disk (the reversible path shipped, not just the forward one).
        ledger.dod.create(
            "t1",
            Verifier.command(
                "test -f test_evidence/manifest.json && "
                'grep -q \'"verdict": "pass"\' test_evidence/manifest.json && '
                "python3 -c \"import json,sys,glob; m=json.load(open('test_evidence/manifest.json')); "
                "g=[x for x in m['gates'] if 'migrat' in str(x.get('name','')).lower()]; "
                "down=glob.glob('migrations/*002*down*') or glob.glob('migrations/*002*.down.*'); "
                "sys.exit(0 if g and all(x.get('status')=='pass' for x in g) and down else 1)\"",
                artifact_class="pr",
            ),
        )
        _log(
            "\n2. TASK assigned (DoD: green bundle carrying a PASSING migration gate + a 002 down "
            "migration on disk)\n   t1: " + _TASK
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
        ):  # build migration + round-trip prove + land; headroom for a repair pass
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
        manifest = company_main / "test_evidence" / "manifest.json"
        migration_proven = _migration_gate_passed(manifest)
        migrations_dir = company_main / "migrations"
        down_002 = list(migrations_dir.glob("*002*down*")) + list(
            migrations_dir.glob("*002*.down.*")
        )
        if landed:
            _log(
                f"   ★ PR ARTIFACT LANDED: {artifacts[0].type.value} ref={artifacts[0].resource_ref}"
            )
            _log(f"   test_evidence carries a PASSING migration gate: {migration_proven}")
            _log(f"   002 down migration on disk: {[p.name for p in down_002] or False}")
            if manifest.exists():
                gates = json.loads(manifest.read_text(encoding="utf-8")).get("gates", [])
                _log(f"   gates: {[(g.get('name'), g.get('status')) for g in gates]}")
        else:
            _log("   no artifact landed (DoD not green this run — see run/DoD status above).")

        ok = (
            landed
            and migration_proven
            and bool(down_002)
            and final is not None
            and final.status is TaskStatus.DONE
        )
        _log(
            "\n   → PASS: backend_engineer shipped a migration proven REVERSIBLE by a round-trip gate."
            if ok
            else "\n   → FAIL: the migration was not proven reversible by a passing round-trip gate."
        )
        return 0 if ok else 1
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
