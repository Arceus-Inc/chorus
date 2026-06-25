"""Drive a chorus org to ship ONE whole HARD_TASKS app from a THIN, goal-only brief.

This is the "horizon hands the org a single OKR leaf and walks away" run. Unlike ``run.py``'s
demo goals — which spell out every module, file, class, and decomposition — the brief here is an
*outcome and a done-bar only*. The org does the design: the team's PM writes the spec (the shared
contract), and the engineers build to it. The whole point is to prove the chorus+dream engine can
take a real product goal with NO tech decomposition and stand up a runnable, tested full-stack app.

Nothing task-specific lives in the chorus or dream packages — only this app script knows about
"boardsync". The engine stays generic; this runner just states the goal and watches the flow.

----------------------------------------------------------------------------------------------------
RUN IT (from the chorus repo root)

    uv run python standup-app/boardsync.py            # ship the real-time collaborative board

Flags:  --task "<text>"   override the thin goal
        --no-color        plain ASCII output
        --timeout N       per-beat wall-clock budget in seconds (default 420; a full-stack
                          install+build+test gate needs headroom)
        --deadline N      overall wall-clock ceiling in seconds (default 3000)
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Reuse the standup-app infrastructure verbatim. These helpers are GENERIC plumbing (color, the event
# narrator, the company builder, the git/summary helpers) — none of them know anything about boardsync.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run import (
    _C,
    _REQUIRED,
    _TEAM_GATE,
    _TERMINAL,
    _TERMINAL_VALUES,
    Narrator,
    _build_company,
    _hr,
    _load_env,
    _print_task_tree,
    _step,
    _summary,
)

from chorus import Chorus, Verifier

# ── the goal (HARD_TASKS #11 — boardsync, FULL-STACK) ────────────────────────────────────────────
#
# The product owner's brief. It states the OUTCOME and the three required pieces of a full-stack app
# (a WebSocket backend, a typed shared event-schema package both sides import, and a REAL React
# frontend) plus the done-bar — but prescribes NO file names, module list, protocol shape, or
# decomposition. The org designs all of that. The earlier "thin" brief let the team drop the browser
# UI by reading the headless-CI bar as "a programmatic client is fine instead of a frontend"; this
# brief closes that hole: the React UI is a DELIVERABLE, and the headless bar scopes ONLY the
# automated proof-tests (which may drive the channel from programmatic clients), not the product.
_THIN_GOAL = (
    "Build a full-stack real-time collaborative board (\"boardsync\") that a team uses together.\n"
    "\n"
    "It is a FULL-STACK web app with THREE parts that all ship in ONE repository:\n"
    "  1. A BACKEND server that exposes a WebSocket channel.\n"
    "  2. A TYPED SHARED EVENT-SCHEMA package — the wire/event contract as its own typed module that\n"
    "     BOTH the server and the frontend import, so there is ONE source of truth for the protocol.\n"
    "  3. A REACT FRONTEND — a real browser UI built with React.\n"
    "\n"
    "What it must do (the outcome — design and build everything yourself):\n"
    "- The React UI shows a board: cards arranged in COLUMNS. A person moves a card from one column "
    "to another in the UI.\n"
    "- Every connected client sees that move appear LIVE within one round-trip — no manual refresh, "
    "no polling delay the user notices.\n"
    "- OPTIMISTIC UI WITH SERVER RECONCILIATION: the mover's own UI updates immediately (optimistic), "
    "then reconciles to the server's authoritative state when the broadcast returns.\n"
    "- The board's state is durable: a move is never lost, even if a client disconnects right after "
    "making it. Moves are persisted to a log.\n"
    "- A person who closes their browser and reconnects immediately rebuilds the CURRENT state from "
    "that log/snapshot — every card in its latest column — without anyone replaying actions by hand.\n"
    "\n"
    "Definition of done (the bar — how we will know it actually works):\n"
    "- It ships as ONE runnable application (backend + shared schema package + React frontend) that "
    "builds, installs its own dependencies, and starts from a clean checkout.\n"
    "- The React FRONTEND is a real deliverable: it builds as part of the single gate (it compiles / "
    "bundles in CI). A repo with no React frontend, or one that does not build, is NOT done.\n"
    "- It carries an automated test suite that PROVES the real-time behaviour: a HEADLESS client "
    "asserts that a move it makes broadcasts to a SECOND connected client, and a RECONNECTING client "
    "rebuilds its state from the log.\n"
    "- The whole app lives at the repository root behind a SINGLE standard build+test gate, so one "
    "command installs dependencies, builds EVERY part (backend + shared package + React frontend "
    "bundle), and runs the tests for the entire app together, and exits green.\n"
    "- That single gate command must run to green HEADLESSLY in a plain CI sandbox from a clean "
    "checkout, installing everything it needs through the ordinary package manager (npm/pnpm). The "
    "HEADLESS bar applies to the automated PROOF-TESTS only (those two tests may drive the real-time "
    "channel directly from two programmatic WebSocket clients — they need no browser). It does NOT "
    "excuse dropping the React frontend: the frontend still ships and still builds in the gate.\n"
    "\n"
    "Choose the framework details, the architecture, the data model, the exact wire protocol, the "
    "build tool, and the file layout yourselves — there is no prescription beyond the three parts, the "
    "outcome, and the bar above. Do NOT run `git push` (there is no remote; the system lands your "
    "work). Build it, run the gate locally until it passes, and commit."
)

# The OBJECTIVE rollup gate pinned on the GOAL itself. With a thin goal we cannot name the files the
# org will invent, so the rollup is the language-agnostic stack gate: the INTEGRATED repo on company
# main must install its deps, build, and pass its tests. The kernel runs this at the lead's integrate
# beat, and the rollup-honesty gate parks the goal BLOCKED (not DONE) unless the whole app is green —
# so "done" can never mean a half-built board.
#
# TAMPER-PROOFING: the gate is a Chorus-owned verifier module, not a file inside the worktree. An
# earlier run showed an engineer rewrite the in-repo gate to deselect the hard e2e tests and still
# print "all gates passed" — gaming the DoD. Pinning the DoD to installed Chorus verifier code closes
# that hole; the gate auto-detects the stack (npm install+build+test for Node, else cargo/go/py) and
# runs with cwd = the worktree.


def _rollup_dod() -> Verifier:
    return Verifier.command(_TEAM_GATE, timeout_s=1200)


async def _run_boardsync(
    org: Chorus, goal_text: str, *, c: _C, rollup_dod: Verifier, deadline_s: float,
    beat_timeout_s: float,
) -> str:
    """A director runs two manager teams with PM + engineering capacity.

    The product goal stays product-shaped, like a real company objective. The org chart itself tells
    the director who reports to them, and each manager's own report list tells them which PM and
    engineers they can use. The role briefs carry the generic PM-first and integration discipline.
    """
    _hr("HIRE — staged org: 1 director, 2 managers, each with 1 PM and 2 engineers", c)
    org.hire(name="vera", role="manager")
    org.hire(name="moe", role="manager", reports_to="vera")
    org.hire(name="max", role="manager", reports_to="vera")

    org.hire(name="pat", role="pm", reports_to="moe")
    org.hire(name="ada", role="engineer", reports_to="moe")
    org.hire(name="bo", role="engineer", reports_to="moe")

    org.hire(name="quinn", role="pm", reports_to="max")
    org.hire(name="cy", role="engineer", reports_to="max")
    org.hire(name="di", role="engineer", reports_to="max")
    _step("hired vera(director) → moe,max(managers) → pat/quinn(pm) · ada,bo,cy,di(engineers)", c)

    _hr("SUBMIT — hand the team the OUTCOME only; the org designs and builds the rest", c)
    goal = org.submit(goal_text, assignee="vera", dod=rollup_dod)
    _step(f"submitted goal {goal.id} → vera   (DoD = objective rollup gate: {_TEAM_GATE})", c)
    print(c("90", f"    goal (thin, outcome-only):\n{_indent(goal_text)}"))

    _hr("HEARTBEAT — org.start(): director delegates to manager teams, each PM-first", c)
    org.start()
    deadline = time.monotonic() + deadline_s
    # The stall watchdog must NEVER fire while the org is still WORKING. A real full-stack build is a
    # MULTI-BEAT task: the engineer's task sits at `in_progress` across many beats (each beat runs up
    # to the per-beat timeout, gets re-dispatched, and continues on the persistent worktree) while it
    # makes real FILE progress the ledger never sees as a status change. The ledger-status signature
    # therefore looks "frozen" for the whole build even though the org is healthily grinding. Two bugs
    # came from a status-only stall signal: iteration 5 (stall=420s < beat=600s killed ada mid-beat)
    # and iteration 7 (status unchanged for 1800s across several timed-out build beats tripped the
    # watchdog and cut the run short at ~3 beats instead of letting ada keep building to the deadline).
    # The fix below: a stall is ONLY when the org is genuinely deadlocked — nothing is running AND
    # nothing changes. While any beat is in flight, the org is progressing; the DEADLINE is the real
    # ceiling for active work. Keep ~2.5 beats of grace for the rare gap between dispatches.
    stall_after_s = max(900.0, beat_timeout_s * 2.5)
    rollup_grace_s = 600.0
    last_sig: tuple[tuple[str, str], ...] = ()
    last_change = time.monotonic()
    rollup_since: float | None = None
    try:
        while time.monotonic() < deadline:
            await asyncio.sleep(5.0)
            g = org.inspect.task(goal.id)
            st = org.status()
            tasks = org._ledger.tasks.all()
            leaves = [t for t in tasks if not org._ledger.tasks.has_children(t.id)]
            leaf_done = sum(1 for t in leaves if t.status.value in _TERMINAL_VALUES)
            print(c("96;1", f"  ↳ goal={g.status.value}  running_beats={st.running_beats}  "
                            f"tasks={len(tasks)}  leaves_terminal={leaf_done}/{len(leaves)}"))
            _print_task_tree(org, goal.id, c)

            if g.status in _TERMINAL:
                break

            area_children = org._ledger.tasks.children(goal.id)
            leaves_landed = (area_children
                             and all(k.status.value in _TERMINAL_VALUES for k in area_children)
                             and leaves and leaf_done == len(leaves))
            if leaves_landed:
                if rollup_since is None:
                    rollup_since = time.monotonic()
                    print(c("94;1", "  ⏳ all subtasks landed on company main — waiting for the lead's "
                                    "integrate beat to run the rollup gate and close the goal…"))
                elif time.monotonic() - rollup_since > rollup_grace_s:
                    print(c("93;1", f"  ◑ the lead kept re-integrating without closing within "
                                    f"{rollup_grace_s:.0f}s; the deliverables ARE on company main "
                                    f"(goal still '{g.status.value}')."))
                    break

            sig = tuple((t.id, t.status.value) for t in tasks)
            if sig != last_sig:
                last_sig = sig
                last_change = time.monotonic()
            elif st.running_beats > 0:
                # A beat is in flight — the org is actively working (a long full-stack build keeps its
                # task at `in_progress` across many beats while making real file progress the ledger
                # can't see). That is NOT a stall; let it run to the deadline. Only a truly deadlocked
                # org (nothing running AND nothing changing) may trip the watchdog below.
                last_change = time.monotonic()
            elif len(tasks) > 1 and time.monotonic() - last_change > stall_after_s:
                print(c("91;1", f"  ✖ no beat running and no task changed for ~{stall_after_s:.0f}s — "
                                f"stopping. goal='{g.status.value}', "
                                f"leaves_terminal={leaf_done}/{len(leaves)}."))
                break
    finally:
        await org.stop()
    return org.inspect.task(goal.id).status.value


def _indent(text: str, pad: str = "      ") -> str:
    return "\n".join(pad + line for line in text.splitlines())


def _final_gate(company_main: Path, gate_command: str, c: _C) -> None:
    """Run the stack-aware gate on company main and report whether the app REALLY builds + tests green.

    This is the honest, end-to-end answer to "does the UI + backend + deps actually work?" — it runs the
    same built-in verifier command the kernel pins as the goal's DoD, but here in plain sight so the
    result is visible even when the run stops early.
    """
    _hr("FINAL GATE — does the integrated app actually build, install deps, and pass its tests?", c)
    if not any(company_main.iterdir()):
        print(c("91", "    company main is empty — nothing was seeded/landed."))
        return
    print(c("90", f"    $ {gate_command}   (cwd={company_main})"))
    proc = subprocess.run(
        gate_command, cwd=str(company_main), shell=True, capture_output=True, text=True,
    )
    for line in (proc.stdout or "").splitlines()[-40:]:
        print(c("90", f"      {line}"))
    for line in (proc.stderr or "").splitlines()[-15:]:
        print(c("91", f"      {line}"))
    if proc.returncode == 0:
        print(c("92;1", "    ✓ FINAL GATE GREEN — the whole app builds, installs deps, and tests pass."))
    else:
        print(c("91;1", f"    ✖ FINAL GATE RED (rc={proc.returncode}) — the app is not yet runnable/green."))


async def _amain(args: argparse.Namespace) -> int:
    c = _C(on=not args.no_color and sys.stdout.isatty())
    _hr("boardsync — ship a real-time collaborative board from a THIN, goal-only brief", c)
    print("  Public API: `from chorus import Chorus`. dream is the agent runtime underneath.")
    print("  The brief is OUTCOME-ONLY — the org designs the tech and builds it. Watch the flow.")

    _load_env()
    if not all(os.environ.get(v) for v in _REQUIRED):
        print(c("93;1", "\n  No model creds found — set these in the repo-root .env, then re-run:"))
        for v in _REQUIRED:
            print(f"    {v}")
        return 0

    base = Path(tempfile.mkdtemp(prefix="chorus-boardsync-"))
    events_log = base / "events.jsonl"
    org, _factory, company_main = _build_company(
        base, c=c, timeout_s=args.timeout, events_log_path=str(events_log)
    )
    org._event_bus.subscribe(Narrator(c).emit)  # live stream (the durable JSONL is wired in parallel)
    _step(f"durable event log → {events_log}", c)

    _step(f"acceptance gate → {_TEAM_GATE} (built into Chorus, run with cwd = repo under test)", c)

    final = await _run_boardsync(
        org, args.task or _THIN_GOAL, c=c, rollup_dod=_rollup_dod(),
        deadline_s=args.deadline, beat_timeout_s=args.timeout,
    )

    _summary(final, company_main, c)
    _final_gate(company_main, _TEAM_GATE, c)

    db_path = base / "company.db"
    print(c("90", f"\n  (workspace: {base})"))
    print(c("97", f"  ledger db    : {db_path}"))
    print(c("97", f"  event log    : {events_log}"))
    return 0


def main() -> int:
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description="Ship a HARD_TASKS app from a thin goal-only brief.")
    parser.add_argument("--task", default=None, help="override the thin goal text")
    parser.add_argument("--no-color", action="store_true", help="plain ASCII output")
    parser.add_argument("--timeout", type=float, default=420.0,
                        help="per-beat wall-clock budget in seconds (default 420)")
    parser.add_argument("--deadline", type=float, default=3000.0,
                        help="overall wall-clock ceiling in seconds (default 3000)")
    return asyncio.run(_amain(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
