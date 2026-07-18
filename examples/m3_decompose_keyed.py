"""Keyed M3 checkpoint — watch a real manager beat call ``decompose`` and fan a task out (Path A).

Proves the whole capability seam end to end with a live model: a manager is materialized as its role
(the chorus ``decompose`` tool registered into its dream harness, bound to the ledger), runs one real
beat, and — because the model actually calls the tool mid-beat — the ledger gains two assigned child
tasks gating their parent. No kernel park/integrate yet; this checkpoint proves only model → dream tool
→ CapabilityService → ledger.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/m3_decompose_keyed.py

Skips cleanly (exit 0) when those env vars are unset.
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

from chorus.events import Event, EventKind
from chorus.ledger import Ledger, Run, RunStatus, Task, TaskStatus
from chorus.lifecycle import assign_task
from chorus.observability import EventBus
from chorus.roles import RoleRegistry, default_roles, role_beat_config
from chorus.workforce import Employee
from chorus_cli._beats import default_pricing_from_env
from chorus_harness import EmployeeHarnessFactory

_PARENT_INTENT = (
    "You manage two engineers: 'ada' and 'bob'. Break this feature into exactly two subtasks and "
    "delegate them with the decompose tool — call decompose once with both children. Give the API "
    "work the label 'api' assigned to ada, and the UI work the label 'ui' assigned to bob; make 'ui' "
    "depend_on 'api'. The feature: build a small movie-rating web page with a JSON API behind it."
)


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


class LoggingBus(EventBus):
    """Print every beat event so the planner → decompose tool call → evaluator loop is visible."""

    def __init__(self) -> None:
        super().__init__(log_path=None)
        self._buf = ""

    def emit(self, event: Event) -> None:
        p = event.payload
        if event.kind is EventKind.RUN_TEXT:
            self._buf += str(p.get("text", ""))
            while "\n" in self._buf:
                head, self._buf = self._buf.split("\n", 1)
                if head.strip():
                    _log(f"    · {head.strip()[:200]}")
            return
        if event.kind is EventKind.RUN_TOOL_USE:
            _log(f"    → TOOL {p.get('tool', '?')}  {str(p.get('input', ''))[:220]}")
        elif event.kind is EventKind.RUN_TOOL_RESULT:
            tag = "ERR" if p.get("is_error") else "ok"
            _log(f"    ← {p.get('tool', '?')} [{tag}]  {str(p.get('content', ''))[:200]}")
        elif event.kind is EventKind.RUN_EVALUATED:
            _log(f"    ⊢ evaluated: {p.get('outcome', p)}")


def _seed_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text("# movie app\n", encoding="utf-8")
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

    base = Path(tempfile.mkdtemp(prefix="chorus-m3-"))
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
            ledger=ledger,  # the manager's decompose tool mutates this live
        )
        ledger.employees.create(Employee(id="moe", name="Moe", role="manager"))
        ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
        ledger.employees.create(Employee(id="bob", name="Bob", role="engineer"))

        cfg = role_beat_config(registry.get("manager").manifest)
        mat = factory.materialize(ledger.employees.get("moe"))  # type: ignore[arg-type]
        _log("=" * 72)
        _log("1. MANAGER materialized as its role (spec 06 §2 → dream)")
        _log(f"   tools     : {', '.join(cfg.tools)}   (decompose = chorus capability tool)")
        _log(f"   worktree  : {mat.working_dir}")

        ledger.tasks.submit(Task(id="feature", intent=_PARENT_INTENT, status=TaskStatus.TODO))
        assign_task(ledger, "feature", "moe")
        run_id = "run_moe_1"
        ledger.runs.create(
            Run(id=run_id, employee_id="moe", task_id="feature", status=RunStatus.RUNNING)
        )
        _log("\n2. PARENT task assigned to the manager")
        _log(f"   feature → moe   (run {run_id})")

        _log("\n3. ONE real manager beat — watch it call decompose")
        outcome = asyncio.run(
            mat.runner.run_task(
                task_id="feature", run_id=run_id, intent=_PARENT_INTENT, observer=LoggingBus().emit
            )
        )
        _log(f"\n   beat verdict: passed={outcome.passed}  {outcome.summary}")

        _log("\n" + "=" * 72)
        _log("4. LEDGER AFTER THE BEAT — did decompose really fan it out?")
        children = [t for t in _all_tasks(ledger) if t.parent_id == "feature"]
        for child in sorted(children, key=lambda t: t.id):
            _log(
                f"   child {child.id}: assignee={child.assignee_employee_id!r} status={child.status.value}"
            )
            _log(f"          intent: {child.intent[:90]}")
        blockers = ledger.dependencies.unresolved_blockers("feature")
        _log(f"   parent 'feature' waits on: {blockers}")
        woken = {w.payload.get("task_id") for w in ledger.wakes.queued()}
        _log(f"   children woken (dispatchable): {sorted(c.id for c in children if c.id in woken)}")

        # The Slice 1 plumbing claim: the manager's decompose tool ran live and mutated the ledger —
        # ≥2 real assigned children, each gating the parent, each woken for dispatch. (The manager's
        # *lifecycle* — park-after-delegate, integrate — is steps 4/5; this proves the capability seam.)
        reports = {"ada", "bob"}
        assigned = all(c.assignee_employee_id in reports for c in children)
        gated = set(blockers) == {c.id for c in children}
        all_woken = all(c.id in woken for c in children)
        ok = len(children) >= 2 and assigned and gated and all_woken
        _log(
            "\n"
            + (
                "✅ PASS — decompose ran live: parent fanned out to assigned, gated, woken children"
                if ok
                else "❌ the capability did not fan out as expected (see the trace above)"
            )
        )
        return 0 if ok else 1
    finally:
        ledger.close()


def _all_tasks(ledger: Ledger) -> list[Task]:
    rows = ledger.tasks._conn.execute("SELECT id FROM task").fetchall()
    return [t for t in (ledger.tasks.get(str(r[0])) for r in rows) if t is not None]


if __name__ == "__main__":
    raise SystemExit(main())
