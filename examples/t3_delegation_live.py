"""T3 live delegation: two coarse parallel backend chunks and verified integration."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from chorus.events import Event, EventKind
from chorus.governance import ManagementAuthorityService
from chorus.heartbeat import Scheduler
from chorus.ledger import (
    ActivityVerb,
    DelegationContract,
    DelegationContractStatus,
    ExecutionMode,
    Goal,
    ManagementProfile,
    SqliteLedger,
    Task,
    TaskStatus,
)
from chorus.lifecycle import MissionTeamPolicy, assign_task
from chorus.observability import EventBus
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee, LedgerWorkforce
from chorus_cli._beats import default_pricing_from_env
from chorus_harness import EmployeeHarnessFactory

_ROOT_TASK_ID = "t3-backends"
_GOAL_ID = "goal-t3-backends"
_LEAD_ID = "backend-lead"
_LINKS_IC_ID = "links-ic"
_ANALYTICS_IC_ID = "analytics-ic"
_COMPANY_ID = "linkport-t3"
_BUDGET_CEILING_CENTS = 700_000
_INTENT = (
    "Build the complete Linkport links backend and analytics backend as exactly TWO coarse, "
    "parallel delivery children. This is one delegation root. First call team_read, then call "
    "decompose exactly once with exactly these module-sized assignments: (1) assign links-ic the "
    "whole `links.py` module with base62 short-code generation, SQLite persistence, collision-safe "
    "create/resolve, optional TTL, and comprehensive `tests/test_links.py`; (2) assign analytics-ic "
    "the whole `analytics.py` module with SQLite-backed idempotent click ingestion keyed by event "
    "id, total/per-day/top-referrer statistics, and comprehensive `tests/test_analytics.py`. Each "
    "child owns its complete module and tests, must follow behavior-specific RED-before-production "
    "TDD, and must run `python gate_check.py`. Do not create plan-only, per-file, per-function, or "
    "third children. The seed owns shared gate/config files; children must not rewrite them. After "
    "both children land, inspect the integration packet and accept only when both complete modules, "
    "tests, independent reviews, and the integrated company gate are credible. Never perform the "
    "children's implementation in the lead beat."
)
_OBJECTIVE_RUBRIC = (
    "Independently verify exactly two terminal delivery children: one complete links backend and "
    "one complete analytics backend, each with behavior tests and machine-owned review evidence. "
    "Inspect the subtree evidence and integrated diff, run `python gate_check.py` when available, "
    "and pass only if links.py, analytics.py, both dedicated test suites, and the combined gate are "
    "green. The verifier must not trust the lead's acceptance claim."
)
_GATE_CHECK = '''"""Portable Linkport project gate."""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    for command in (
        (sys.executable, "-m", "pytest", "-q"),
        (sys.executable, "-m", "ruff", "check", "."),
    ):
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
_PYPROJECT = """[project]
name = "linkport-backends"
version = "0.1.0"
requires-python = ">=3.11"

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py311"
"""


@dataclass(frozen=True)
class Invariant:
    """One independently checkable T3 acceptance condition."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class RunWindow:
    """Wall-clock interval for one employee-owned child beat."""

    task_id: str
    principal_id: str
    started_at: float
    finished_at: float


@dataclass(frozen=True)
class T3Snapshot:
    """Pure projection used to judge a completed T3 live run."""

    root_status: str
    child_ids: tuple[str, ...]
    child_statuses: tuple[str, ...]
    child_assignees: tuple[str, ...]
    child_scopes: tuple[str, ...]
    employee_run_windows: tuple[RunWindow, ...]
    contract_status_history: tuple[str, ...]
    parent_verifier_principals: tuple[str, ...]
    parent_verifier_statuses: tuple[str, ...]
    parent_verdict_passed: bool
    child_prs_merged: tuple[bool, ...]
    company_branch: str
    gate_exit_code: int
    shipped_paths: tuple[str, ...]
    child_tdd_valid: tuple[bool, ...]
    child_review_valid: tuple[bool, ...]
    evaluator_retrieval_complete: bool
    task_count: int
    tool_use_count: int
    tool_result_count: int
    all_tool_results_lossless: bool
    event_count: int
    trace_count: int
    secret_redaction_safe: bool


def _contains_in_order(values: tuple[str, ...], expected: tuple[str, ...]) -> bool:
    cursor = iter(values)
    return all(any(value == wanted for value in cursor) for wanted in expected)


def _parallel(windows: tuple[RunWindow, ...]) -> bool:
    if len(windows) != 2 or any(window.finished_at <= window.started_at for window in windows):
        return False
    first, second = windows
    return max(first.started_at, second.started_at) < min(first.finished_at, second.finished_at)


def evaluate_invariants(snapshot: T3Snapshot) -> tuple[Invariant, ...]:
    """Judge T3 from immutable evidence without trusting model prose."""
    scopes = tuple(sorted(snapshot.child_scopes))
    two_coarse = (
        len(snapshot.child_ids) == 2
        and len(set(snapshot.child_ids)) == 2
        and snapshot.task_count == 3
        and scopes == ("analytics", "links")
        and len(set(snapshot.child_assignees)) == 2
        and snapshot.child_statuses == ("done", "done")
    )
    windows_match = {window.task_id for window in snapshot.employee_run_windows} == set(
        snapshot.child_ids
    ) and {window.principal_id for window in snapshot.employee_run_windows} == set(
        snapshot.child_assignees
    )
    phases_ok = _contains_in_order(
        snapshot.contract_status_history,
        ("delegated", "integrating", "verifying", "done"),
    )
    verifier_ok = (
        snapshot.root_status == "done"
        and snapshot.parent_verifier_principals == ("system-verifier",)
        and snapshot.parent_verifier_statuses == ("succeeded",)
        and snapshot.parent_verdict_passed
    )
    landed = snapshot.child_prs_merged == (True, True) and snapshot.company_branch == "main"
    tests = tuple(
        path
        for path in snapshot.shipped_paths
        if Path(path).suffix == ".py" and "test" in Path(path).name.lower()
    )
    modules = (
        "links.py" in snapshot.shipped_paths
        and "analytics.py" in snapshot.shipped_paths
        and any("links" in path for path in tests)
        and any("analytics" in path for path in tests)
    )
    quality_provenance = (
        snapshot.child_tdd_valid == (True, True)
        and snapshot.child_review_valid == (True, True)
        and snapshot.evaluator_retrieval_complete
    )
    evidence_ok = (
        snapshot.tool_use_count > 0
        and snapshot.tool_use_count == snapshot.tool_result_count
        and snapshot.all_tool_results_lossless
        and snapshot.event_count > 0
        and snapshot.trace_count > 0
    )
    return (
        Invariant(
            "exactly two coarse children",
            two_coarse,
            f"children={snapshot.child_ids}, scopes={snapshot.child_scopes}, "
            f"assignees={snapshot.child_assignees}, statuses={snapshot.child_statuses}, "
            f"total tasks={snapshot.task_count}",
        ),
        Invariant(
            "parallel child beats",
            windows_match and _parallel(snapshot.employee_run_windows),
            f"run windows={snapshot.employee_run_windows}",
        ),
        Invariant(
            "delegation phase transitions",
            phases_ok,
            f"contract history={snapshot.contract_status_history}",
        ),
        Invariant(
            "independent subtree verification",
            verifier_ok,
            f"root={snapshot.root_status}, principals={snapshot.parent_verifier_principals}, "
            f"statuses={snapshot.parent_verifier_statuses}, verdict={snapshot.parent_verdict_passed}",
        ),
        Invariant(
            "child PRs landed",
            landed,
            f"merged={snapshot.child_prs_merged}, company branch={snapshot.company_branch!r}",
        ),
        Invariant(
            "both modules landed",
            modules and snapshot.gate_exit_code == 0,
            f"gate exit={snapshot.gate_exit_code}, tracked paths={snapshot.shipped_paths}",
        ),
        Invariant(
            "per-child quality provenance",
            quality_provenance,
            f"TDD={snapshot.child_tdd_valid}, review={snapshot.child_review_valid}, "
            f"evaluator retrieval={snapshot.evaluator_retrieval_complete}",
        ),
        Invariant(
            "lossless monitoring evidence",
            evidence_ok,
            f"tools={snapshot.tool_use_count}/{snapshot.tool_result_count}, "
            f"events={snapshot.event_count}, traces={snapshot.trace_count}",
        ),
        Invariant(
            "secret redaction audit",
            snapshot.secret_redaction_safe,
            f"persisted report/events/traces redacted={snapshot.secret_redaction_safe}",
        ),
    )


def redact_text(text: str, secret_values: tuple[str, ...]) -> str:
    """Remove configured provider secrets before evidence is persisted."""
    redacted = text
    for secret in secret_values:
        if len(secret) >= 8:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def _secret_values() -> tuple[str, ...]:
    names = (
        "AZURE_OPENAI_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "TAVILY_API_KEY",
    )
    return tuple(value for name in names if (value := os.environ.get(name, "")))


def _jsonable(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _json(value: object) -> str:
    return json.dumps(_jsonable(value), indent=2, sort_keys=True, default=str)


def _code_block(text: str, language: str = "") -> str:
    fence = "````" if "```" in text else "```"
    return f"{fence}{language}\n{text}\n{fence}"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _seed_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(
        ["git", "-C", str(path), "init", "-b", "trunk"],
        check=True,
        capture_output=True,
    )
    (path / "gate_check.py").write_text(_GATE_CHECK, encoding="utf-8")
    (path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    (path / "README.md").write_text(
        "# Linkport backends\n\nT3 delegates links and analytics as two parallel chunks.\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "-c",
            "user.name=Linkport T3",
            "-c",
            "user.email=t3@linkport.invalid",
            "commit",
            "-m",
            "seed shared Linkport backend gate",
        ],
        check=True,
        capture_output=True,
    )


def _log(console_path: Path, message: str = "") -> None:
    print(message, flush=True)
    with console_path.open("a", encoding="utf-8") as stream:
        stream.write(message + "\n")


class _Monitor:
    """Lossless runtime observer plus concise console and contract-transition sampling."""

    def __init__(self, ledger: SqliteLedger, console_path: Path) -> None:
        self._ledger = ledger
        self._console_path = console_path
        self.events: list[Event] = []
        self.contract_transitions: list[dict[str, str]] = []

    def capture_contract(self, source: str, *, at: datetime | None = None) -> None:
        contract = self._ledger.delegation_contracts.get(_ROOT_TASK_ID)
        status = contract.status.value if contract is not None else "missing"
        if self.contract_transitions and self.contract_transitions[-1]["status"] == status:
            return
        self.contract_transitions.append(
            {
                "at": (at or datetime.now(UTC)).isoformat(),
                "status": status,
                "source": source,
            }
        )
        _log(self._console_path, f"contract -> {status} ({source})")

    def observe(self, event: Event) -> None:
        self.capture_contract(f"event:{event.kind.value}", at=event.at)
        self.events.append(event)
        if event.kind is EventKind.RUN_STARTED:
            _log(
                self._console_path,
                f"[{event.at.isoformat()}] run started task={event.task_id} "
                f"employee={event.employee_id}",
            )
        elif event.kind is EventKind.RUN_TOOL_USE:
            _log(
                self._console_path,
                f"[{event.at.isoformat()}] tool -> {event.payload.get('tool', '?')} "
                f"role={event.payload.get('role', '?')} task={event.task_id}",
            )
        elif event.kind is EventKind.RUN_TOOL_RESULT:
            result = "error" if event.payload.get("is_error") else "ok"
            _log(
                self._console_path,
                f"[{event.at.isoformat()}] tool <- {event.payload.get('tool', '?')} "
                f"[{result}] task={event.task_id}",
            )
        elif event.kind is EventKind.RUN_EVALUATED:
            _log(self._console_path, f"[{event.at.isoformat()}] evaluated {dict(event.payload)}")
        elif event.kind is EventKind.RUN_DONE:
            _log(self._console_path, f"[{event.at.isoformat()}] run done task={event.task_id}")


def _seed_org(ledger: SqliteLedger) -> tuple[Employee, ...]:
    employees = (
        Employee(id=_LEAD_ID, name="Backend Lead", role="backend_engineer"),
        Employee(
            id=_LINKS_IC_ID,
            name="Links IC",
            role="backend_engineer",
            reports_to=_LEAD_ID,
        ),
        Employee(
            id=_ANALYTICS_IC_ID,
            name="Analytics IC",
            role="backend_engineer",
            reports_to=_LEAD_ID,
        ),
    )
    for employee in employees:
        ledger.employees.create(employee)
    authority = ManagementAuthorityService(ledger)
    profile = authority.upsert_profile(
        ManagementProfile(
            employee_id=_LEAD_ID,
            granted_by_user_id="t3-setup",
            active=True,
            can_lead=True,
            can_subdelegate=False,
            max_delegation_depth=1,
            max_team_size=3,
            allowed_professions=("backend_engineer",),
            spend_limit_cents=_BUDGET_CEILING_CENTS,
        ),
        actor_user_id="t3-setup",
    )
    ledger.goals.create(Goal(id=_GOAL_ID, title="Ship Linkport backend foundations"))
    team_policy = MissionTeamPolicy(ledger)
    team = team_policy.create_for_root(employees[0], _GOAL_ID)
    team_policy.activate(team.id)
    ledger.tasks.submit(
        Task(
            id=_ROOT_TASK_ID,
            intent=_INTENT,
            status=TaskStatus.TODO,
            execution_mode=ExecutionMode.DELEGATION,
            team_id=team.id,
            goal_id=_GOAL_ID,
        )
    )
    authority.create_delegation_contract(
        DelegationContract(
            task_id=_ROOT_TASK_ID,
            team_id=team.id,
            lead_employee_id=_LEAD_ID,
            management_profile_version=profile.version,
            objective_rubric=_OBJECTIVE_RUBRIC,
            can_subdelegate=False,
            max_depth=1,
            max_team_size=3,
            max_direct_children=2,
            spend_limit_cents=_BUDGET_CEILING_CENTS,
            status=DelegationContractStatus.DELEGATED,
        ),
        actor_user_id="t3-setup",
    )
    assign_task(ledger, _ROOT_TASK_ID, _LEAD_ID)
    return employees


async def _drive(
    scheduler: Scheduler,
    ledger: SqliteLedger,
    monitor: _Monitor,
    console_path: Path,
) -> None:
    for pulse in range(1, 9):
        _log(console_path, f"pulse {pulse}: dispatch")
        await scheduler.tick_once()
        await scheduler.drain()
        monitor.capture_contract(f"pulse:{pulse}:settled")
        root = ledger.tasks.get(_ROOT_TASK_ID)
        children = ledger.tasks.children(_ROOT_TASK_ID)
        _log(
            console_path,
            f"pulse {pulse}: root={root.status.value if root else 'missing'} "
            f"children={[(child.id, child.status.value) for child in children]} "
            f"running={ledger.runs.count_running()} queued_wakes={len(ledger.wakes.queued())}",
        )
        contract = ledger.delegation_contracts.get(_ROOT_TASK_ID)
        if root is None or root.status in {
            TaskStatus.DONE,
            TaskStatus.REJECTED,
            TaskStatus.CANCELLED,
        }:
            return
        if contract is not None and contract.status is DelegationContractStatus.BLOCKED:
            return
        if not ledger.wakes.queued() and ledger.runs.count_running() == 0:
            return


def _scope(task: Task) -> str:
    text = f"{task.origin_fingerprint} {task.intent}".lower()
    if "analytics" in text:
        return "analytics"
    if "link" in text or "short" in text:
        return "links"
    return "unknown"


def _snapshot_prompts(company_root: Path) -> dict[str, str]:
    prompts: dict[str, str] = {}
    for path in sorted((company_root / "worktrees").glob("*/.harness/roles/*.toml")):
        prompts[str(path.relative_to(company_root)).replace("\\", "/")] = path.read_text(
            encoding="utf-8"
        )
    return prompts


def _copy_traces(company_root: Path, destination: Path, secrets: tuple[str, ...]) -> list[Path]:
    copied: list[Path] = []
    pattern = "worktrees/*/.dream/sidecars/*/logs/trace.jsonl"
    for index, source in enumerate(sorted(company_root.glob(pattern)), start=1):
        destination.mkdir(parents=True, exist_ok=True)
        employee_id = source.parents[4].name
        target = destination / f"trace-{index:02d}-{employee_id}-{source.parents[1].name}.jsonl"
        target.write_text(
            redact_text(source.read_text(encoding="utf-8"), secrets), encoding="utf-8"
        )
        copied.append(target)
    return copied


def _run_gate(repo: Path) -> subprocess.CompletedProcess[str]:
    if not (repo / "gate_check.py").is_file():
        return subprocess.CompletedProcess(
            args=[sys.executable, "gate_check.py"],
            returncode=127,
            stdout="",
            stderr="gate_check.py is missing",
        )
    return subprocess.run(
        [sys.executable, "gate_check.py"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def _audit_tdd(events: list[Event], red_path: Path) -> tuple[bool, str]:
    try:
        manifest = json.loads(red_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, "RED manifest is missing or malformed"
    if not isinstance(manifest, dict) or manifest.get("verdict") != "red-confirmed":
        return False, "RED manifest is not red-confirmed"
    returncode = manifest.get("returncode")
    if not isinstance(returncode, int) or returncode == 0 or returncode in {126, 127}:
        return False, "RED command did not execute as an expected failing test"
    if manifest.get("command_unavailable") is not False:
        return False, "RED command was unavailable"
    if manifest.get("expected_failure_matched") is not True:
        return False, "RED output did not match the expected failure"
    for field in ("production_paths", "invalid_test_paths", "missing_tests"):
        if manifest.get(field) != []:
            return False, f"RED manifest carries non-empty {field}"
    red_index: int | None = None
    production_index: int | None = None
    for index, event in enumerate(events):
        payload = event.payload
        if (
            event.kind is EventKind.RUN_TOOL_RESULT
            and payload.get("tool") == "test_red"
            and not payload.get("is_error")
            and "red-confirmed" in str(payload.get("content", ""))
        ):
            red_index = index
        if event.kind is not EventKind.RUN_TOOL_USE or payload.get("tool") != "write_file":
            continue
        path = str(dict(payload.get("input") or {}).get("path", "")).replace("\\", "/")
        name = Path(path).name.lower()
        is_test = (
            path.startswith("tests/")
            or "/tests/" in f"/{path}"
            or name.startswith("test_")
            or ".test." in name
            or ".spec." in name
        )
        is_bookkeeping = path in {"TODO.md", "test_plan.json"} or path.startswith(
            (".dream/", ".harness/", "test_evidence/")
        )
        if path and not is_test and not is_bookkeeping and production_index is None:
            production_index = index
    if red_index is None or production_index is None or red_index >= production_index:
        return False, f"RED index={red_index}, production index={production_index}"
    return True, f"RED event {red_index + 1} precedes production event {production_index + 1}"


_PROVENANCE_EXCLUDED_PATHS = frozenset(
    {
        "TODO.md",
        "api_verdict.json",
        "code_quality/report.json",
        "review_verdict.json",
        "security_scan/report.json",
        "test_evidence/manifest.json",
        "test_evidence/red.json",
        "test_evidence/red.txt",
        "test_plan.json",
    }
)
_PROVENANCE_EXCLUDED_PREFIXES = (
    ".dream/",
    ".harness/",
    "docs/evals/",
    "docs/exec-plans/active/",
    "test_evidence/",
)


def _worktree_fingerprint(root: Path) -> str:
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if listed.returncode != 0:
        return ""
    digest = sha256()
    for relative_path in sorted(os.fsdecode(raw) for raw in listed.stdout.split(b"\0") if raw):
        normalized = relative_path.replace("\\", "/")
        if normalized in _PROVENANCE_EXCLUDED_PATHS or normalized.startswith(
            _PROVENANCE_EXCLUDED_PREFIXES
        ):
            continue
        digest.update(normalized.encode("utf-8", errors="surrogateescape"))
        path = root / relative_path
        if not path.exists():
            digest.update(b"\0missing\0")
        elif path.is_symlink():
            digest.update(b"\0link\0" + os.readlink(path).encode("utf-8"))
        elif path.is_file():
            digest.update(b"\0file\0" + path.read_bytes())
    return digest.hexdigest()


def _audit_review(events: list[Event], worktree: Path) -> tuple[bool, str]:
    artifact_path = worktree / "review_verdict.json"
    provenance_path = worktree / ".harness" / "subagent-evidence" / "code_reviewer.json"
    try:
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, "review artifact or machine provenance is missing/malformed"
    if not isinstance(artifact, dict) or artifact.get("cleared") is not True:
        return False, "review artifact is not cleared"
    if not isinstance(provenance, dict):
        return False, "review provenance is not an object"
    if provenance.get("artifact_sha256") != sha256(artifact_path.read_bytes()).hexdigest():
        return False, "review artifact hash differs from machine provenance"
    if provenance.get("required_claim") != {"cleared": True}:
        return False, "review provenance does not require cleared=true"
    if provenance.get("worktree_sha256") != _worktree_fingerprint(worktree):
        return False, "reviewed worktree hash changed"
    completed = [
        event
        for event in events
        if event.kind is EventKind.SUBAGENT_COMPLETED
        and event.payload.get("subagent_name") == "code_reviewer"
    ]
    if not completed or completed[-1].payload.get("is_error"):
        return False, "no successful code_reviewer completion event"
    try:
        returned = json.loads(str(completed[-1].payload.get("content", "")))
    except json.JSONDecodeError:
        return False, "code_reviewer completion was not typed JSON"
    if returned != artifact:
        return False, "code_reviewer typed return differs from worktree artifact"
    return True, "typed return, artifact, and reviewed worktree hash agree"


def _audit_test_author(events: list[Event], worktree: Path) -> tuple[bool, str]:
    artifact_path = worktree / "test_plan.json"
    provenance_path = worktree / ".harness" / "subagent-evidence" / "test_author.json"
    try:
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, "test-author artifact or machine provenance is missing/malformed"
    if not isinstance(artifact, dict) or artifact.get("authored") is not True:
        return False, "test-author artifact does not claim authored=true"
    if not isinstance(provenance, dict):
        return False, "test-author provenance is not an object"
    if provenance.get("artifact_sha256") != sha256(artifact_path.read_bytes()).hexdigest():
        return False, "test-author artifact hash differs from machine provenance"
    if provenance.get("required_claim") != {"authored": True}:
        return False, "test-author provenance does not require authored=true"
    if provenance.get("evidence_read_only") is not False:
        return False, "test-author provenance has the wrong evidence mutation mode"
    completed = [
        event
        for event in events
        if event.kind is EventKind.SUBAGENT_COMPLETED
        and event.payload.get("subagent_name") == "test_author"
    ]
    if not completed or completed[-1].payload.get("is_error"):
        return False, "no successful test_author completion event"
    try:
        returned = json.loads(str(completed[-1].payload.get("content", "")))
    except json.JSONDecodeError:
        return False, "test_author completion was not typed JSON"
    if returned != artifact:
        return False, "test_author typed return differs from worktree artifact"
    return True, "typed return, artifact, and independent test-author provenance agree"


_OFFLOAD_POINTER = re.compile(r"Full output saved to:\s*([^\s]+)")


def _audit_evaluator_retrieval(events: list[Event]) -> tuple[bool, str]:
    missing: list[str] = []
    for index, event in enumerate(events):
        payload = event.payload
        if event.kind is not EventKind.RUN_TOOL_RESULT or payload.get("role") != "evaluator":
            continue
        for pointer in _OFFLOAD_POINTER.findall(str(payload.get("content", ""))):
            if not any(
                later.kind is EventKind.RUN_TOOL_USE
                and later.payload.get("role") == "evaluator"
                and later.payload.get("tool") == "read_offloaded"
                and str(dict(later.payload.get("input") or {}).get("path", "")) == pointer
                for later in events[index + 1 :]
            ):
                missing.append(pointer)
    return (
        (False, f"unretrieved evaluator offloads={missing}")
        if missing
        else (True, "all evaluator offloads were retrieved, or no evaluator result spilled")
    )


def _audit_redaction(paths: list[Path], secrets: tuple[str, ...]) -> tuple[bool, str]:
    leaks: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        if any(secret in content for secret in secrets if len(secret) >= 8):
            leaks.append(path.name)
    return not leaks, f"files containing configured secrets={tuple(leaks)}"


def _render_report(
    *,
    run_root: Path,
    deployment: str,
    snapshot: T3Snapshot,
    invariants: tuple[Invariant, ...],
    employees: tuple[Employee, ...],
    goal: object,
    team: object,
    contract: object,
    contract_transitions: list[dict[str, str]],
    tasks: list[Task],
    runs_by_task: Mapping[str, Sequence[object]],
    artifacts_by_task: Mapping[str, Sequence[object]],
    dod_by_task: Mapping[str, object],
    activities: Sequence[object],
    decisions_by_task: Mapping[str, Sequence[object]],
    prompts: dict[str, str],
    events: list[Event],
    traces: list[Path],
    gate: subprocess.CompletedProcess[str],
    company_repo: Path,
    quality_details: dict[str, object],
) -> str:
    passed = all(check.passed for check in invariants)
    lines = [
        "# T3 Parallel Delegation Live Run Report",
        "",
        f"**Result:** {'PASS' if passed else 'STOPPED / NEEDS FIX'}  ",
        f"**Model deployment:** `{deployment}`  ",
        f"**Run directory:** `{run_root}`  ",
        "**Scope:** one backend lead, two backend ICs, two concurrent module-sized children, "
        "independent subtree verification",
        "",
        "## Invariants",
        "",
        "| Check | Result | Evidence |",
        "| --- | --- | --- |",
    ]
    for check in invariants:
        lines.append(
            f"| {check.name} | {'PASS' if check.passed else 'FAIL'} | "
            f"{check.detail.replace('|', chr(92) + '|')} |"
        )
    lines.extend(
        [
            "",
            "## Objective, OKRs, and Task Split",
            "",
            "```text",
            "Objective: Ship Linkport backend foundations",
            "|- KR-A: links.py + dedicated tests (links-ic)",
            "`- KR-B: analytics.py + dedicated tests (analytics-ic)",
            "```",
            "",
            "Exactly two coarse children are allowed. Shared gate/config files are immutable seed "
            "inputs; each IC owns one complete module and its dedicated tests.",
            "",
            "### Effective root intent",
            _INTENT,
            "",
            "### Independent integration rubric",
            _OBJECTIVE_RUBRIC,
            "",
            "## Organization and Authority",
            "",
            "### Employees",
            _code_block(_json(employees), "json"),
            "",
            "### Goal",
            _code_block(_json(goal), "json"),
            "",
            "### Mission Team",
            _code_block(_json(team), "json"),
            "",
            "### Delegation contract",
            _code_block(_json(contract), "json"),
            "",
            "`system-verifier` is not an employee. It appears only as a system principal in "
            "verification runs and audit activities.",
            "",
            "## Delegation Timeline",
            "",
            _code_block(_json(contract_transitions), "json"),
            "",
            "## Goal and Task Tree",
            "",
            _code_block(_json(tasks), "json"),
            "",
            "## Runs by Task",
            "",
            _code_block(_json(runs_by_task), "json"),
            "",
            "## Definitions of Done",
            "",
            _code_block(_json(dod_by_task), "json"),
            "",
            "## Artifacts Written and Landed",
            "",
            _code_block(_json(artifacts_by_task), "json"),
            "",
            "## Per-Child Quality Reconstruction",
            "",
            _code_block(_json(quality_details), "json"),
            "",
            "## Decisions",
            "",
            _code_block(_json(decisions_by_task), "json"),
            "",
            "## Effective Role Prompts",
            "",
        ]
    )
    for path, content in prompts.items():
        lines.extend([f"### `{path}`", "", _code_block(content, "toml"), ""])
    lines.extend(["## Chronological Runtime Events", ""])
    for index, event in enumerate(events, start=1):
        lines.extend(
            [
                f"### {index}. `{event.kind.value}` at {event.at.isoformat()}",
                "",
                f"task=`{event.task_id}` employee=`{event.employee_id}` run=`{event.run_id}` "
                f"trace=`{event.trace_id}`",
                "",
                _code_block(_json(dict(event.payload)), "json"),
                "",
            ]
        )
    lines.extend(["## Append-Only Audit Activity", ""])
    for index, activity in enumerate(activities, start=1):
        lines.extend(
            [
                f"### {index}. `{getattr(activity, 'verb', '?')}`",
                "",
                _code_block(_json(activity), "json"),
                "",
            ]
        )
    lines.extend(
        [
            "## Independent Company-Main Gate",
            "",
            f"Command: `{sys.executable} gate_check.py`  ",
            f"Exit code: `{gate.returncode}`",
            "",
            _code_block((gate.stdout + "\n" + gate.stderr).strip() or "(no output)", "text"),
            "",
            "## Final Deliverables",
            "",
            "### Tracked files",
            _code_block(_git(company_repo, "ls-files").stdout or "(company repo missing)", "text"),
            "",
            "### Git history",
            _code_block(_git(company_repo, "log", "--oneline", "--decorate", "-15").stdout, "text"),
            "",
            "### Git status",
            _code_block(_git(company_repo, "status", "--short").stdout or "(clean)", "text"),
            "",
            "## Raw Evidence Inventory",
            "",
            "- [events.jsonl](events.jsonl): lossless Chorus runtime event stream",
            "- [console.log](console.log): concise chronological runner log",
            "- [company.db](company.db): durable ledger",
            "- [summary.json](summary.json): machine-readable invariant snapshot",
        ]
    )
    lines.extend(f"- [{trace.name}]({trace.relative_to(run_root).as_posix()})" for trace in traces)
    lines.extend(
        [
            "",
            "## Monitoring Boundary",
            "",
            f"This report renders all {snapshot.event_count} observable Chorus events and all "
            f"{snapshot.tool_use_count} tool calls with their recorded arguments/results. Dream "
            "sidecar JSONL is retained above. Private chain-of-thought is unavailable and is not "
            "claimed; decisions are reconstructed from model text, tool activity, typed outputs, "
            "verdicts, ledger state, git history, and artifacts.",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "reports" / "t3-live-runs",
    )
    parser.add_argument("--expect-model", default="gpt-5.2")
    return parser.parse_args()


def _timestamp(value: datetime | None) -> float:
    return value.timestamp() if value is not None else -1.0


def main() -> int:
    args = _parse_args()
    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL", "")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")
    if not (api_key and base_url and deployment):
        print("missing AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, or AZURE_OPENAI_DEPLOYMENT")
        return 2
    if deployment != args.expect_model:
        print(f"refusing to run: expected model {args.expect_model!r}, configured {deployment!r}")
        return 2

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_root = args.output_root.resolve() / f"t3-{stamp}-{uuid4().hex[:8]}"
    run_root.mkdir(parents=True)
    console_path = run_root / "console.log"
    console_path.touch()
    seed = run_root / "seed"
    _seed_repo(seed)
    ledger = SqliteLedger.open(str(run_root / "company.db"))
    events_path = run_root / "events.jsonl"
    secrets = _secret_values()
    registry = RoleRegistry.from_plugins(default_roles())
    factory = EmployeeHarnessFactory(
        api_key=api_key,
        base_url=base_url,
        deployment=deployment,
        company_id=_COMPANY_ID,
        roles=registry,
        pricing=default_pricing_from_env(),
        seed=seed,
        work_root=run_root / "work",
        timeout_s=None,
        ledger=ledger,
    )

    try:
        employees = _seed_org(ledger)
        monitor = _Monitor(ledger, console_path)
        monitor.capture_contract("setup")
        event_bus = EventBus(log_path=events_path)
        event_bus.subscribe(monitor.observe)
        scheduler = Scheduler(
            ledger=ledger,
            workforce=LedgerWorkforce(ledger.employees),
            beat_runner_for=factory,
            event_bus=event_bus,
            roles=registry,
            landers=factory.landers,
            max_concurrent_runs=2,
            max_repair_attempts=0,
            max_resume_attempts=0,
            transient_retries=0,
            max_review_rounds=0,
            max_integrate_iterations=1,
        )
        _log(console_path, f"T3 run directory: {run_root}")
        _log(
            console_path,
            f"model: {deployment}; lead: {_LEAD_ID}; ICs: {_LINKS_IC_ID}, {_ANALYTICS_IC_ID}",
        )
        asyncio.run(_drive(scheduler, ledger, monitor, console_path))
        monitor.capture_contract("run-complete")

        company_repo = factory.company_root / "repo"
        gate = _run_gate(company_repo)
        tasks = ledger.tasks.all()
        children = sorted(ledger.tasks.children(_ROOT_TASK_ID), key=_scope, reverse=True)
        runs_by_task = {task.id: list(ledger.runs.for_task(task.id)) for task in tasks}
        artifacts_by_task = {
            task.id: list(ledger.artifacts.list_for_task(task.id)) for task in tasks
        }
        dod_by_task = {task.id: ledger.dod.get_for_task(task.id) for task in tasks}
        decisions_by_task = {task.id: list(ledger.decisions.for_task(task.id)) for task in tasks}
        activities = ledger.activity.all()
        root = ledger.tasks.get(_ROOT_TASK_ID)
        contract = ledger.delegation_contracts.get(_ROOT_TASK_ID)
        team = ledger.teams.get(root.team_id) if root is not None and root.team_id else None
        goal = ledger.goals.get(_GOAL_ID)
        root_runs = runs_by_task.get(_ROOT_TASK_ID, [])
        parent_verifier_runs = [
            run for run in root_runs if getattr(run, "principal_kind", "") == "system"
        ]
        parent_verdicts = [
            activity
            for activity in ledger.activity.by_subject("delegation_contract", _ROOT_TASK_ID)
            if activity.verb is ActivityVerb.PARENT_VERIFIED
        ]
        employee_run_windows = tuple(
            RunWindow(
                task_id=child.id,
                principal_id=run.principal_id,
                started_at=_timestamp(run.started_at),
                finished_at=_timestamp(run.finished_at),
            )
            for child in children
            for run in runs_by_task.get(child.id, [])
            if getattr(run, "principal_kind", "") == "employee"
        )
        child_prs_merged = tuple(
            any(
                artifact.type.value == "pr"
                and artifact.resource_ref is not None
                and artifact.resource_ref.get("merged") is True
                for artifact in artifacts_by_task.get(child.id, [])
            )
            for child in children
        )
        quality_details: dict[str, object] = {}
        child_tdd: list[bool] = []
        child_review: list[bool] = []
        for child in children:
            child_events = [event for event in monitor.events if event.task_id == child.id]
            worktree = factory.company_root / "worktrees" / str(child.assignee_employee_id)
            red_ok, red_detail = _audit_tdd(child_events, worktree / "test_evidence" / "red.json")
            author_ok, author_detail = _audit_test_author(child_events, worktree)
            tdd_ok = red_ok and author_ok
            tdd_detail = f"{red_detail}; test author: {author_detail}"
            review_ok, review_detail = _audit_review(child_events, worktree)
            child_tdd.append(tdd_ok)
            child_review.append(review_ok)
            quality_details[child.id] = {
                "scope": _scope(child),
                "assignee": child.assignee_employee_id,
                "tdd_valid": tdd_ok,
                "tdd_detail": tdd_detail,
                "review_valid": review_ok,
                "review_detail": review_detail,
            }
        retrieval_ok, retrieval_detail = _audit_evaluator_retrieval(monitor.events)
        quality_details["evaluator_retrieval"] = {
            "complete": retrieval_ok,
            "detail": retrieval_detail,
        }
        tool_uses = [event for event in monitor.events if event.kind is EventKind.RUN_TOOL_USE]
        tool_results = [
            event for event in monitor.events if event.kind is EventKind.RUN_TOOL_RESULT
        ]
        traces = _copy_traces(factory.company_root, run_root / "traces", secrets)
        prompts = _snapshot_prompts(factory.company_root)
        tracked = tuple(
            line.strip().replace("\\", "/")
            for line in _git(company_repo, "ls-files").stdout.splitlines()
            if line.strip()
        )
        snapshot = T3Snapshot(
            root_status=root.status.value if root is not None else "missing",
            child_ids=tuple(child.id for child in children),
            child_statuses=tuple(child.status.value for child in children),
            child_assignees=tuple(str(child.assignee_employee_id or "") for child in children),
            child_scopes=tuple(_scope(child) for child in children),
            employee_run_windows=employee_run_windows,
            contract_status_history=tuple(
                transition["status"] for transition in monitor.contract_transitions
            ),
            parent_verifier_principals=tuple(run.principal_id for run in parent_verifier_runs),
            parent_verifier_statuses=tuple(run.status.value for run in parent_verifier_runs),
            parent_verdict_passed=len(parent_verdicts) == 1
            and parent_verdicts[0].payload.get("passed") is True,
            child_prs_merged=child_prs_merged,
            company_branch=_git(company_repo, "branch", "--show-current").stdout.strip(),
            gate_exit_code=gate.returncode,
            shipped_paths=tracked,
            child_tdd_valid=tuple(child_tdd),
            child_review_valid=tuple(child_review),
            evaluator_retrieval_complete=retrieval_ok,
            task_count=len(tasks),
            tool_use_count=len(tool_uses),
            tool_result_count=len(tool_results),
            all_tool_results_lossless=bool(tool_results)
            and all("content" in event.payload for event in tool_results),
            event_count=len(monitor.events),
            trace_count=len(traces),
            secret_redaction_safe=False,
        )
        invariants = evaluate_invariants(snapshot)
        report = _render_report(
            run_root=run_root,
            deployment=deployment,
            snapshot=snapshot,
            invariants=invariants,
            employees=employees,
            goal=goal,
            team=team,
            contract=contract,
            contract_transitions=monitor.contract_transitions,
            tasks=tasks,
            runs_by_task=runs_by_task,
            artifacts_by_task=artifacts_by_task,
            dod_by_task=dod_by_task,
            activities=activities,
            decisions_by_task=decisions_by_task,
            prompts=prompts,
            events=monitor.events,
            traces=traces,
            gate=gate,
            company_repo=company_repo,
            quality_details=quality_details,
        )
        report_path = run_root / "report.md"
        report_path.write_text(redact_text(report, secrets), encoding="utf-8")
        for path in (events_path, console_path):
            if path.is_file():
                path.write_text(
                    redact_text(path.read_text(encoding="utf-8"), secrets), encoding="utf-8"
                )
        redaction_paths = [report_path, events_path, console_path, *traces]
        redaction_safe, redaction_detail = _audit_redaction(redaction_paths, secrets)
        snapshot = replace(snapshot, secret_redaction_safe=redaction_safe)
        invariants = evaluate_invariants(snapshot)
        report = _render_report(
            run_root=run_root,
            deployment=deployment,
            snapshot=snapshot,
            invariants=invariants,
            employees=employees,
            goal=goal,
            team=team,
            contract=contract,
            contract_transitions=monitor.contract_transitions,
            tasks=tasks,
            runs_by_task=runs_by_task,
            artifacts_by_task=artifacts_by_task,
            dod_by_task=dod_by_task,
            activities=activities,
            decisions_by_task=decisions_by_task,
            prompts=prompts,
            events=monitor.events,
            traces=traces,
            gate=gate,
            company_repo=company_repo,
            quality_details=quality_details,
        )
        report_path.write_text(redact_text(report, secrets), encoding="utf-8")
        summary_path = run_root / "summary.json"
        summary_path.write_text(
            redact_text(
                _json(
                    {
                        "snapshot": snapshot,
                        "invariants": invariants,
                        "quality_details": quality_details,
                        "redaction_audit": redaction_detail,
                    }
                )
                + "\n",
                secrets,
            ),
            encoding="utf-8",
        )
        final_redaction_safe, final_redaction_detail = _audit_redaction(
            [*redaction_paths, summary_path], secrets
        )
        if final_redaction_safe != snapshot.secret_redaction_safe:
            snapshot = replace(snapshot, secret_redaction_safe=final_redaction_safe)
            invariants = evaluate_invariants(snapshot)
        args.output_root.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(report_path, args.output_root / "T3-latest.md")
        shutil.copyfile(summary_path, args.output_root / "T3-latest.json")

        _log(console_path, f"redaction audit: {final_redaction_detail}")
        for check in invariants:
            _log(
                console_path,
                f"{'PASS' if check.passed else 'FAIL'} {check.name}: {check.detail}",
            )
        _log(console_path, f"report: {report_path}")
        _log(console_path, f"latest: {args.output_root / 'T3-latest.md'}")
        return 0 if all(check.passed for check in invariants) else 1
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
