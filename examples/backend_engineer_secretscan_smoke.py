"""Backend Engineer safety floor (spec §09) — remediate a hardcoded secret, proven by secret_scan.

The spec's "governed against the unsafe service": no service lands with a credential baked into the
diff. This example is self-verifying — the seeded repo ALREADY leaks a hardcoded AWS key. The engineer
must remove it (read the key from the environment instead), keep behaviour identical, and PROVE no
secrets remain by running the `secret_scan` tool until its durable `security_scan/report.json` is clean.
The DoD gates on a green `test_evidence` bundle AND a clean secret-scan report, so the scan must go
dirty -> clean — proving both that the tool catches the leak and that the fix removed it.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/backend_engineer_secretscan_smoke.py

Skips cleanly (exit 0) when those env vars are unset. Exits non-zero if keyed but the secret was not
provably removed — a real assertion, not a demo.
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

# The canonical AWS documentation example key — safe to commit, and it trips the aws-access-key-id rule.
_LEAKED_KEY = "AKIAIOSFODNN7EXAMPLE"

_TASK = (
    "config.py hardcodes an AWS credential (a real security defect). Remove the hardcoded secret: read "
    "the key from the API_KEY environment variable instead (os.environ), keeping the public behaviour "
    "of api_key() identical. Do not weaken the existing test. Then PROVE no secrets remain — run the "
    "`secret_scan` tool over the worktree until its security_scan/report.json is clean. Keep it "
    "dependency-free (standard library only)."
)


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


class _TraceBus(EventBus):
    """Prints tool calls + the verdict, so the remediate -> prove -> secret_scan loop is visible."""

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
    """A tiny valid Python repo that ALREADY leaks a hardcoded secret in config.py."""
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "config.py").write_text(
        f'# TODO: this hardcoded credential must not ship\nAPI_KEY = "{_LEAKED_KEY}"\n\n\n'
        "def api_key() -> str:\n    return API_KEY\n",
        encoding="utf-8",
    )
    (path / "test_config.py").write_text(
        "from config import api_key\n\n\ndef test_api_key_is_non_empty() -> None:\n"
        "    assert api_key()\n",
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

    base = Path(tempfile.mkdtemp(prefix="chorus-backend-eng-secretscan-"))
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
        _log("1. EMPLOYEE — materialized as backend_engineer (spec §09 — secret_scan safety floor)")
        _log(f"   tools     : {', '.join(cfg.tools)}")
        _log(f"   worktree  : {mat.working_dir}")
        _log(f"   seeded a hardcoded secret in config.py: {_LEAKED_KEY}")

        ledger.tasks.submit(Task(id="t1", intent=_TASK))
        assign_task(ledger, "t1", "bex")
        # The safety floor: a green unit bundle AND a CLEAN secret-scan report. The report starts dirty
        # (the seed leaks a key), so the DoD passes only once the engineer removed the secret and the
        # scan confirms it — proving both the detector and the fix.
        ledger.dod.create(
            "t1",
            Verifier.command(
                "test -f test_evidence/manifest.json && "
                'grep -q \'"verdict": "pass"\' test_evidence/manifest.json && '
                "test -f security_scan/report.json && "
                "grep -q '\"clean\": *true' security_scan/report.json",
                artifact_class="pr",
            ),
        )
        _log(
            "\n2. TASK assigned (DoD: green bundle AND a clean security_scan report)\n   t1: "
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

        for n in range(1, 4):  # remediate + prove + scan + land; headroom for a repair pass
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
        config = company_main / "config.py"
        report = company_main / "security_scan" / "report.json"
        secret_gone = config.exists() and _LEAKED_KEY not in config.read_text(encoding="utf-8")
        scan_clean = report.exists() and '"clean": true' in report.read_text(encoding="utf-8")
        if landed:
            _log(
                f"   ★ PR ARTIFACT LANDED: {artifacts[0].type.value} ref={artifacts[0].resource_ref}"
            )
            _log(f"   hardcoded key removed from config.py: {secret_gone}")
            _log(f"   security_scan/report.json is clean: {scan_clean}")
        else:
            _log("   no artifact landed (DoD not green this run — see run/DoD status above).")

        ok = (
            landed
            and secret_gone
            and scan_clean
            and final is not None
            and final.status is (TaskStatus.DONE)
        )
        _log(
            "\n   → PASS: backend_engineer removed the secret and proved it clean with secret_scan."
            if ok
            else "\n   → FAIL: the hardcoded secret was not provably removed."
        )
        return 0 if ok else 1
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
