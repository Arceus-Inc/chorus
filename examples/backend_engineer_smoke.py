"""Backend Engineer proof-bundle slice (backend-engineer spec §10 / §16 Slice 2) — one keyed LLM beat.

An end-to-end proof that the ``backend_engineer`` employee exists and proves its work: seed a tiny
Python service, hire a Backend Engineer, assign a ticket, and tick the kernel. A real model probes the
stack, implements the function + a test, runs the tests to green, then calls ``test_evidence`` to write
a durable ``test_evidence/`` bundle; the evidence-floor DoD passes only on an all-green manifest, and a
``pr`` artifact lands (the same ``pr`` lander the Engineer uses — outcome_kind matches). Solo: no reviewer.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/backend_engineer_smoke.py

Skips cleanly (exit 0) when those env vars are unset. Exits non-zero if keyed but the beat did not land
the deliverable — so it is a real assertion, not just a demo.
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
    "In slugify.py add a function slugify(s: str) -> str that lowercases s, replaces every run of "
    "non-alphanumeric characters with a single '-', and strips any leading or trailing '-'. "
    "In test_slugify.py add a pytest test asserting slugify('Hello, World!') == 'hello-world'. "
    "Keep the existing health() function and its test. Make the changes directly in those files and "
    "make the tests pass."
)


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=False, capture_output=True, text=True
    ).stdout.rstrip()


class _TraceBus(EventBus):
    """Prints tool calls + the evaluator verdict, so the implement→run→prove loop is visible."""

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
    """A tiny, valid Python project the Backend Engineer probes + extends (a real pytest repo)."""
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "app.py").write_text('def health() -> str:\n    return "ok"\n', encoding="utf-8")
    (path / "test_app.py").write_text(
        'from app import health\n\n\ndef test_health() -> None:\n    assert health() == "ok"\n',
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

    base = Path(tempfile.mkdtemp(prefix="chorus-backend-eng-"))
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
            "1. EMPLOYEE — materialized as backend_engineer (spec §16 Slice 2 — test_evidence floor)"
        )
        _log(f"   tools     : {', '.join(cfg.tools)}")
        _log(f"   sandbox   : {cfg.sandbox}   permission: {cfg.permission_mode}")
        _log(f"   worktree  : {mat.working_dir}")
        _log(f"   seeded    : {_git(mat.working_dir, 'ls-files')!r}")

        ledger.tasks.submit(Task(id="t1", intent=_TASK))
        assign_task(ledger, "t1", "bex")
        # Slice 2 — the evidence floor. A single backend engineer lands SOLO, gated not on a transient
        # `pytest` run but on the DURABLE proof bundle: the DoD passes only when a `test_evidence/`
        # manifest exists in the worktree with an all-green verdict. So the model must call the
        # `test_evidence` tool (which runs the gates + writes the bundle) — "it was tested" is a file on
        # disk the DoD greps, not a claim. No reviewer needed — a single-beat Command DoD over the bundle.
        ledger.dod.create(
            "t1",
            Verifier.command(
                "test -f test_evidence/manifest.json && "
                'grep -q \'"verdict": "pass"\' test_evidence/manifest.json',
                artifact_class="pr",
            ),
        )
        _log(
            "\n2. TASK assigned (DoD: green test_evidence/ bundle, gates solo — no reviewer)\n   t1: "
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
        ):  # one deliverable beat gates on pytest + lands; headroom for self-repair
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
        shipped = (company_main / "slugify.py").exists() and "slugify" in (
            (company_main / "slugify.py").read_text(encoding="utf-8")
            if (company_main / "slugify.py").exists()
            else ""
        )
        if landed:
            _log(
                f"   ★ PR ARTIFACT LANDED: {artifacts[0].type.value} ref={artifacts[0].resource_ref}"
            )
            _log(f"   company main slugify.py present + integrated: {shipped}")
        else:
            _log("   no artifact landed (DoD not green this run — see run/DoD status above).")

        ok = landed and shipped and final is not None and final.status is TaskStatus.DONE
        _log(
            "\n   → PASS: backend_engineer shipped a proven PR."
            if ok
            else "\n   → FAIL: nothing landed."
        )
        return 0 if ok else 1
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
