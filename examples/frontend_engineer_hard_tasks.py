"""Frontend Engineer hard tasks — increasingly hard, INTENT-ONLY, independently re-verified.

Each task states ONLY the user-visible behaviour we want — the product and what a person can do with
it — and says NOTHING about how to build it, what files to write, what to test, WHICH STACK to use, or
how the work will be checked. Finn (the frontend_engineer role) must choose everything end to end: size
the slice, CHOOSE the frontend stack that fits (hand-written HTML/JS, a component framework, or a
meta-framework), build a working app, unit-test the logic, drive it in a real browser with Playwright,
capture the evidence, run the two review subagents, and go green.

The load-bearing part of this script is the INDEPENDENT re-verification. After each beat lands, we do
NOT trust the transcript or even the captured logs: we re-run the shipped code ourselves — the project's
wired unit runner via ``npm test`` and Playwright over the e2e suite — from a clean process, in the
worktree the employee actually produced. Both re-runs are done with ``CI=1`` so any watch-mode runner
exits instead of hanging. A task only counts as truly passed when the deterministic DoD floor passes AND
both suites go green again under our own hands. That is what makes a fabricated log or a test that
doesn't match the app impossible to hide — and it stays framework-agnostic because it drives only the
neutral, stack-declared entry points (``npm test`` + ``npx playwright test``).

Each task uses its own company id so the worktrees never collide. The script skips cleanly (exit 0) when
the AZURE_OPENAI_* env vars are unset, and accepts an optional list of task keys on argv to run a subset
(e.g. `uv run python examples/frontend_engineer_hard_tasks.py tip` runs just the first one).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from chorus.events import Event, EventKind
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee
from chorus_employee.frontend_engineer import (
    TEST_EVIDENCE_DIR,
    frontend_engineer_plugin,
)
from chorus_harness import EmployeeHarnessFactory

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

# Make `python` / `node` / `npx` on PATH resolve to the same interpreter dir first (mirrors the
# environment the beat itself runs under).
os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")

# Let the sibling flow-report generator import cleanly regardless of the process cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _load_env() -> None:
    """Fold the repo-root ``chorus/.env`` (or ``CHORUS_ENV_FILE``) into the environment.

    The pinned ``.env`` is AUTHORITATIVE: it OVERRIDES any pre-existing shell value rather than
    deferring to it (mirrors ``standup-app/run.py::_load_env``). This is the fix for the footgun
    where a stale session var (e.g. a leftover ``AZURE_OPENAI_DEPLOYMENT=gpt-5.4-mini`` pointing at a
    different endpoint) silently defeats the pinned config and starves the toolless planner so it
    never emits ``<spec>``. Any override of a *differing* live value is announced, so the
    substitution is never silent. Secrets stay in the gitignored ``.env``, never in this file.
    """
    default = Path(__file__).resolve().parent.parent / ".env"
    path = Path(os.environ.get("CHORUS_ENV_FILE", str(default)))
    if not path.exists():
        return
    overridden: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        prev = os.environ.get(key)
        if prev is not None and prev != value:
            overridden.append(key)
        os.environ[key] = value
    if overridden:
        print(f"  (.env overrode stale shell value(s): {', '.join(sorted(set(overridden)))})")


@dataclass(frozen=True)
class _Task:
    key: str
    intent: str


# Ordered easiest -> hardest. Intent only: the product and what a person can DO — never a file, a test,
# a technology, an ARIA attribute, or anything about how the result will be verified.
_TASKS: tuple[_Task, ...] = (
    _Task(
        key="tip",
        intent=(
            "Build a single-page bill-splitting helper. Someone enters the bill amount, chooses or types "
            "a tip percentage, and sets how many people are sharing the bill; the page immediately shows "
            "the tip in money, the grand total including tip, and the amount each person pays. It should "
            "behave sensibly when the inputs are still empty or not yet valid rather than showing broken "
            "or nonsensical numbers."
        ),
    ),
    _Task(
        key="tasks",
        intent=(
            "Build a to-do list page. A person can add a task, mark a task as done, and remove a task, "
            "and can switch the visible list between all tasks, only the ones still to do, and only the "
            "finished ones. Somewhere on screen there is always an accurate count of how many tasks are "
            "still unfinished, and it stays correct as tasks are added, completed, and removed."
        ),
    ),
    _Task(
        key="rsvp",
        intent=(
            "Build an event RSVP page. The guest gives their name, an email address, how many people "
            "they are bringing, and whether they need a vegetarian meal. The page checks the answers, "
            "keeps the confirm/submit action unavailable until everything given is acceptable, tells the "
            "guest clearly what is wrong with any individual field in a way that someone using a screen "
            "reader would also hear, and on a good submission replaces the form with a confirmation that "
            "repeats back what they chose."
        ),
    ),
    _Task(
        key="board",
        intent=(
            "Build a small task board with three lanes: to do, in progress, and done. A person can add a "
            "card to the first lane, move any card forward or backward between adjacent lanes, and remove "
            "a card. Every one of those actions must be fully doable using only the keyboard, and the "
            "board must show the same cards in the same lanes after the browser is refreshed as it did "
            "before."
        ),
    ),
    _Task(
        key="shop",
        intent=(
            "Build a small storefront that works as one continuous experience across three connected "
            "views: a browsable list of products, a single product's detail page, and a cart. From the "
            "list a person can open any product to see its details and add it to the cart; from a "
            "product's details they can return to browsing; and from anywhere they can open the cart to "
            "change item quantities or remove items. A running count of items in the cart and the current "
            "total are visible at all times and stay correct as things are added, changed, and removed "
            "while moving between the different views. Navigating the storefront must feel like a real "
            "app: a person can use the browser's back and forward buttons to retrace their steps, opening "
            "a link to a specific product or the cart directly lands on the right view, and whatever is "
            "in the cart survives all of that moving around."
        ),
    ),
)


def _short(value: object, n: int = 160) -> str:
    s = str(value).replace("\n", " / ")
    return s if len(s) <= n else s[:n] + "..."


# Everything the observer prints is also captured here so each task can persist a `flow.log`, which the
# flow-report generator turns into HTML. Cleared at the start of every task in `_run_one`.
_captured: list[str] = []


def _emit(line: str, capture: str | None = None) -> None:
    print(line)
    _captured.append(capture if capture is not None else line)


def _observer(ev: Event) -> None:
    p = ev.payload
    if ev.kind is EventKind.RUN_TOOL_USE:
        tool = p.get("tool")
        inp = p.get("input")
        # Print a tidy short line, but capture a longer payload so the report keeps the key argument
        # (path / command / name) even for tools whose input dict is large.
        _emit(f"  [tool ->] {tool}  {_short(inp)}", f"  [tool ->] {tool}  {_short(inp, 500)}")
    elif ev.kind is EventKind.RUN_TOOL_RESULT:
        flag = " (ERROR)" if p.get("is_error") else ""
        _emit(f"  [tool <-] {p.get('tool')}{flag}")
    elif ev.kind is EventKind.RUN_EVALUATED:
        keys = {k: v for k, v in p.items() if k != "dream_kind"}
        _emit(f"  [EVALUATED] {_short(keys, 500)}")
    elif ev.kind is EventKind.RUN_DONE:
        _emit("== beat done ==")


def _artifacts_root() -> Path:
    root = Path("chorus") if Path("chorus").is_dir() else Path(".")
    out = root / "reports" / "frontend-engineer-artifacts"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _force_rmtree(path: Path) -> None:
    """Remove a tree even when it holds read-only files (the usual Windows rmtree footgun).

    Git packs objects read-only, so a plain ``shutil.rmtree`` raises ``PermissionError`` on Windows and
    leaves the worktree — and the planner's spec/ledger artefacts — behind. A stale ledger then trips
    dream's runs-once guard on the next run (``planner has already produced artefacts``). The onerror
    handler flips the read-only bit and retries, which clears the vast majority of these.
    """
    if not path.exists():
        return

    def _onerror(func: object, p: str, _exc: object) -> None:
        with contextlib.suppress(Exception):
            os.chmod(p, stat.S_IWRITE)
            func(p)  # type: ignore[operator]

    with contextlib.suppress(Exception):
        shutil.rmtree(path, onerror=_onerror)


async def _rerun(cmd: str, cwd: Path, timeout_s: float, *, env: dict[str, str] | None = None) -> tuple[int | None, str]:
    """Independently run a command in the shipped worktree and capture combined output + exit code.

    Uses the same shell dream's oracle uses (cmd.exe on Windows, /bin/sh on POSIX), so this re-run is a
    faithful reproduction of the after-beat verification — no setup, no install, just the code as shipped.
    ``env`` (when given) fully replaces the child environment; callers pass ``CI=1`` so a watch-mode
    unit runner (vitest/jest) exits instead of hanging the re-run.
    """
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
    except OSError as exc:  # shell/tool genuinely not launchable
        return None, f"[could not launch] {cmd}: {exc}"
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        return None, f"[timed out after {timeout_s:.0f}s] {cmd}"
    return proc.returncode, out.decode("utf-8", errors="replace")


def _copy_worktree_artifacts(working_dir: Path, dest: Path) -> list[str]:
    """Copy the interesting, human-inspectable parts of the worktree (never node_modules)."""
    dest.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []

    def _ignore(_dir: str, names: list[str]) -> set[str]:
        return {n for n in names if n in {"node_modules", ".git", "test-results", "playwright-report"}}

    # top-level source files (any stack: vanilla, TS, JSX/TSX, Vue SFC, Svelte, + config/manifests)
    for pat in (
        "*.html", "*.js", "*.mjs", "*.cjs", "*.ts", "*.mts", "*.jsx", "*.tsx",
        "*.vue", "*.svelte", "*.css", "*.json",
    ):
        for f in working_dir.glob(pat):
            if f.is_file():
                with contextlib.suppress(Exception):
                    shutil.copy2(f, dest / f.name)
                    saved.append(f.name)
    # source + test + evidence directories (whatever layout the chosen stack uses)
    for sub in ("src", "tests", "test", "e2e", "public", "app", TEST_EVIDENCE_DIR):
        srcdir = working_dir / sub
        if srcdir.is_dir():
            with contextlib.suppress(Exception):
                shutil.copytree(srcdir, dest / sub, ignore=_ignore, dirs_exist_ok=True)
                saved.append(f"{sub}/")
    return saved


@dataclass
class _Result:
    key: str
    beat_passed: bool
    unit_code: int | None
    e2e_code: int | None
    summary: str

    @property
    def truly_passed(self) -> bool:
        return self.beat_passed and self.unit_code == 0 and self.e2e_code == 0


async def _run_one(task: _Task, key: str, base: str, dep: str, api_key: str) -> _Result:
    workroot = Path("chorus") if Path("chorus").is_dir() else Path(".")
    company = f"frontend-eng-hard-{task.key}"
    company_dir = workroot / ".chorus" / "work" / company
    _force_rmtree(company_dir)
    if company_dir.exists():
        print(
            f"[{task.key}] WARNING: could not fully remove {company_dir}. The planner runs-once guard "
            f"may fire on stale spec/ledger — close anything holding files there and retry."
        )

    roles = RoleRegistry.from_plugins(default_roles())
    factory = EmployeeHarnessFactory(
        api_key=api_key, base_url=base, deployment=dep, company_id=company,
        roles=roles, timeout_s=1800.0,
    )
    mat = factory.materialize(Employee(id="finn", name="Finn", role="frontend_engineer"))

    verifier = frontend_engineer_plugin().dod_generator(task.intent)
    print("\n" + "=" * 90)
    print(f"TASK [{task.key}]  DoD -> {verifier.kind.value}")
    print(f"intent: {task.intent}")
    print("=" * 90)

    _captured.clear()
    run_id = f"run-{task.key}"
    outcome = await mat.runner.run_task(
        task_id=run_id, intent=task.intent, run_id=run_id,
        verification=verifier.verification_steps(), rubric=verifier.rubric(), observer=_observer,
    )
    print(f"\n[{task.key}] beat passed (DoD floor) = {outcome.passed}")
    print(f"[{task.key}] summary = {_short(outcome.summary, 400)}")

    # --- INDEPENDENT RE-VERIFICATION: prove the shipped code actually works, from a clean process ------
    wd = mat.working_dir
    print(f"[{task.key}] re-verifying shipped code in {wd} ...")
    # Framework-agnostic re-run: `npm test` runs whatever unit runner the engineer wired into the
    # project's `test` script (node --test / vitest run / jest), and Playwright drives the real browser.
    # Both run with CI=1 so a watch-mode runner exits once instead of hanging the beat; the unit budget
    # is wider than a bare node run because a framework build/transpile is slower.
    ci_env = {**os.environ, "CI": "1"}
    unit_code, unit_out = await _rerun("npm test", wd, timeout_s=300.0, env=ci_env)
    print(f"[{task.key}]   npm test     -> exit {unit_code}")
    e2e_code, e2e_out = await _rerun("npx playwright test", wd, timeout_s=600.0, env=ci_env)
    print(f"[{task.key}]   playwright   -> exit {e2e_code}")

    # --- artifacts ------------------------------------------------------------------------------------
    dest = _artifacts_root() / task.key
    saved = _copy_worktree_artifacts(wd, dest)
    (dest / "reverify_unit.txt").write_text(
        f"$ npm test\n[exit {unit_code}]\n\n{unit_out}", encoding="utf-8"
    )
    (dest / "reverify_e2e.txt").write_text(
        f"$ npx playwright test\n[exit {e2e_code}]\n\n{e2e_out}", encoding="utf-8"
    )
    (dest / "_meta.txt").write_text(
        f"key={task.key}\n"
        f"beat_passed={outcome.passed}\n"
        f"reverify_unit_exit={unit_code}\n"
        f"reverify_e2e_exit={e2e_code}\n"
        f"truly_passed={outcome.passed and unit_code == 0 and e2e_code == 0}\n"
        f"intent={task.intent}\n"
        f"working_dir={wd}\n"
        f"summary={outcome.summary}\n",
        encoding="utf-8",
    )

    # Persist the captured observer trace + the independent verdict, then render the HTML flow report.
    truly = bool(outcome.passed) and unit_code == 0 and e2e_code == 0
    flow_lines = [f"intent: {task.intent}", ""]
    flow_lines.extend(_captured)
    flow_lines += [
        "",
        f"[verdict] dod_floor={'pass' if outcome.passed else 'fail'}",
        f"[verdict] unit_reverify_exit={unit_code}",
        f"[verdict] e2e_reverify_exit={e2e_code}",
        f"[verdict] truly_passed={truly}",
    ]
    (dest / "flow.log").write_text("\n".join(flow_lines), encoding="utf-8")
    try:
        from frontend_engineer_flow_report import write_report_for_task

        report = write_report_for_task(dest)
        print(f"[{task.key}] report -> {report}")
    except Exception as exc:  # a report glitch must never sink a genuinely-passing beat
        import traceback

        print(f"[{task.key}] report FAILED: {exc}")
        traceback.print_exc()

    print(f"[{task.key}] artifacts -> {dest}  :: {', '.join(saved) if saved else '(none)'}")

    return _Result(
        key=task.key,
        beat_passed=bool(outcome.passed),
        unit_code=unit_code,
        e2e_code=e2e_code,
        summary=str(outcome.summary),
    )


async def main() -> int:
    _load_env()
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base = os.environ.get("AZURE_OPENAI_BASE_URL")
    dep = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base and dep):
        print("skipping: set AZURE_OPENAI_API_KEY / AZURE_OPENAI_BASE_URL / AZURE_OPENAI_DEPLOYMENT")
        return 0

    wanted = {a.strip() for a in sys.argv[1:] if a.strip()}
    tasks = [t for t in _TASKS if not wanted or t.key in wanted]
    if not tasks:
        print(f"no matching tasks for {sorted(wanted)}; known: {[t.key for t in _TASKS]}")
        return 2

    results: list[_Result] = []
    for task in tasks:
        results.append(await _run_one(task, task.key, base, dep, api_key))

    # --- verdict table --------------------------------------------------------------------------------
    print("\n" + "=" * 90)
    print("FRONTEND ENGINEER HARD TASKS — INDEPENDENT VERDICT")
    print("=" * 90)
    print(f"{'task':<8} {'DoD floor':<11} {'unit re-run':<13} {'e2e re-run':<12} {'VERDICT'}")
    print("-" * 90)
    for r in results:
        print(
            f"{r.key:<8} "
            f"{'pass' if r.beat_passed else 'FAIL':<11} "
            f"{('exit ' + str(r.unit_code)):<13} "
            f"{('exit ' + str(r.e2e_code)):<12} "
            f"{'TRULY PASSED' if r.truly_passed else 'NOT PROVEN'}"
        )
    all_true = all(r.truly_passed for r in results)
    print("-" * 90)
    print(f"overall: {'ALL TRULY PASSED' if all_true else 'SOME NOT PROVEN'}  ({len(results)} task(s))")
    # Non-zero exit if any task failed independent re-verification, so CI/humans notice.
    return 0 if all_true else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
