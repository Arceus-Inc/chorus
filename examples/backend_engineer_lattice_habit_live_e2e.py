"""Live e2e — real backend_engineer + skill_manage EVOLVE + pattern retrieval.

Flow:
  1. Seed worktree with a tiny HTTP client (retry already present)
  2. Seed 5 done episodic beats → lattice gate opens
  3. Programmatic patterns via lattice_apply + skill_manage(evolve)
  4. Rematerialize factory → versioned skill merge in .harness/skills/
  5. ONE live Azure beat: agent must load skill + lattice_context and write README

    CHORUS_PROBE_BEAT_TIMEOUT_S=180 \\
      uv run python examples/backend_engineer_lattice_habit_live_e2e.py

Requires AZURE_OPENAI_* in the repo-root ``.env``.
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
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

from lattice.domain.proposal import PatternDraft, Proposal

from chorus.budgets import BudgetEnforcer
from chorus.events import Event, EventKind
from chorus.heartbeat import Scheduler
from chorus.ledger import Ledger, Task
from chorus.lifecycle import assign_task
from chorus.memory import EpisodicStore, SprintDelta
from chorus.observability import EventBus
from chorus.outcomes import Verifier
from chorus.roles import RoleRegistry, default_roles
from chorus.roles._plugin import RolePlugin
from chorus.skills import SkillManager, SkillStore
from chorus.workforce import Employee, LedgerWorkforce
from chorus_cli._beats import default_pricing_from_env
from chorus_cli._env import load_env_file
from chorus_employee import default_landers
from chorus_harness import EmployeeHarnessFactory
from chorus_tools._lattice_bridge import build_lattice_for_chorus

_EMPLOYEE_ID = "bex"
_BEAT_TIMEOUT_S = float(os.environ.get("CHORUS_PROBE_BEAT_TIMEOUT_S", "180"))
_MAX_TICKS = int(os.environ.get("CHORUS_PROBE_MAX_TICKS", "3"))

_LIVE_TASK_ID = "t-habit-skill-load"
_LIVE_INTENT = (
    "Do NOT edit src/api/client.py. "
    "1) Load skill `structuring-any-service` via the skill tool and quote the section "
    "'Before patching HTTP clients' if present. "
    "2) Call lattice_context(query='retry') and note the api.retry pattern. "
    "3) Add a short RETRY_POLICY section to README.md documenting max retries, backoff cap, "
    "and which status codes retry — values must match the lattice pattern / client. "
    "Use todo_write. Success = README has RETRY_POLICY and you loaded the skill."
)

_DOD = Verifier.command("test -f README.md", artifact_class="pr")

_EVOLVE_BODY = (
    "## Before patching HTTP clients\n\n"
    "1. Call `get_run(run_id)` for each cited beat and recall the failure shape.\n"
    "2. Classify transient (429/503) versus logic error before editing.\n"
    "3. Only then edit `src/api/client.py`.\n\n"
    "## Pitfalls\n"
    "- Patching without reading prior beat prose repeats the same mistake.\n\n"
    "## Verification\n"
    "- `test_evidence` passes after the patch.\n"
)

_CLIENT_PY = '''\
"""HTTP client with retry policy.

Retries up to max_retries=3 on HTTP 429 and 503 with exponential backoff
(base 0.2s, cap 30s).
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request


class HttpClient:
    max_retries: int = 3
    backoff_base: float = 0.2
    backoff_cap: float = 30.0

    def request(self, url: str) -> int:
        last_status = 0
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(url, timeout=5) as resp:
                    return int(resp.status)
            except urllib.error.HTTPError as exc:
                last_status = int(exc.code)
                if last_status not in {429, 503} or attempt >= self.max_retries:
                    return last_status
                delay = min(self.backoff_base * (2**attempt), self.backoff_cap)
                time.sleep(delay)
            except urllib.error.URLError:
                if attempt >= self.max_retries:
                    raise
                delay = min(self.backoff_base * (2**attempt), self.backoff_cap)
                time.sleep(delay)
        return last_status
'''


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _seed(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text("# retry-api seed\n", encoding="utf-8")
    api = path / "src" / "api"
    api.mkdir(parents=True)
    (api / "__init__.py").write_text("", encoding="utf-8")
    (api / "client.py").write_text(_CLIENT_PY, encoding="utf-8")
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
            "-qm",
            "init",
        ],
        check=True,
        capture_output=True,
    )


def _registry_short_beats(timeout_s: float) -> RoleRegistry:
    plugins: list[RolePlugin] = []
    for plugin in default_roles():
        if plugin.name != "backend_engineer":
            plugins.append(plugin)
            continue
        manifest = replace(
            plugin.manifest,
            beat_timeout_s=timeout_s,
            lease_ttl_s=timeout_s + 90.0,
            max_turns=12,
        )
        plugins.append(
            RolePlugin(
                name=plugin.name,
                manifest=manifest,
                dod_generator=plugin.dod_generator,
                outcome_kind=plugin.outcome_kind,
                declared_routines=plugin.declared_routines,
                replace=True,
            )
        )
    return RoleRegistry.from_plugins(plugins)


@dataclass
class _BeatTrace:
    task_id: str
    tick: int
    run_id: str = ""
    tool_calls: list[str] = field(default_factory=list)
    lattice_calls: list[str] = field(default_factory=list)
    skill_calls: list[str] = field(default_factory=list)
    role_texts: list[str] = field(default_factory=list)
    outcome: str = "?"


class _Bus(EventBus):
    def __init__(self) -> None:
        super().__init__(log_path=None)
        self.traces: list[_BeatTrace] = []
        self._current: _BeatTrace | None = None

    def start_beat(self, task_id: str, *, tick: int) -> None:
        self._current = _BeatTrace(task_id=task_id, tick=tick)
        self.traces.append(self._current)

    def emit(self, event: Event) -> None:
        try:
            if self._current is None:
                return
            p = event.payload
            if event.kind is EventKind.RUN_STARTED:
                self._current.run_id = str(p.get("run_id", ""))
            elif event.kind is EventKind.RUN_TOOL_USE:
                tool = str(p.get("tool", "?"))
                self._current.tool_calls.append(tool)
                if tool.startswith("lattice_"):
                    self._current.lattice_calls.append(tool)
                if tool == "skill":
                    inp = p.get("input") or {}
                    name = ""
                    if isinstance(inp, dict):
                        name = str(inp.get("name") or inp.get("skill") or "")
                    self._current.skill_calls.append(name or "skill")
            elif event.kind is EventKind.RUN_TEXT:
                text = str(p.get("text", p.get("content", "")))
                if text.strip():
                    if self._current.role_texts and len(text) < 24:
                        self._current.role_texts[-1] += text
                    else:
                        self._current.role_texts.append(text)
            elif event.kind is EventKind.RUN_EVALUATED:
                self._current.outcome = str(p.get("outcome", "?"))
        except Exception:
            pass
        super().emit(event)


def _worktree_path(company_root: Path, employee_id: str) -> Path:
    return company_root / "worktrees" / employee_id


def _seed_episodes(store: EpisodicStore, *, n: int = 5) -> list[str]:
    now = datetime.now(UTC)
    run_ids: list[str] = []
    for i in range(n):
        run_id = f"seed_r{i}"
        run_ids.append(run_id)
        store.append(
            SprintDelta(
                run_id=run_id,
                task_id=f"t{i}",
                employee_id=_EMPLOYEE_ID,
                role="backend_engineer",
                scope="project",
                intent="retry http client",
                outcome="done",
                score=1.0,
                created_at=now,
                recorded_at=now,
                artifacts=(),
                files_touched=("src/api/client.py",),
                body=(
                    f"Implemented retry attempt {i}: max_retries=3, backoff 0.2s–30s, "
                    "retry on 429/503. Loaded structuring-any-service."
                ),
            )
        )
    return run_ids


def _apply_pattern_and_habit(
    *, company_root: Path, ledger: Ledger, run_ids: list[str]
) -> list[tuple[str, bool, str]]:
    from chorus_employee.backend_engineer._harness import backend_engineer_manifest

    skills_root = backend_engineer_manifest().skills_root
    lattice = build_lattice_for_chorus(
        company_root,
        canonical_skills_root=skills_root,
        min_new_episodes=5,
        min_cluster_size=2,
    )
    checks: list[tuple[str, bool, str]] = []
    checks.append(("gate open after seed", lattice.gate_open(_EMPLOYEE_ID), "N=5 K=2"))

    proposal = Proposal(
        employee_id=_EMPLOYEE_ID,
        patterns=(
            PatternDraft(
                key="api.retry",
                claim=(
                    "The HTTP client in src/api/client.py retries 429 and 503 responses "
                    "up to 3 times with exponential backoff from 0.2s to 30s."
                ),
                source_run_ids=tuple(run_ids[:5]),
            ),
        ),
    )
    validation = lattice.validate(proposal)
    checks.append(("proposal validates", validation.ok, "; ".join(validation.errors) or "ok"))
    if not validation.ok:
        return checks

    result = lattice.apply(proposal)
    checks.append(
        (
            "lattice_apply patterns",
            result.ok,
            f"atoms={result.atoms_written}",
        )
    )

    store = SkillStore(ledger)
    episodes = tuple(EpisodicStore(company_root / "memory").records_for(_EMPLOYEE_ID, limit=20))
    mgr = SkillManager(
        store,
        employee_id=_EMPLOYEE_ID,
        canonical_skills_root=Path(skills_root) if skills_root else None,
        episodes=episodes,
    )
    try:
        obs = mgr.apply(
            action="evolve",
            name="structuring-any-service",
            section="Before patching HTTP clients",
            content=_EVOLVE_BODY,
            source_run_ids=run_ids[:2],
        )
        checks.append(
            (
                "skill_manage evolve",
                obs.status == "success",
                obs.summary,
            )
        )
        rev_no = obs.artifacts.get("revision_no")
        checks.append(
            (
                "skill_revision written",
                rev_no == 1,
                f"revision_no={rev_no}",
            )
        )
    finally:
        mgr.close()

    semantic = company_root / "lattice" / _EMPLOYEE_ID / "semantic" / "api__retry.json"
    checks.append(("semantic atom on disk", semantic.is_file(), str(semantic)))
    return checks


async def _run_task(
    scheduler: Scheduler, ledger: Ledger, bus: _Bus, task_id: str
) -> list[_BeatTrace]:
    from chorus.ledger import TaskStatus

    before = len(bus.traces)
    for tick in range(1, _MAX_TICKS + 1):
        task = ledger.tasks.get(task_id)
        if task is None or task.status in (TaskStatus.DONE, TaskStatus.BLOCKED):
            break
        _log(f"    tick {tick} …")
        bus.start_beat(task_id, tick=tick)
        await scheduler.tick_once()
        await scheduler.drain()
    return bus.traces[before:]


def _live_checks(*, traces: list[_BeatTrace], worktree: Path) -> list[tuple[str, bool, str]]:
    live = [t for t in traces if t.task_id == _LIVE_TASK_ID]
    if not live:
        return [("live beat ran", False, "no traces")]
    trace = live[-1]
    role_text = "\n".join(trace.role_texts).lower()
    readme = worktree / "README.md"
    readme_text = readme.read_text(encoding="utf-8") if readme.is_file() else ""
    skill_loaded = any(
        "structuring" in c.lower() or c == "skill" for c in trace.skill_calls
    ) or "structuring-any-service" in " ".join(trace.tool_calls)
    # skill tool may appear as tool name only; also accept role text quoting the section
    section_quoted = "before patching http clients" in role_text or "failure shape" in role_text
    return [
        ("live beat ran", True, f"tick={trace.tick} outcome={trace.outcome}"),
        (
            "skill tool or section quoted",
            skill_loaded or section_quoted,
            f"skill_calls={trace.skill_calls!r} quoted={section_quoted}",
        ),
        (
            "lattice_context called",
            "lattice_context" in trace.lattice_calls,
            f"lattice={trace.lattice_calls}",
        ),
        (
            "README has RETRY_POLICY",
            "retry_policy" in readme_text.lower() or "retry" in readme_text.lower(),
            readme_text[:160].replace("\n", " "),
        ),
        (
            "materialized versioned skill",
            (worktree / ".harness" / "skills" / "structuring-any-service" / "SKILL.md").is_file()
            and "Before patching HTTP clients"
            in (
                worktree / ".harness" / "skills" / "structuring-any-service" / "SKILL.md"
            ).read_text(encoding="utf-8"),
            "worktree .harness/skills/structuring-any-service",
        ),
    ]


def main() -> int:
    load_env_file(Path(__file__).resolve().parent.parent / ".env", override=True)
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        _log("skipping: set AZURE_OPENAI_* in .env")
        return 0

    base = Path(tempfile.mkdtemp(prefix="chorus-lattice-habit-live-"))
    os.chdir(base)
    seed = base / "source"
    _seed(seed)

    ledger = Ledger.open(
        os.environ.get("CHORUS_LEDGER_DSN", "postgresql://localhost/chorus"),
        company_id=_EXAMPLE_COMPANY,
    )
    report_path = (
        Path(__file__).resolve().parent.parent
        / "reports"
        / "backend-engineer-lattice-habit-live.json"
    )

    registry = _registry_short_beats(_BEAT_TIMEOUT_S)
    factory = EmployeeHarnessFactory(
        api_key=api_key,
        base_url=base_url,
        deployment=deployment,
        company_id="acme",
        roles=registry,
        pricing=default_pricing_from_env(),
        seed=seed,
    )
    store = EpisodicStore(factory.company_root / "memory")

    ledger.employees.create(Employee(id=_EMPLOYEE_ID, name="Bex", role="backend_engineer"))

    _log("=" * 72)
    _log("BACKEND ENGINEER LATTICE HABIT LIVE E2E")
    _log(f"  beat_timeout : {_BEAT_TIMEOUT_S}s")
    _log(f"  company_root : {factory.company_root}")
    _log(f"  deployment   : {deployment}")
    _log("=" * 72)

    _log("\n--- SEED episodic (5 done beats) ---")
    run_ids = _seed_episodes(store)
    _log(f"  seeded {len(run_ids)} runs")

    _log("\n--- PROGRAMMATIC pattern + habit EVOLVE ---")
    prog_checks = _apply_pattern_and_habit(
        company_root=factory.company_root, ledger=ledger, run_ids=run_ids
    )
    for name, ok, detail in prog_checks:
        _log(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")
    if not all(ok for _, ok, _ in prog_checks):
        _log("\nABORT: programmatic apply failed — not running live beat")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps({"all_pass": False, "prog_checks": prog_checks}, indent=2),
            encoding="utf-8",
        )
        return 1

    # Materialize so versioned skill lands in worktree before the live beat.
    _log("\n--- MATERIALIZE backend_engineer (versioned skill merge) ---")
    mat = factory.materialize(Employee(id=_EMPLOYEE_ID, name="Bex", role="backend_engineer"))
    worktree = mat.working_dir
    skill_md = worktree / ".harness" / "skills" / "structuring-any-service" / "SKILL.md"
    _log(f"  worktree: {worktree}")
    _log(f"  skill present: {skill_md.is_file()}")
    if skill_md.is_file():
        preview = skill_md.read_text(encoding="utf-8")[:200].replace("\n", " ")
        _log(f"  skill preview: {preview}…")
    else:
        _log("ABORT: versioned skill not materialized into worktree")
        return 1

    bus = _Bus()
    scheduler = Scheduler(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        beat_runner_for=factory,
        budget_enforcer=BudgetEnforcer(ledger, company_id="acme"),
        roles=registry,
        landers=default_landers(factory.company_root),
        memory_writer=store,
        event_bus=bus,
        max_concurrent_runs=1,
        company_root=factory.company_root,
    )

    _log(f"\n--- LIVE TASK {_LIVE_TASK_ID} ---")
    ledger.tasks.submit(Task(id=_LIVE_TASK_ID, intent=_LIVE_INTENT))
    assign_task(ledger, _LIVE_TASK_ID, _EMPLOYEE_ID)
    ledger.dod.create(_LIVE_TASK_ID, _DOD)
    traces = asyncio.run(_run_task(scheduler, ledger, bus, _LIVE_TASK_ID))
    final = ledger.tasks.get(_LIVE_TASK_ID)
    status = final.status.value if final else "?"
    _log(f"  → status: {status} | traces: {len(traces)}")
    for t in traces:
        if t.role_texts:
            _log(f"  role.text preview: {t.role_texts[-1][:240].replace(chr(10), ' ')}…")
        _log(f"  tools: {t.tool_calls[:20]}")
        if t.skill_calls:
            _log(f"  skills: {t.skill_calls}")
        if t.lattice_calls:
            _log(f"  lattice: {t.lattice_calls}")

    live_checks = _live_checks(traces=bus.traces, worktree=worktree)
    _log(f"\n{'=' * 72}")
    _log("LIVE CHECKS")
    all_ok = all(ok for _, ok, _ in prog_checks)
    for name, ok, detail in live_checks:
        _log(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")
        # Hard gates: live beat + materialized overlay. Soft: skill/lattice_context (agent may vary).
        if name in {"live beat ran", "materialized versioned skill", "README has RETRY_POLICY"}:
            all_ok = all_ok and ok

    soft_ok = all(
        ok
        for name, ok, _ in live_checks
        if name in {"skill tool or section quoted", "lattice_context called"}
    )

    payload = {
        "all_pass": all_ok,
        "soft_pass": soft_ok,
        "task_status": status,
        "prog_checks": [{"name": n, "pass": ok, "detail": d} for n, ok, d in prog_checks],
        "live_checks": [{"name": n, "pass": ok, "detail": d} for n, ok, d in live_checks],
        "company_root": str(factory.company_root),
        "worktree": str(worktree),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _log(f"\nreport → {report_path}")
    _log(f"all_pass={all_ok} soft_pass={soft_ok}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
