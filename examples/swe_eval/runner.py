"""Run one benchmark case through an employee and capture its candidate patch.

Seeds ``EmployeeHarnessFactory`` with the prepared base-commit tree, materializes the case's role,
submits the issue text as the task intent, then captures the worktree's diff against the seeded ``main``
as the candidate patch. The beat's own Definition-of-Done verdict is recorded but is NOT the benchmark
oracle — that is ``evaluate.py``'s job (objective test-patch, else LLM judge).
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from chorus.events import Event, EventKind
from chorus.roles import RoleRegistry, default_roles
from chorus.roles._plugin import RolePlugin
from chorus.workforce import Employee
from chorus_harness import EmployeeHarnessFactory

from swe_eval.case import BenchCase, CandidateSolution
from swe_eval.env import ModelCreds

# git pathspecs excluded from the candidate diff: build outputs + operational dirs that are incidental
# to a code fix and would only add noise to the judge / overlap signals.
_DIFF_EXCLUDES = (
    ":(exclude)node_modules",
    ":(exclude)dist",
    ":(exclude)build",
    ":(exclude)coverage",
    ":(exclude).harness",
    ":(exclude).dream",
    ":(exclude)test_evidence",
    ":(exclude)*.lock",
    ":(exclude)package-lock.json",
)


def _safe_id(case_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", case_id).strip("-")[:60] or "case"


def plugins_by_name() -> dict[str, RolePlugin]:
    """Map role slug -> its plugin, so any role's DoD generator is reachable generically."""
    return {p.name: p for p in default_roles()}


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=120)


def capture_candidate_diff(worktree: Path) -> str:
    """Stage everything (minus build/op noise) and diff against the seeded base ``main``."""
    _git("add", "-A", cwd=worktree)
    res = _git("diff", "--cached", "main", "--", ".", *_DIFF_EXCLUDES, cwd=worktree)
    return res.stdout if res.returncode == 0 else ""


async def run_case(
    case: BenchCase,
    *,
    creds: ModelCreds,
    seed_dir: Path,
    workdir: Path,
    timeout_s: float = 1800.0,
    on_event: Callable[[str], None] | None = None,
) -> CandidateSolution:
    """Run ``case`` end-to-end through its employee and return the captured candidate solution."""
    company = f"swe-{_safe_id(case.id)}"
    company_dir = workdir / ".chorus" / "work" / company
    _force_rmtree(company_dir)

    roles = RoleRegistry.from_plugins(default_roles())
    factory = EmployeeHarnessFactory(
        api_key=creds.api_key,
        base_url=creds.base_url,
        deployment=creds.deployment,
        company_id=company,
        roles=roles,
        timeout_s=timeout_s,
        seed=seed_dir,
    )
    mat = factory.materialize(Employee(id=case.role, name=case.role.title(), role=case.role))

    verifier = plugins_by_name()[case.role].dod_generator(case.issue_text)

    trace: list[str] = []

    def _observer(ev: Event) -> None:
        if ev.kind is EventKind.RUN_TOOL_USE:
            line = f"[tool] {ev.payload.get('tool')} {str(ev.payload.get('input'))[:160]}"
            trace.append(line)
            if on_event:
                on_event(line)

    run_id = f"run-{_safe_id(case.id)}"
    beat_passed = False
    summary = ""
    error = ""
    try:
        outcome = await mat.runner.run_task(
            task_id=run_id,
            intent=case.issue_text,
            run_id=run_id,
            verification=verifier.verification_steps(),
            rubric=verifier.rubric(),
            observer=_observer,
        )
        beat_passed = bool(outcome.passed)
        summary = str(outcome.summary)
    except Exception as exc:  # a crashed beat is a (failed) result, not a harness crash
        error = repr(exc)

    wd = Path(mat.working_dir)
    diff = capture_candidate_diff(wd)
    return CandidateSolution(
        case_id=case.id,
        beat_passed=beat_passed,
        summary=summary,
        diff=diff,
        working_dir=str(wd),
        error=error,
        trace=trace,
    )


def _force_rmtree(path: Path) -> None:
    """Remove a tree even when it holds read-only git objects (the Windows rmtree footgun)."""
    import contextlib
    import os
    import shutil
    import stat

    if not path.exists():
        return

    def _onerror(func: object, p: str, _exc: object) -> None:
        with contextlib.suppress(Exception):
            os.chmod(p, stat.S_IWRITE)
            func(p)  # type: ignore[operator]

    with contextlib.suppress(Exception):
        shutil.rmtree(path, onerror=_onerror)
