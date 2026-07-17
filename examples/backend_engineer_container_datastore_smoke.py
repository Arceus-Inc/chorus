"""Backend Engineer container-backed datastore verification (spec §16 Slice 3, testcontainers path).

The prior datastore smoke (:mod:`backend_engineer_datastore_smoke`) proved durability against SQLite —
an EMBEDDED engine, so the api_verifier's "boot a real container" instruction never actually ran. This
example forces the other branch: the service is backed by Redis, a CLIENT-SERVER datastore, so proving
"not a mock" requires the api_verifier to actually discover and use this sandbox's container runtime
(`docker` or `podman` — neither is assumed, both are checked) and boot a real Redis image, per the
`testcontainers-integration` skill and the api_verifier's MUST-container instruction. `fakeredis` or an
in-process dict would satisfy the endpoints but not this DoD, which greps for a real container-boot
command in the recorded evidence.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/backend_engineer_container_datastore_smoke.py

Skips cleanly (exit 0) when those env vars are unset. Exits non-zero if keyed but a real container-boot
was not proven in the evidence — a real assertion, not a demo.
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
    "Build a STATEFUL HTTP service in app.py backed by a REAL Redis server — not an in-process dict, "
    "not `fakeredis`, not any other embedded/in-memory substitute. This sandbox has a container "
    "runtime available (try `docker info`, then `podman info` — use whichever answers); boot a real "
    "Redis image as a disposable container for this. Use the `redis` PyPI package (pip install it) as "
    "the client. The service must start with `python app.py` and listen on the port in the PORT "
    "environment variable (default 8000), connecting to Redis at the host:port in the REDIS_URL "
    "environment variable. Routes: `GET /health` returns 200 `ok`; `POST /items` with a JSON body "
    '{"name": "<text>"} inserts an item into Redis and returns 201 with the created item as JSON (an '
    "id + the name); `GET /items` returns 200 with a JSON array of all items read back from Redis. The "
    "data MUST survive the HTTP service process being restarted while the Redis container keeps "
    "running (real state lives in Redis, not in the Python process). Put the storage logic in a small "
    "store.py module and add a pytest test in test_store.py (it may use a real Redis instance you "
    "boot for the test, or document why it's skipped without one)."
)


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


class _TraceBus(EventBus):
    """Prints tool calls + the verdict, so the container-boot -> prove -> land loop is visible."""

    def __init__(self) -> None:
        super().__init__(log_path=None)

    def emit(self, event: Event) -> None:
        p = event.payload
        if event.kind is EventKind.RUN_TOOL_USE:
            _log(f"    → {p.get('tool', '?')}  {str(p.get('input', ''))[:160]}")
        elif event.kind is EventKind.RUN_TOOL_RESULT:
            _log(f"    ← {p.get('tool', '?')} [{'ERR' if p.get('is_error') else 'ok'}]")
        elif event.kind is EventKind.RUN_EVALUATED:
            _log(f"    ⊢ evaluated: {p.get('outcome', p)}")


def _seed_service(path: Path) -> None:
    """A tiny valid Python repo the Backend Engineer probes + grows into a Redis-backed service."""
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text(
        "# demo service\n\nRun with `python app.py` (honours PORT and REDIS_URL env vars).\n",
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

    base = Path(tempfile.mkdtemp(prefix="chorus-backend-eng-container-datastore-"))
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
        _log(
            "1. EMPLOYEE — materialized as backend_engineer "
            "(spec §16 Slice 3 — client-server datastore, container-boot path)"
        )
        _log(f"   subagents : {', '.join(sa.name for sa in cfg.subagents)}")
        _log(f"   worktree  : {mat.working_dir}")

        ledger.tasks.submit(Task(id="t1", intent=_TASK))
        assign_task(ledger, "t1", "bex")
        # The container-boot floor: a green unit bundle, a passing api_verdict.json with a persistence
        # check, AND evidence naming an actual container-runtime boot command — "connected to redis" is
        # not enough; the api_verifier's evidence must show HOW it got a real Redis running.
        ledger.dod.create(
            "t1",
            Verifier.command(
                "test -f test_evidence/manifest.json && "
                'grep -q \'"verdict": "pass"\' test_evidence/manifest.json && '
                "test -f api_verdict.json && "
                "grep -q '\"passed\": *true' api_verdict.json && "
                "grep -qi persist api_verdict.json && "
                "grep -Eqi '(docker|podman)([ -]compose)? run|(docker|podman)-compose up' "
                "api_verdict.json",
                artifact_class="pr",
            ),
        )
        _log(
            "\n2. TASK assigned (DoD: green bundle, a passing api_verdict.json with a persistence "
            "check, AND evidence of a real container boot)\n   t1: " + _TASK
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

        for n in range(1, 4):  # build + unit + container-verify + land; headroom for a repair pass
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
        vt_lower = verdict_text.lower()
        proven_persist = '"passed": true' in verdict_text and "persist" in vt_lower
        proven_container = (
            "docker run" in vt_lower
            or "podman run" in vt_lower
            or "docker-compose up" in vt_lower
            or "podman-compose up" in vt_lower
            or "docker compose up" in vt_lower
            or "podman compose up" in vt_lower
        )
        if landed:
            _log(
                f"   ★ PR ARTIFACT LANDED: {artifacts[0].type.value} ref={artifacts[0].resource_ref}"
            )
            _log(f"   stateful service app.py present: {app.exists()}")
            _log(f"   api_verdict.json proves persistence-across-restart: {proven_persist}")
            _log(f"   api_verdict.json evidence names a real container boot: {proven_container}")
            if verdict_text:
                _log(f"   verdict: {verdict_text[:400]}")
        else:
            _log("   no artifact landed (DoD not green this run — see run/DoD status above).")

        ok = (
            landed
            and proven_persist
            and proven_container
            and final is not None
            and final.status is TaskStatus.DONE
        )
        _log(
            "\n   → PASS: backend_engineer shipped a service whose persistence was proven against a "
            "REAL containerized datastore."
            if ok
            else "\n   → FAIL: durability against a real, container-booted datastore was not proven."
        )
        return 0 if ok else 1
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
