"""Backend Engineer real-system verification (spec §16 Slice 3) — one keyed beat, an independent grader.

Slices 1-2 proved the engineer builds and records a green unit bundle. But green unit tests only prove
the code compiles and the mocks pass — not that the service *starts and answers over a socket*. This
example proves the uplift: the engineer builds a small HTTP service, records the unit bundle, then
DELEGATES to its ``api_verifier`` subagent — an independent grader that boots the service on a real
localhost port and probes it over real HTTP, writing a durable ``api_verdict.json`` and returning a
typed ``ApiTestVerdict``. The DoD gates on BOTH a green ``test_evidence`` bundle AND a passing verdict,
so "it runs" is proven by a live socket, judged by something other than the author.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/backend_engineer_api_verify_smoke.py

Skips cleanly (exit 0) when those env vars are unset. Exits non-zero if keyed but the beat did not land
a service proven to run — a real assertion, not a demo.
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
    "Build a tiny HTTP service in app.py using ONLY the Python standard library (http.server) — no "
    "pip installs. It must start with `python app.py` and listen on the port in the PORT environment "
    "variable (default 8000). It exposes two GET routes: `/health` returns 200 with the body `ok`; "
    "`/slugify?s=<text>` returns 200 with the slug of <text> — lowercased, every run of "
    "non-alphanumeric characters replaced by a single '-', with leading/trailing '-' stripped "
    "(e.g. /slugify?s=Hello,%20World! returns `hello-world`). Put the slug logic in a slugify(s: str) "
    "-> str function in slugify.py and add a pytest test in test_slugify.py asserting "
    "slugify('Hello, World!') == 'hello-world'. Keep it dependency-free."
)


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


class _TraceBus(EventBus):
    """Prints tool calls + the verdict, so the build → prove → api_verify loop is visible."""

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
    """A tiny valid Python repo the Backend Engineer probes + grows into a service (a real pytest repo)."""
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text(
        "# demo service\n\nRun with `python app.py` (honours the PORT env var).\n", encoding="utf-8"
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

    base = Path(tempfile.mkdtemp(prefix="chorus-backend-eng-apiverify-"))
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
        _log("1. EMPLOYEE — materialized as backend_engineer (spec §16 Slice 3 — API-Verifier)")
        _log(f"   tools     : {', '.join(cfg.tools)}")
        _log(f"   subagents : {', '.join(sa.name for sa in cfg.subagents)}")
        _log(f"   worktree  : {mat.working_dir}")

        ledger.tasks.submit(Task(id="t1", intent=_TASK))
        assign_task(ledger, "t1", "bex")
        # The Slice-3 floor: a green unit bundle is not enough for a running service. The DoD passes
        # only when BOTH proofs are on disk — the durable test_evidence bundle AND a passing
        # api_verdict.json the (independent) api_verifier subagent wrote after booting + probing it.
        ledger.dod.create(
            "t1",
            Verifier.command(
                "test -f test_evidence/manifest.json && "
                'grep -q \'"verdict": "pass"\' test_evidence/manifest.json && '
                "test -f api_verdict.json && "
                "grep -q '\"passed\": *true' api_verdict.json",
                artifact_class="pr",
            ),
        )
        _log(
            "\n2. TASK assigned (DoD: green test_evidence bundle AND a passing api_verdict.json, "
            "gates solo)\n   t1: " + _TASK
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

        for n in range(1, 4):  # build + unit + api_verify + land; headroom for a self-repair pass
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
        verdict = company_main / "api_verdict.json"
        shipped = (
            app.exists() and verdict.exists() and '"passed"' in verdict.read_text(encoding="utf-8")
        )
        if landed:
            _log(
                f"   ★ PR ARTIFACT LANDED: {artifacts[0].type.value} ref={artifacts[0].resource_ref}"
            )
            _log(f"   service app.py present: {app.exists()}")
            _log(f"   api_verdict.json landed (independent grader ran): {verdict.exists()}")
            if verdict.exists():
                _log(f"   verdict: {verdict.read_text(encoding='utf-8')[:200]}")
        else:
            _log("   no artifact landed (DoD not green this run — see run/DoD status above).")

        ok = landed and shipped and final is not None and final.status is TaskStatus.DONE
        _log(
            "\n   → PASS: backend_engineer shipped a service PROVEN TO RUN by an independent grader."
            if ok
            else "\n   → FAIL: nothing landed / the running service was not proven."
        )
        return 0 if ok else 1
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
