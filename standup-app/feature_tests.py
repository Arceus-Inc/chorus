"""Feature exercises for chorus — drives the wired-but-untested surfaces end to end.

Reuses the standup-app's supported build path (``_build_company`` over ``Chorus.build``) and pokes the
features catalogued in ``post-dev-wiring-tested.md``: PM doc outcome, Analyst finding outcome, and
cron routines (auto-provision + add/pause/resume). Each test prints a PASS/FAIL line with the ledger /
git signal it checked.

    uv run python standup-app/feature_tests.py routine     # live every-minute cron fires in a real org
    uv run python standup-app/feature_tests.py pm          # PM writes plan.md → lands as a doc
    uv run python standup-app/feature_tests.py analyst     # Analyst writes findings.md → finding
    uv run python standup-app/feature_tests.py governance  # hire-approval gate holds a pending hire
    uv run python standup-app/feature_tests.py budgets     # a 1¢ cap hard-stops a beat, raise resumes
    uv run python standup-app/feature_tests.py memory      # a fact saved in beat 1 is recalled in beat 2
    uv run python standup-app/feature_tests.py all
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # import the sibling run.py helpers
import run as app  # noqa: E402
from chorus import (  # noqa: E402
    ApprovalDecision,
    BudgetScope,
    Chorus,
    GovernanceFacade,
    TaskStatus,
    Verifier,
)
from chorus.governance import GovernancePolicy  # noqa: E402
from chorus.ledger import ApprovalSubjectKind, BudgetThreshold  # noqa: E402

_TERMINAL = frozenset({TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.REJECTED})
# An objective, OS-portable DoD: the named deliverable file exists, is non-empty, and (optionally)
# mentions every required token — so a beat that writes a generic stub instead of addressing the brief
# FAILS the gate instead of passing. (PM/Analyst default DoD is an agent_review that needs a second
# reviewer LLM; this keeps the test deterministic so it isolates the *lander* AND the on-brief content.)
def _file_present_gate(name: str, *, contains: tuple[str, ...] = ()) -> Verifier:
    toks = list(contains)
    return Verifier.command(
        f'python -c "import os,sys; p={name!r}; t={toks!r}; '
        f"b=open(p,encoding='utf-8').read().lower() if os.path.exists(p) else ''; "
        f'sys.exit(0 if b.strip() and all(k.lower() in b for k in t) else 1)"'
    )


def _ok(label: str, cond: bool, detail: str = "") -> bool:
    mark = "\033[92mPASS\033[0m" if cond else "\033[91mFAIL\033[0m"
    print(f"  [{mark}] {label}" + (f"  — {detail}" if detail else ""))
    return cond


async def _drive(org: Chorus, task_id: str, *, max_pulses: int = 24) -> str:
    """Single-step the heartbeat until the task settles (the deterministic solo cadence)."""
    for n in range(1, max_pulses + 1):
        await org.tick()
        await org.drain()
        view = org.inspect.task(task_id)
        beat = view.latest_run.status if view.latest_run is not None else "-"
        print(f"    — pulse {n}: task={view.status.value} last_beat={beat}")
        if view.status in _TERMINAL:
            break
    return org.inspect.task(task_id).status.value


def _branch_file(company_main: Path, employee_id: str, fname: str) -> str:
    """The committed deliverable on the employee's landing branch (the lander commits chorus/{eid})."""
    return app._git(company_main, "show", f"chorus/{employee_id}:{fname}")


def _artifacts(org: Chorus, task_id: str) -> list:
    return list(org._ledger.artifacts.list_for_task(task_id))


# ── tests ────────────────────────────────────────────────────────────────────────────────────────

async def test_routine(org: Chorus, company_main: Path, base: Path) -> bool:
    print("\n\033[96m● ROUTINE — a real every-minute cron fires in a live org and the spawned task runs\033[0m")
    org.hire(name="moe", role="manager")
    eng = org.hire(name="eng1", role="engineer", reports_to="moe")
    org.hire(name="pat", role="pm", reports_to="moe")

    # (a) hiring a PM auto-provisions its standing weekly-planning routine (no firing — Monday 09:00).
    auto = org.routines.list(employee="pat")
    crons = [t.cron_expression for r in auto for t in r.triggers]
    ok1 = _ok("hiring a PM auto-provisions the weekly-planning routine",
              any(c == "0 9 * * 1" for c in crons), f"crons={crons}")

    # (b) add a real every-minute routine on the engineer, then let the LIVE heartbeat fire it.
    rid = org.routines.add(
        employee="eng1",
        intent_template=(
            "Append a single line containing the current date to a file named NOTES.md in the "
            "repository root (create it if missing), then commit. Touch no other files. pytest and "
            "ruff are already installed — do NOT run pip install, and do NOT run git push."
        ),
        schedule="* * * * *",
        routine_key="every-minute-notes",
    ).id
    print(f"    added routine {rid} (* * * * *) on eng1 — starting the heartbeat, waiting for a fire…")

    org.start()
    fired_task: str | None = None
    final = "-"
    try:
        deadline = time.monotonic() + 220.0
        while time.monotonic() < deadline:
            await asyncio.sleep(3.0)
            r = org.routines.get(rid)
            fires = [run for run in r.recent_runs if run.linked_task_id]
            last = r.triggers[0].last_fired_at if r.triggers else None
            if fired_task is None and fires:
                fired_task = fires[0].linked_task_id
                print(f"    ⏰ routine fired (last_fired_at={last}) → spawned task {fired_task}")
            if fired_task is not None:
                st = org.inspect.task(fired_task).status.value
                print(f"    — spawned task {fired_task}: {st}")
                if st in {s.value for s in _TERMINAL}:
                    final = st
                    break
    finally:
        await org.stop()

    ok2 = _ok("the every-minute cron fired and spawned a task", fired_task is not None,
              f"task={fired_task}")
    ok3 = _ok("the spawned task is a real ledger task assigned to the routine owner",
              fired_task is not None
              and org.inspect.task(fired_task).assignee == eng.id,
              f"assignee={org.inspect.task(fired_task).assignee if fired_task else None}")
    notes = _branch_file(company_main, eng.id, "NOTES.md") if fired_task else ""
    ok4 = _ok("the spawned task ran to DONE and committed NOTES.md",
              final == "done" and bool(notes.strip()),
              f"status={final}, NOTES.md={notes[:50]!r}")
    return all((ok1, ok2, ok3, ok4))


async def test_pm(org: Chorus, company_main: Path, base: Path) -> bool:
    print("\n\033[96m● PM — planning task → plan.md lands as a `doc` artifact\033[0m")
    org.hire(name="moe", role="manager")
    pat = org.hire(name="pat", role="pm", reports_to="moe")
    goal = (
        "Write an implementation plan for a small Python `csvstats` CLI that reads a CSV and prints, "
        "per numeric column, the count/min/max/mean. In `plan.md` ONLY, specify: scope and non-goals, "
        "the file layout (module names + responsibilities), the public function signatures, the CLI "
        "contract (arguments + exact stdout format), the test cases an engineer must write, and the "
        "smallest ordered list of next steps. Be decisive — no open questions. Do NOT write any code; "
        "`plan.md` IS the deliverable."
    )
    task = org.submit(
        goal, assignee="pat",
        dod=_file_present_gate(app_PM_DOC := "plan.md", contains=("csv", "mean")),
    )
    print(f"    submitted {task.id} → pat (pm)")
    final = await _drive(org, task.id)

    ok1 = _ok("PM task reached DONE", final == "done", f"status={final}")
    arts = _artifacts(org, task.id)
    ok2 = _ok("a `doc` artifact was recorded", any(a.type.value == "doc" for a in arts),
              f"artifacts={[a.type.value for a in arts]}")
    body = _branch_file(company_main, pat.id, app_PM_DOC)
    ok3 = _ok("plan.md committed on the PM's landing branch and non-empty", bool(body.strip()),
              f"{len(body)} chars: {body[:70]!r}…")
    return all((ok1, ok2, ok3))


async def test_analyst(org: Chorus, company_main: Path, base: Path) -> bool:
    print("\n\033[96m● ANALYST — research task → findings.md lands as a `finding` artifact\033[0m")
    org.hire(name="moe", role="manager")
    ana = org.hire(name="ana", role="analyst", reports_to="moe")
    goal = (
        "Investigate: in Python's standard library, what is the difference between `os.path.join` and "
        "`pathlib.Path` for building filesystem paths, and which should new code prefer? In "
        "`findings.md` ONLY, give the answer, two concrete evidence points (with the behaviour each "
        "shows), and the one-line implication for a new codebase. State concrete findings a reviewer "
        "can check — not a restatement of the question. Do NOT write any code; `findings.md` IS the "
        "deliverable."
    )
    task = org.submit(
        goal, assignee="ana",
        dod=_file_present_gate(fdoc := "findings.md", contains=("pathlib", "os.path")),
    )
    print(f"    submitted {task.id} → ana (analyst)")
    final = await _drive(org, task.id)

    ok1 = _ok("Analyst task reached DONE", final == "done", f"status={final}")
    arts = _artifacts(org, task.id)
    ok2 = _ok("a `finding` artifact was recorded", any(a.type.value == "finding" for a in arts),
              f"artifacts={[a.type.value for a in arts]}")
    body = _branch_file(company_main, ana.id, fdoc)
    ok3 = _ok("findings.md committed on the Analyst's landing branch and non-empty", bool(body.strip()),
              f"{len(body)} chars: {body[:70]!r}…")
    return all((ok1, ok2, ok3))


async def test_governance(org: Chorus, company_main: Path, base: Path) -> bool:
    print("\n\033[96m● GOVERNANCE — a hire-approval gate holds a new hire PENDING until a human signs off\033[0m")
    # Arm the hire gate. `Chorus.build` wires the empty default policy; swap in a gated one over the same
    # ledger/workforce/roles so `request_hire` opens an approval instead of hiring directly.
    org._governance = GovernanceFacade(
        org._ledger, org._workforce, org._roles, GovernancePolicy(require_hire_approval=True)
    )
    boss = org.hire(name="boss", role="manager")  # the manager is a direct hire (no gate on org.hire)

    req = org.governance.request_hire(name="rookie", role="engineer", reports_to=boss.id)
    ok1 = _ok("request_hire opened a pending hire_employee approval (not a direct hire)",
              req.approval is not None, f"approval={getattr(req.approval, 'id', None)}")
    assert req.approval is not None  # narrowed by ok1; below we resolve it
    ok2 = _ok("the new hire is created PENDING (uninvokable until approved)",
              org._workforce.get(req.employee.id).status.value == "pending",
              f"status={org._workforce.get(req.employee.id).status.value}")
    inbox = org.governance.approvals()
    ok3 = _ok("the approval shows up in the open-gate inbox",
              any(a.id == req.approval.id for a in inbox), f"inbox={[a.id for a in inbox]}")

    # Assign real work to the still-pending hire — the invokability gate must hold the wake (no run).
    task = org.submit(
        "Create a file named greeting.txt in the repository root whose only line is "
        "'approved-hire ok', then commit. Touch no other files. Do NOT run pip install or git push.",
        assignee="rookie",
        dod=_file_present_gate("greeting.txt", contains=("approved-hire",)),
    )
    print(f"    submitted {task.id} → rookie (PENDING) — driving a few pulses; it must NOT run yet")
    held = await _drive(org, task.id, max_pulses=4)
    ok4 = _ok("the pending hire's task is held (no beat runs while uninvokable)",
              held != "done", f"status={held}")

    # Approve → the hire goes active and the held wake becomes dispatchable.
    org.governance.resolve(req.approval.id, decision=ApprovalDecision.APPROVE, by="ceo")
    ok5 = _ok("after APPROVE the hire is active",
              org._workforce.get(req.employee.id).status.value == "active",
              f"status={org._workforce.get(req.employee.id).status.value}")
    print(f"    approved {req.employee.id} — driving the held task to completion")
    final = await _drive(org, task.id)
    body = _branch_file(company_main, req.employee.id, "greeting.txt") if final == "done" else ""
    ok6 = _ok("the approved hire then runs the task to DONE and commits greeting.txt",
              final == "done" and "approved-hire" in body.lower(),
              f"status={final}, greeting.txt={body[:40]!r}")
    return all((ok1, ok2, ok3, ok4, ok5, ok6))


async def test_budgets(org: Chorus, company_main: Path, base: Path) -> bool:
    print("\n\033[96m● BUDGETS — the first beat's spend trips a hard stop that pauses NEW work until the cap is raised\033[0m")
    org.hire(name="moe", role="manager")
    eng = org.hire(name="eng1", role="engineer", reports_to="moe")
    # The company budget scope id is the company_id the factory builds under ("acme"), not "company".
    pol = org.budgets.set(BudgetScope.COMPANY, "acme", amount_cents=1)
    print(f"    set a 1¢ MONTHLY company cap (policy {pol.id}) — any real beat exceeds it")

    # Beat 1 runs and its metered spend trips Gate 2 *post-hoc* (the cost event is priced AFTER the
    # beat), so this single-beat task finishes — the hard stop's job is to pause the NEXT invocation.
    first = org.submit(
        "Create a Python module `mathx.py` in the repository root with a function "
        "`def add(a, b): return a + b`, then commit. Touch no other files. pytest and ruff are "
        "installed — do NOT run pip install, and do NOT run git push.",
        assignee="eng1",
        dod=_file_present_gate("mathx.py", contains=("def add",)),
    )
    print(f"    submitted {first.id} → eng1 — its spend should trip the hard stop")
    await _drive(org, first.id, max_pulses=6)

    incidents = org._ledger.budget_incidents.open_for_policy(pol.id)
    hard = [i for i in incidents if i.threshold_type is BudgetThreshold.HARD]
    ok1 = _ok("a HARD budget incident opened once spend ≥ the cap",
              bool(hard), f"open incidents={[(i.threshold_type.value, i.amount_observed) for i in incidents]}")
    pending = org._ledger.approvals.pending()
    ok2 = _ok("a budget-incident approval is pending (a human must decide resume/dismiss)",
              any(a.subject_kind is ApprovalSubjectKind.BUDGET_INCIDENT for a in pending),
              f"pending={[a.subject_kind.value for a in pending]}")

    # The scope is now paused. A NEW task must be held pre-dispatch by Gate 1 (invocation_block).
    blocked = org.submit(
        "Create a Python module `mathy.py` in the repository root with a function "
        "`def sub(a, b): return a - b`, then commit. Touch no other files. Do NOT run pip install, "
        "and do NOT run git push.",
        assignee="eng1",
        dod=_file_present_gate("mathy.py", contains=("def sub",)),
    )
    print(f"    submitted {blocked.id} while paused — driving a few pulses; it must NOT run")
    held = await _drive(org, blocked.id, max_pulses=4)
    ok3 = _ok("new work is blocked pre-dispatch while the scope is paused", held != "done",
              f"status={held}")

    # Raise the cap above observed spend → the resume path clears the incident and unpauses the scope.
    org.budgets.raise_(pol.id, new_amount_cents=10_000_000, by="cfo")
    still_hard = [
        i for i in org._ledger.budget_incidents.open_for_policy(pol.id)
        if i.threshold_type is BudgetThreshold.HARD
    ]
    ok4 = _ok("raising the cap cleared the hard incident (scope resumed)", not still_hard,
              f"remaining hard incidents={len(still_hard)}")

    org.assign(blocked.id, eng.id)  # re-wake the held task now that the scope is live again
    print(f"    raised the cap and re-woke {blocked.id} — driving to completion")
    final = await _drive(org, blocked.id)
    body = _branch_file(company_main, eng.id, "mathy.py") if final == "done" else ""
    ok5 = _ok("after the raise the blocked work runs and commits mathy.py",
              final == "done" and "def sub" in body.lower(), f"status={final}, mathy.py={body[:40]!r}")
    return all((ok1, ok2, ok3, ok4, ok5))


async def test_memory(org: Chorus, company_main: Path, base: Path) -> bool:
    print("\n\033[96m● MEMORY — a fact saved to durable memory in beat 1 is recalled (not re-derivable) in beat 2\033[0m")
    org.hire(name="moe", role="manager")
    eng = org.hire(name="eng1", role="engineer", reports_to="moe")
    codename = "BLUEFIN-42"  # a coined token — it is in NO file, so beat 2 can only get it from memory

    # Beat 1: hand the engineer the fact, ask it to persist it to durable memory, and prove it ran by
    # writing an ack file that must NOT contain the codename (so memory is the only carrier).
    t1 = org.submit(
        f"Remember this project fact for later tasks: the release-7 codename is {codename}. "
        "Use your durable memory tools (memory_propose / memory_search) to record it so a future "
        "task can recall it. Then create a file named ack.txt in the repository root whose only line "
        f"is 'codename recorded' and commit. Do NOT write {codename} into ack.txt or any other file — "
        "it must live only in memory. Do NOT run pip install or git push.",
        assignee="eng1",
        dod=_file_present_gate("ack.txt", contains=("recorded",)),
    )
    print(f"    submitted {t1.id} → eng1 (record the codename in memory)")
    first = await _drive(org, t1.id)
    ack = _branch_file(company_main, eng.id, "ack.txt") if first == "done" else ""
    ok1 = _ok("beat 1 reached DONE and the codename was kept OUT of the ack file",
              first == "done" and bool(ack.strip()) and codename.lower() not in ack.lower(),
              f"status={first}, ack.txt={ack[:40]!r}")

    # Beat 2: same engineer, same worktree — ask it to recall the codename from memory and write it out.
    t2 = org.submit(
        "A previous task recorded a project codename for release 7 in your durable memory. Use "
        "memory_search to recall it. WITHOUT guessing and WITHOUT reading ack.txt or any prior file, "
        "write the recalled release-7 codename as the only line of a file named codename.txt in the "
        "repository root and commit. Do NOT run pip install or git push.",
        assignee="eng1",
        dod=_file_present_gate("codename.txt", contains=(codename.lower(),)),
    )
    print(f"    submitted {t2.id} → eng1 (recall the codename from memory)")
    second = await _drive(org, t2.id)
    recalled = _branch_file(company_main, eng.id, "codename.txt") if second == "done" else ""
    ok2 = _ok("beat 2 reached DONE", second == "done", f"status={second}")
    ok3 = _ok("beat 2 recalled the codename from durable memory and wrote it out",
              codename.lower() in recalled.lower(), f"codename.txt={recalled[:40]!r}")
    return all((ok1, ok2, ok3))


_TESTS = {
    "routine": test_routine,
    "pm": test_pm,
    "analyst": test_analyst,
    "governance": test_governance,
    "budgets": test_budgets,
    "memory": test_memory,
}


async def _amain(which: list[str]) -> int:
    os.environ.setdefault("CHORUS_ENV_FILE", str(Path(__file__).resolve().parent.parent / ".env"))
    for v in app._REQUIRED:  # let the pinned .env win over any stale vars in the shell session
        os.environ.pop(v, None)
    app._load_env()
    if not all(os.environ.get(v) for v in app._REQUIRED):
        print("No model creds (need " + ", ".join(app._REQUIRED) + ")")
        return 2

    results: dict[str, bool] = {}
    for name in which:
        base = Path(tempfile.mkdtemp(prefix=f"chorus-feat-{name}-"))
        org, _factory, company_main = app._build_company(base, c=app._C(on=False), timeout_s=240.0)
        results[name] = await _TESTS[name](org, company_main, base)
        print(f"    (workspace: {base})")

    print("\n\033[97;1m── summary ──\033[0m")
    for name, passed in results.items():
        print(f"  {name:8s}: {'PASS' if passed else 'FAIL'}")
    return 0 if all(results.values()) else 1


def main() -> int:
    args = sys.argv[1:] or ["routine"]
    which = list(_TESTS) if args == ["all"] else [a for a in args if a in _TESTS]
    if not which:
        print(f"usage: feature_tests.py [{'|'.join(_TESTS)}|all]")
        return 2
    return asyncio.run(_amain(which))


if __name__ == "__main__":
    raise SystemExit(main())
