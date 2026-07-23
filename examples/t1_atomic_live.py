"""T1 atomic live run: one large backend beat, independent verification, full report.

This is the first rung of the end-to-end capstone ladder. It intentionally disables automatic
repair, resume, and transient retry loops: one worker beat gets one substantial module. Any failure
stops the scenario with its durable evidence intact so the responsible general mechanism can be
fixed before rerunning.

The runner writes an isolated run directory containing the company database, git workspaces,
lossless Chorus events, Dream sidecar traces, and a rendered Markdown report. It exits non-zero when
any T1 invariant fails.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from chorus.events import Event, EventKind
from chorus.heartbeat import Scheduler
from chorus.ledger import Ledger, Task, TaskStatus
from chorus.lifecycle import assign_task
from chorus.observability import EventBus
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee, LedgerWorkforce
from chorus_cli._beats import default_pricing_from_env
from chorus_harness import EmployeeHarnessFactory

_TASK_ID = "t1-links"
_EMPLOYEE_ID = "bex"
_COMPANY_ID = "linkport-t1"
_TERMINAL = frozenset(
    {TaskStatus.DONE, TaskStatus.BLOCKED, TaskStatus.REJECTED, TaskStatus.CANCELLED}
)
_RUNTIME_STATE_SUFFIXES = frozenset({".db", ".log", ".sqlite", ".sqlite3"})
_RUNTIME_STATE_PARTS = frozenset(
    {
        ".coverage",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "build",
        "dist",
        "htmlcov",
    }
)
_INTENT = (
    "Build the complete Linkport links module as ONE end-to-end delivery chunk. Use Python's "
    "standard library only. Create `links.py` with base62 short-code generation and a SQLite-backed "
    "store. Its public API must support `create(url, ttl_seconds=None) -> code` and `resolve(code) -> "
    "url`; validate URLs, handle short-code collisions safely, persist across store reopens, and "
    "enforce optional TTL expiry. Author a comprehensive pytest suite under `tests/`, test-first, "
    "covering base62 boundaries, create/resolve persistence, collisions, invalid URLs, unknown codes, "
    "and expiry with a deterministic injected clock. Keep this as one module-sized task: implement "
    "the production code and all of its tests in this beat; do not split or defer work. Run "
    "`python gate_check.py`, make every gate green, and leave the role's durable test, test-plan, "
    "code-review, and quality evidence in the worktree for independent system verification."
)

_GATE_CHECK = '''"""Portable project gate: tests and static analysis."""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    commands = (
        (sys.executable, "-m", "pytest", "-q"),
        (sys.executable, "-m", "ruff", "check", "."),
    )
    for command in commands:
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

_PYPROJECT = """[project]
name = "linkport-links"
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
    """One independently checkable T1 acceptance condition."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class T1Snapshot:
    """Minimal, pure-data projection used to judge a completed live run."""

    task_status: str
    worker_run_principals: tuple[str, ...]
    worker_run_statuses: tuple[str, ...]
    verifier_run_principals: tuple[str, ...]
    verifier_run_statuses: tuple[str, ...]
    dod_status: str
    artifact_types: tuple[str, ...]
    pr_merged: bool
    pr_target: str
    company_branch: str
    gate_exit_code: int
    shipped_paths: tuple[str, ...]
    red_evidence_verdict: str
    tdd_chronology_valid: bool
    review_provenance_valid: bool
    evaluator_retrieval_complete: bool
    secret_redaction_safe: bool
    tool_use_count: int
    tool_result_count: int
    all_tool_results_lossless: bool
    event_count: int = 1
    trace_count: int = 1


def evaluate_invariants(snapshot: T1Snapshot) -> tuple[Invariant, ...]:
    """Judge T1 without access to mutable runtime state; every check fails closed."""
    one_worker = snapshot.worker_run_principals == (
        _EMPLOYEE_ID,
    ) and snapshot.worker_run_statuses == ("succeeded",)
    one_verifier = snapshot.verifier_run_principals == (
        "system-verifier",
    ) and snapshot.verifier_run_statuses == ("succeeded",)
    tests_present = any(
        Path(path).suffix == ".py" and "test" in Path(path).name.lower()
        for path in snapshot.shipped_paths
    )
    runtime_state_paths = tuple(
        path
        for path in snapshot.shipped_paths
        if Path(path).suffix.lower() in _RUNTIME_STATE_SUFFIXES
        or any(part.lower() in _RUNTIME_STATE_PARTS for part in Path(path).parts)
    )
    return (
        Invariant(
            "one build beat",
            one_worker,
            f"worker principals={snapshot.worker_run_principals}, "
            f"statuses={snapshot.worker_run_statuses}",
        ),
        Invariant(
            "independent system verification",
            one_verifier,
            f"verifier principals={snapshot.verifier_run_principals}, "
            f"statuses={snapshot.verifier_run_statuses}",
        ),
        Invariant(
            "reviewed-build gate passed",
            snapshot.task_status == "done" and snapshot.dod_status == "passed",
            f"task={snapshot.task_status}, DoD={snapshot.dod_status}",
        ),
        Invariant(
            "PR artifact landed",
            "pr" in snapshot.artifact_types
            and snapshot.pr_merged
            and snapshot.pr_target == "main"
            and snapshot.company_branch == "main",
            f"artifact types={snapshot.artifact_types}, merged={snapshot.pr_merged}, "
            f"target={snapshot.pr_target!r}, company branch={snapshot.company_branch!r}",
        ),
        Invariant(
            "independent gate green",
            snapshot.gate_exit_code == 0,
            f"python gate_check.py exit={snapshot.gate_exit_code}",
        ),
        Invariant(
            "module and tests shipped",
            "links.py" in snapshot.shipped_paths and tests_present,
            f"tracked paths={snapshot.shipped_paths}",
        ),
        Invariant(
            "artifact hygiene",
            not runtime_state_paths,
            f"generated runtime paths={runtime_state_paths}",
        ),
        Invariant(
            "strict TDD chronology",
            snapshot.red_evidence_verdict == "red-confirmed" and snapshot.tdd_chronology_valid,
            f"test_evidence/red.json verdict={snapshot.red_evidence_verdict}, "
            f"behavior-specific RED precedes production={snapshot.tdd_chronology_valid}",
        ),
        Invariant(
            "independent review provenance",
            snapshot.review_provenance_valid,
            f"typed return, artifact, worktree hash agree={snapshot.review_provenance_valid}",
        ),
        Invariant(
            "evaluator evidence retrieval",
            snapshot.evaluator_retrieval_complete,
            f"all evaluator offloads retrieved={snapshot.evaluator_retrieval_complete}",
        ),
        Invariant(
            "secret redaction audit",
            snapshot.secret_redaction_safe,
            f"persisted report/events/traces contain no configured secret={snapshot.secret_redaction_safe}",
        ),
        Invariant(
            "tool stream complete",
            snapshot.tool_use_count > 0
            and snapshot.tool_result_count == snapshot.tool_use_count
            and snapshot.all_tool_results_lossless,
            f"uses={snapshot.tool_use_count}, results={snapshot.tool_result_count}, "
            f"lossless={snapshot.all_tool_results_lossless}",
        ),
        Invariant(
            "durable monitoring evidence",
            snapshot.event_count > 0 and snapshot.trace_count >= 2,
            f"events={snapshot.event_count}, Dream traces={snapshot.trace_count}",
        ),
    )


def redact_text(text: str, secret_values: tuple[str, ...]) -> str:
    """Remove known secret values without altering ordinary evidence."""
    redacted = text
    for secret in sorted(
        {value for value in secret_values if len(value) >= 8}, key=len, reverse=True
    ):
        redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def _secret_values() -> tuple[str, ...]:
    markers = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
    return tuple(
        value
        for name, value in os.environ.items()
        if value and any(marker in name.upper() for marker in markers)
    )


def _json(value: object) -> str:
    return json.dumps(_jsonable(value), indent=2, sort_keys=True, default=str)


def _jsonable(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _code_block(text: str, language: str = "") -> str:
    longest = max((len(part) for part in text.split("`") if part == ""), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{text.rstrip()}\n{fence}"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _manifest_verdict(path: Path) -> str:
    """Read a durable evidence verdict; missing or malformed evidence fails closed."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "missing-or-malformed"
    verdict = payload.get("verdict") if isinstance(payload, dict) else None
    return verdict if isinstance(verdict, str) else "missing-or-malformed"


def _audit_tdd(events: list[Event], red_path: Path) -> tuple[bool, str]:
    """Reconstruct behavior-specific RED and RED-before-production chronology."""
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
    ignored_paths = {"TODO.md", "test_plan.json"}
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
        is_bookkeeping = path in ignored_paths or path.startswith(
            (".dream/", ".harness/", "test_evidence/")
        )
        if path and not is_test and not is_bookkeeping and production_index is None:
            production_index = index
    if red_index is None:
        return False, "event stream has no successful test_red result"
    if production_index is None:
        return False, "event stream has no production write"
    if red_index >= production_index:
        return False, "production was written before machine-confirmed RED"
    return True, f"RED event {red_index + 1} precedes production event {production_index + 1}"


_OFFLOAD_POINTER = re.compile(r"Full output saved to:\s*([^\s]+)")


def _audit_evaluator_retrieval(events: list[Event]) -> tuple[bool, str]:
    """Require every evaluator spill pointer to be followed by a matching retrieval call."""
    missing: list[str] = []
    for index, event in enumerate(events):
        payload = event.payload
        if event.kind is not EventKind.RUN_TOOL_RESULT or payload.get("role") != "evaluator":
            continue
        pointers = _OFFLOAD_POINTER.findall(str(payload.get("content", "")))
        for pointer in pointers:
            retrieved = any(
                later.kind is EventKind.RUN_TOOL_USE
                and later.payload.get("role") == "evaluator"
                and later.payload.get("tool") == "read_offloaded"
                and str(dict(later.payload.get("input") or {}).get("path", "")) == pointer
                for later in events[index + 1 :]
            )
            if not retrieved:
                missing.append(pointer)
    if missing:
        return False, f"unretrieved evaluator offloads={missing}"
    return True, "all evaluator offloads were retrieved, or no evaluator result spilled"


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
    }
)
_PROVENANCE_EXCLUDED_PREFIXES = (
    ".dream/",
    ".harness/",
    "docs/evals/",
    "docs/exec-plans/active/",
    "test_evidence/",
)


def _reviewed_worktree_fingerprint(root: Path) -> str:
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if listed.returncode != 0:
        return ""
    digest = sha256()
    paths = sorted(os.fsdecode(raw) for raw in listed.stdout.split(b"\0") if raw)
    for relative_path in paths:
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


def _audit_review_provenance(
    events: list[Event], *, company_repo: Path, worker_worktree: Path
) -> tuple[bool, str]:
    artifact_path = company_repo / "review_verdict.json"
    provenance_path = worker_worktree / ".harness" / "subagent-evidence" / "code_reviewer.json"
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
    if provenance.get("worktree_sha256") != _reviewed_worktree_fingerprint(worker_worktree):
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
        return False, "code_reviewer typed return differs from landed artifact"
    return True, "typed return, landed artifact, and reviewed worktree hash agree"


def _audit_redaction(paths: list[Path], secrets: tuple[str, ...]) -> tuple[bool, str]:
    candidates = tuple(secret for secret in secrets if len(secret) >= 8)
    exposed: list[str] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if any(secret in text for secret in candidates):
            exposed.append(path.name)
    return (not exposed, "no configured secrets found" if not exposed else f"exposed in {exposed}")


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
        "# Linkport links\n\nThe links module is implemented by the T1 delivery beat.\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "-c",
            "user.name=Linkport T1",
            "-c",
            "user.email=t1@linkport.invalid",
            "commit",
            "-m",
            "seed portable Linkport gate",
        ],
        check=True,
        capture_output=True,
    )


class _Monitor:
    """Concise live console view; the EventBus remains the lossless source of record."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    def observe(self, event: Event) -> None:
        self.events.append(event)
        if event.kind is EventKind.RUN_STARTED:
            print(f"[{event.at.isoformat()}] run started task={event.task_id}", flush=True)
        elif event.kind is EventKind.RUN_TOOL_USE:
            print(
                f"[{event.at.isoformat()}] tool -> {event.payload.get('tool', '?')} "
                f"role={event.payload.get('role', '?')}",
                flush=True,
            )
        elif event.kind is EventKind.RUN_TOOL_RESULT:
            result = "error" if event.payload.get("is_error") else "ok"
            print(
                f"[{event.at.isoformat()}] tool <- {event.payload.get('tool', '?')} [{result}]",
                flush=True,
            )
        elif event.kind is EventKind.RUN_EVALUATED:
            print(f"[{event.at.isoformat()}] evaluated {dict(event.payload)}", flush=True)
        elif event.kind is EventKind.RUN_DONE:
            print(f"[{event.at.isoformat()}] run done task={event.task_id}", flush=True)


def _snapshot_prompts(worktree: Path) -> dict[str, str]:
    role_dir = worktree / ".harness" / "roles"
    if not role_dir.is_dir():
        return {}
    return {
        str(path.relative_to(worktree)).replace("\\", "/"): path.read_text(encoding="utf-8")
        for path in sorted(role_dir.glob("*.toml"))
    }


def _copy_traces(worktree: Path, destination: Path, secrets: tuple[str, ...]) -> list[Path]:
    copied: list[Path] = []
    for index, source in enumerate(
        sorted(worktree.glob(".dream/sidecars/*/logs/trace.jsonl")), start=1
    ):
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / f"trace-{index:02d}-{source.parents[1].name}.jsonl"
        target.write_text(
            redact_text(source.read_text(encoding="utf-8"), secrets), encoding="utf-8"
        )
        copied.append(target)
    return copied


async def _drive(scheduler: Scheduler, ledger: Ledger) -> None:
    """Advance settled pulses and stop at the first terminal or abnormal state."""
    for pulse in range(1, 5):
        print(f"pulse {pulse}: dispatch", flush=True)
        await scheduler.tick_once()
        await scheduler.drain()
        task = ledger.tasks.get(_TASK_ID)
        runs = ledger.runs.for_task(_TASK_ID)
        worker_runs = [run for run in runs if run.principal_kind == "employee"]
        print(
            f"pulse {pulse}: task={task.status.value if task else 'missing'} "
            f"runs={len(runs)} worker_runs={len(worker_runs)}",
            flush=True,
        )
        if task is None or task.status in _TERMINAL or len(worker_runs) > 1:
            return
        if not ledger.wakes.queued() and ledger.runs.count_running() == 0:
            return


def _run_gate(repo: Path) -> subprocess.CompletedProcess[str]:
    if not (repo / "gate_check.py").exists():
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


def _render_report(
    *,
    run_root: Path,
    deployment: str,
    snapshot: T1Snapshot,
    invariants: tuple[Invariant, ...],
    employee: Employee,
    task: Task | None,
    runs: list[object],
    dod: object,
    artifacts: list[object],
    activities: list[object],
    decisions: list[object],
    events: list[Event],
    worker_prompts: dict[str, str],
    verifier_prompts: dict[str, str],
    traces: list[Path],
    gate: subprocess.CompletedProcess[str],
    company_repo: Path,
) -> str:
    passed = all(check.passed for check in invariants)
    lines = [
        "# T1 Atomic Live Run Report",
        "",
        f"**Result:** {'PASS' if passed else 'STOPPED / NEEDS FIX'}  ",
        f"**Model deployment:** `{deployment}`  ",
        f"**Run directory:** `{run_root}`  ",
        "**Scope:** one backend engineer, one module-sized build beat, independent system verifier",
        "",
        "## Invariants",
        "",
        "| Check | Result | Evidence |",
        "| --- | --- | --- |",
    ]
    for check in invariants:
        escaped_detail = check.detail.replace("|", "\\|")
        lines.append(f"| {check.name} | {'PASS' if check.passed else 'FAIL'} | {escaped_detail} |")
    lines.extend(
        [
            "",
            "## Founder Task",
            "",
            _INTENT,
            "",
            "## Organization",
            "",
            _code_block(_json(employee), "json"),
            "",
            "`system-verifier` is absent from the employee roster and appears only as a system "
            "principal in the run and audit evidence below.",
            "",
            "## Durable State",
            "",
            "### Task",
            _code_block(_json(task), "json"),
            "",
            "### Runs",
            _code_block(_json(runs), "json"),
            "",
            "### Definition of Done and verdict",
            _code_block(_json(dod), "json"),
            "",
            "### Artifacts",
            _code_block(_json(artifacts), "json"),
            "",
            "### Decisions",
            _code_block(_json(decisions), "json"),
            "",
            "## Effective Prompts",
            "",
            "The task intent above is the user prompt. These are the effective role overlays "
            "materialized around it.",
        ]
    )
    for label, prompts in (("Worker", worker_prompts), ("System verifier", verifier_prompts)):
        lines.extend(["", f"### {label}"])
        for path, content in prompts.items():
            lines.extend(["", f"#### `{path}`", _code_block(content, "toml")])
    lines.extend(["", "## Chronological Runtime Events", ""])
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
                _code_block(_json(activity), "json"),
                "",
            ]
        )
    lines.extend(
        [
            "## Independent Gate Rerun",
            "",
            f"Command: `{sys.executable} gate_check.py`  ",
            f"Exit code: `{gate.returncode}`",
            "",
            _code_block((gate.stdout + "\n" + gate.stderr).strip() or "(no output)", "text"),
            "",
            "## Deliverables",
            "",
            "### Tracked files",
            _code_block(_git(company_repo, "ls-files").stdout or "(company repo missing)", "text"),
            "",
            "### Git history",
            _code_block(_git(company_repo, "log", "--oneline", "--decorate", "-10").stdout, "text"),
            "",
            "### Git status",
            _code_block(_git(company_repo, "status", "--short").stdout or "(clean)", "text"),
            "",
            "## Dream Sidecar Traces",
            "",
        ]
    )
    for trace in traces:
        lines.append(f"- [{trace.name}]({trace.relative_to(run_root).as_posix()})")
    lines.extend(
        [
            "",
            "## Monitoring Boundary",
            "",
            f"The report contains all {snapshot.event_count} observable Chorus events, including "
            f"all {snapshot.tool_use_count} tool calls with complete inputs and outputs. Dream's "
            "model-side traces are linked above. Private model chain-of-thought is neither available "
            "nor represented; decisions are reported through model text, tool activity, verdicts, "
            "durable state, and artifacts.",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "reports" / "t1-live-runs",
    )
    parser.add_argument("--expect-model", default="gpt-5.2")
    return parser.parse_args()


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
    run_root = args.output_root.resolve() / f"t1-{stamp}-{uuid4().hex[:8]}"
    run_root.mkdir(parents=True)
    seed = run_root / "seed"
    _seed_repo(seed)
    ledger = Ledger.open(str(run_root / "company.db"))
    events_path = run_root / "events.jsonl"
    secrets = _secret_values()
    monitor = _Monitor()
    event_bus = EventBus(log_path=events_path)
    event_bus.subscribe(monitor.observe)
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
        employee = ledger.employees.create(
            Employee(id=_EMPLOYEE_ID, name="Bex", role="backend_engineer")
        )
        ledger.tasks.submit(Task(id=_TASK_ID, intent=_INTENT, status=TaskStatus.TODO))
        assign_task(ledger, _TASK_ID, employee.id)

        materialized = factory.materialize(employee, task_id=_TASK_ID)
        worker_prompts = _snapshot_prompts(materialized.working_dir)
        scheduler = Scheduler(
            ledger=ledger,
            workforce=LedgerWorkforce(ledger.employees),
            beat_runner_for=factory,
            event_bus=event_bus,
            roles=registry,
            landers=factory.landers,
            max_concurrent_runs=1,
            max_repair_attempts=0,
            max_resume_attempts=0,
            transient_retries=0,
            max_review_rounds=0,
        )

        print(f"T1 run directory: {run_root}", flush=True)
        print(f"model: {deployment}; task: {_TASK_ID}; worker: {_EMPLOYEE_ID}", flush=True)
        asyncio.run(_drive(scheduler, ledger))

        verifier_prompts = _snapshot_prompts(materialized.working_dir)
        company_repo = factory.company_root / "repo"
        gate = _run_gate(company_repo)
        runs = ledger.runs.for_task(_TASK_ID)
        task = ledger.tasks.get(_TASK_ID)
        dod = ledger.dod.get_for_task(_TASK_ID)
        artifacts = ledger.artifacts.list_for_task(_TASK_ID)
        pr_artifact = next(
            (artifact for artifact in artifacts if artifact.type.value == "pr"),
            None,
        )
        pr_ref = dict(pr_artifact.resource_ref or {}) if pr_artifact is not None else {}
        activities = ledger.activity.all()
        decisions = ledger.decisions.for_task(_TASK_ID)
        worker_runs = [run for run in runs if run.principal_kind == "employee"]
        verifier_runs = [run for run in runs if run.principal_kind == "system"]
        tool_uses = [event for event in monitor.events if event.kind is EventKind.RUN_TOOL_USE]
        tool_results = [
            event for event in monitor.events if event.kind is EventKind.RUN_TOOL_RESULT
        ]
        traces = _copy_traces(materialized.working_dir, run_root / "traces", secrets)
        tdd_valid, tdd_detail = _audit_tdd(
            monitor.events, materialized.working_dir / "test_evidence" / "red.json"
        )
        review_valid, review_detail = _audit_review_provenance(
            monitor.events,
            company_repo=company_repo,
            worker_worktree=materialized.working_dir,
        )
        retrieval_complete, retrieval_detail = _audit_evaluator_retrieval(monitor.events)
        tracked = tuple(
            line.strip().replace("\\", "/")
            for line in _git(company_repo, "ls-files").stdout.splitlines()
            if line.strip()
        )
        snapshot = T1Snapshot(
            task_status=task.status.value if task is not None else "missing",
            worker_run_principals=tuple(run.principal_id for run in worker_runs),
            worker_run_statuses=tuple(run.status.value for run in worker_runs),
            verifier_run_principals=tuple(run.principal_id for run in verifier_runs),
            verifier_run_statuses=tuple(run.status.value for run in verifier_runs),
            dod_status=dod.status.value if dod is not None else "missing",
            artifact_types=tuple(artifact.type.value for artifact in artifacts),
            pr_merged=pr_ref.get("merged") is True,
            pr_target=str(pr_ref.get("into", "")),
            company_branch=_git(company_repo, "branch", "--show-current").stdout.strip(),
            gate_exit_code=gate.returncode,
            shipped_paths=tracked,
            red_evidence_verdict=_manifest_verdict(
                materialized.working_dir / "test_evidence" / "red.json"
            ),
            tdd_chronology_valid=tdd_valid,
            review_provenance_valid=review_valid,
            evaluator_retrieval_complete=retrieval_complete,
            secret_redaction_safe=False,
            tool_use_count=len(tool_uses),
            tool_result_count=len(tool_results),
            all_tool_results_lossless=bool(tool_results)
            and all("content" in event.payload for event in tool_results),
            event_count=len(monitor.events),
            trace_count=len(traces),
        )
        invariants = evaluate_invariants(snapshot)
        print(f"TDD audit: {tdd_detail}", flush=True)
        print(f"review audit: {review_detail}", flush=True)
        print(f"evaluator retrieval audit: {retrieval_detail}", flush=True)
        report = _render_report(
            run_root=run_root,
            deployment=deployment,
            snapshot=snapshot,
            invariants=invariants,
            employee=employee,
            task=task,
            runs=list(runs),
            dod=dod,
            artifacts=list(artifacts),
            activities=list(activities),
            decisions=list(decisions),
            events=monitor.events,
            worker_prompts=worker_prompts,
            verifier_prompts=verifier_prompts,
            traces=traces,
            gate=gate,
            company_repo=company_repo,
        )
        report_path = run_root / "report.md"
        report_path.write_text(redact_text(report, secrets), encoding="utf-8")
        if events_path.exists():
            events_path.write_text(
                redact_text(events_path.read_text(encoding="utf-8"), secrets), encoding="utf-8"
            )
        redaction_safe, redaction_detail = _audit_redaction(
            [report_path, events_path, *traces], secrets
        )
        snapshot = replace(snapshot, secret_redaction_safe=redaction_safe)
        invariants = evaluate_invariants(snapshot)
        report = _render_report(
            run_root=run_root,
            deployment=deployment,
            snapshot=snapshot,
            invariants=invariants,
            employee=employee,
            task=task,
            runs=list(runs),
            dod=dod,
            artifacts=list(artifacts),
            activities=list(activities),
            decisions=list(decisions),
            events=monitor.events,
            worker_prompts=worker_prompts,
            verifier_prompts=verifier_prompts,
            traces=traces,
            gate=gate,
            company_repo=company_repo,
        )
        report_path.write_text(redact_text(report, secrets), encoding="utf-8")
        final_redaction_safe, final_redaction_detail = _audit_redaction(
            [report_path, events_path, *traces], secrets
        )
        if final_redaction_safe != snapshot.secret_redaction_safe:
            snapshot = replace(snapshot, secret_redaction_safe=final_redaction_safe)
            invariants = evaluate_invariants(snapshot)
        print(f"secret redaction audit: {final_redaction_detail or redaction_detail}", flush=True)
        args.output_root.mkdir(parents=True, exist_ok=True)
        latest = args.output_root / "T1-latest.md"
        shutil.copyfile(report_path, latest)

        print("\nT1 invariants:")
        for check in invariants:
            print(f"  {'PASS' if check.passed else 'FAIL'} {check.name}: {check.detail}")
        print(f"report: {report_path}")
        print(f"latest: {latest}")
        return 0 if all(check.passed for check in invariants) else 1
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
