"""Stand up a complete repo with chorus — and watch the *entire* flow in your terminal.

This is a tiny, self-contained app that drives a chorus company through the **public facade**
(``from chorus import Chorus`` — the only API you touch) to complete a real task end to end:
an employee plans, edits code on its own git branch, runs the tests until the done-gate passes,
a reviewer signs off, and the work merges onto company main.

The point of this app is **visibility**. It subscribes to chorus's in-process event bus and narrates
every transition as it happens, so you can read the exact flow:

    operator → build → hire → submit → [ tick → wake → beat( plan · tools · evaluate ) → DoD → land ] → done

dream is the agent runtime underneath; chorus is the only thing the app imports. The app never spawns
a subprocess, scrapes stdout, or parses prose — every line below is a *typed event* chorus published.

----------------------------------------------------------------------------------------------------
RUN IT (from the chorus repo root)

    # one-time: install chorus + the sibling dream SDK
    uv pip install -e ../dream -e ".[dev]"

    # put your model creds in the repo-root .env (the app reads it automatically):
    #   AZURE_OPENAI_API_KEY=...
    #   AZURE_OPENAI_BASE_URL=https://<resource>.cognitiveservices.azure.com/...
    #   AZURE_OPENAI_DEPLOYMENT=<deployment>      # e.g. gpt-5.2

    uv run python standup-app/run.py              # solo: one engineer stands up a small package
    uv run python standup-app/run.py --team       # a manager decomposes the goal across two engineers

Flags:  --team   delegate through a manager + 2 engineers (decompose → build → integrate)
        --task "<text>"   override the goal
        --no-color   plain ASCII output
        --pulses N   max heartbeat pulses before giving up (solo mode; default 18)

With no creds set, the app prints what it *would* do and exits cleanly (so you can read the flow first).
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
from dataclasses import replace
from pathlib import Path

# ── chorus is the ONLY API this app imports (dream is wired in under the hood by the harness) ──────
from chorus import Caps, Chorus, TaskStatus, Verifier, default_roles
from chorus.events import Event, EventKind
from chorus.ledger import SqliteLedger
from chorus.roles import RoleRegistry

_REQUIRED = ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_BASE_URL", "AZURE_OPENAI_DEPLOYMENT")
_TERMINAL = frozenset({TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.REJECTED})
_TERMINAL_VALUES = frozenset(s.value for s in _TERMINAL)  # child views carry status as a plain string

# The objective CI gate, pinned as the engineers' Definition of Done in --team mode (see
# ``_objective_engineer_dod``). It is the SAME deterministic floor solo uses.
_TEAM_GATE = "pytest -q && ruff check ."


def _objective_engineer_dod(intent: str) -> Verifier:
    """Engineer DoD = the objective command gate the kernel runs in the worktree (same as solo).

    The engineer role's *default* DoD is a **reviewed build**: the kernel runs the gate AND a read-only
    reviewer must sign off the diff. In practice a weak/over-eager reviewer conflates "judge the diff"
    with "run the gate" — and its read-only sandbox cannot run pytest/ruff — so it returns
    ``needs-changes`` forever. Every decomposed child then loops, the parent goal sits ``blocked``, and
    the run spins out its deadline (the bug this fixes). Pinning ``Verifier.command`` makes a child go
    ``done`` exactly when ``pytest -q && ruff check .`` exits 0 in its own worktree — deterministic and
    self-verifying, with no reviewer in the loop. (Solo already does this explicitly at submit.)
    """
    return Verifier.command(_TEAM_GATE)

# NOTE: pytest + ruff are already installed in the sandbox — the tasks say so explicitly, and tell the
# agent NOT to pip-install or git-push (the kernel's lander handles the PR + merge). Both were the main
# time-wasters that blew the per-beat timeout on the first run; the gate itself (pytest/ruff) is real.
_NO_THRASH = (
    " pytest and ruff are ALREADY installed — do NOT run pip install or ensurepip. Do NOT run git "
    "push (there is no remote; the system handles landing). Just create the files, run the gate "
    "locally, and commit."
)
_SOLO_TASK = (
    "Stand up a small Python package called `greet` in a new directory greet/. Create "
    "greet/__init__.py exposing a function hello(name: str) -> str that returns 'Hello, <name>!', "
    "and greet/cli.py with a main() that prints hello() for a name given on argv (default 'world'). "
    "Add tests in test_greet.py covering hello('Ada') == 'Hello, Ada!' and the default. "
    "The done-gate is `pytest -q && ruff check .` — it must pass." + _NO_THRASH
)
# The two pieces touch DISJOINT files on purpose: each engineer owns a separate module + its own test
# file, so the two branches merge with zero overlap and BOTH deliverables land on company main. (When
# both engineers edited one shared mathx.py/test_mathx.py, the landing collided and the test file was
# dropped from main.) Each child must be SELF-CONTAINED — the SAME engineer writes the module AND its
# test in ONE task — because a test-only child runs in its own worktree and can't see another task's
# module, so an impl/test split deadlocks. We also pin "exactly two children, no separate verify task"
# because the done-gate already IS the verification — an extra verify child is a wasted beat.
_TEAM_GOAL = (
    "Stand up a small Python math package as two INDEPENDENT modules the engineers build in parallel: "
    "(A) subtract.py defining subtract(a, b) returning a - b, with tests in test_subtract.py; "
    "(B) multiply.py defining multiply(a, b) returning a * b, with tests in test_multiply.py. "
    "Decompose into EXACTLY two child tasks — one per engineer — and assign A and B to the two "
    "different engineers. Each child is SELF-CONTAINED: the SAME engineer writes BOTH the module AND "
    "its test file in that one task. NEVER split a module's implementation and its tests into separate "
    "tasks — a test-only task runs in its own worktree, cannot see the other task's module, and will "
    "deadlock. Each engineer creates ONLY their own two files (no shared files, so the two branches "
    "never collide). Do NOT create a separate verification or integration child task: the done-gate "
    "`pytest -q && ruff check .` run in each engineer's own task IS the check." + _NO_THRASH
)
# --org mode: a THREE-level org (director → two team leads → engineers). The director splits the goal
# into two AREAS and delegates each to a *team lead* (a manager report, NOT an engineer); each team
# lead then splits ITS area into two engineer tasks. This exercises multi-level delegation: decompose
# at two depths, a subtree integrate at each manager level (the worktree-sync fix lands here twice),
# and the full role set (manager · engineer · reviewer · pm · analyst) on one org chart. The four leaf
# modules touch DISJOINT files so all four branches merge onto company main with zero overlap.
_ORG_GOAL = (
    "Stand up a small Python utility library as TWO INDEPENDENT areas, built by two separate teams in "
    "parallel. Decompose into EXACTLY two child tasks — one per AREA — and assign each AREA to a "
    "different TEAM LEAD (a manager report, identified by id in the list below); do NOT assign an area "
    "to an engineer, and do NOT create the modules yourself. Write each area child's `intent` as a "
    "precise, self-contained brief the team lead can split into exactly two engineer tasks:\n"
    "- AREA A — text utilities: (1) slugify.py defining slugify(text: str) -> str that lowercases, "
    "replaces every run of non-alphanumeric characters with a single '-', and strips leading/trailing "
    "'-', with tests in test_slugify.py asserting slugify('Hello, World!') == 'hello-world'; and "
    "(2) titlecase.py defining titlecase(text: str) -> str that capitalizes the first letter of each "
    "whitespace-separated word, with tests in test_titlecase.py asserting "
    "titlecase('hello world') == 'Hello World'.\n"
    "- AREA B — number utilities: (1) gcd.py defining gcd(a: int, b: int) -> int using Euclid's "
    "algorithm, with tests in test_gcd.py asserting gcd(12, 18) == 6; and (2) is_prime.py defining "
    "is_prime(n: int) -> bool, with tests in test_is_prime.py asserting is_prime(7) is True and "
    "is_prime(9) is False.\n"
    "Each team lead splits its area into EXACTLY two engineer tasks — one module + its test file per "
    "engineer, assigned to a DIFFERENT engineer. Every leaf task is SELF-CONTAINED: the SAME engineer "
    "writes BOTH the module AND its test in that one task. NEVER split a module's implementation and "
    "its tests into separate tasks. Each engineer creates ONLY their own two files (every module lives "
    "in its own files, so no two branches ever collide). Do NOT create separate verification or "
    "integration child tasks: the done-gate `pytest -q && ruff check .` run in each engineer's own "
    "task IS the check." + _NO_THRASH
)


# ── output helpers ────────────────────────────────────────────────────────────────────────────────

class _C:
    """ANSI palette (disabled with --no-color or when stdout is not a TTY)."""

    def __init__(self, on: bool) -> None:
        self.on = on

    def __call__(self, code: str, text: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self.on else text


def _hr(title: str, c: _C) -> None:
    print("\n" + c("96", "═" * 90))
    print(c("96;1", f"  {title}"))
    print(c("96", "═" * 90), flush=True)


def _step(msg: str, c: _C) -> None:
    print(c("92;1", f"▶ {msg}"), flush=True)


# ── the narrator: turn chorus's typed event stream into readable English ───────────────────────────

class Narrator:
    """Subscribes to chorus's in-process event bus and prints every transition as it happens.

    chorus publishes a single typed ``Event`` for each transition; ``kind`` discriminates and the
    details live in ``payload`` + resolved refs. The ``run.*`` kinds come verbatim from dream's engine
    stream — this is chorus *witnessing* the agent loop, not parsing its prose.
    """

    def __init__(self, c: _C) -> None:
        self._c = c
        self._prose = ""  # RUN_TEXT arrives token-by-token; we buffer to whole lines

    # the human label + a short detail for each event kind
    def emit(self, event: Event) -> None:  # signature chorus's EventBus calls
        c = self._c
        p = event.payload
        k = event.kind

        # streamed model reasoning — buffer tokens, print whole lines
        if k is EventKind.RUN_TEXT:
            self._prose += str(p.get("text", ""))
            while "\n" in self._prose:
                head, self._prose = self._prose.split("\n", 1)
                if head.strip():
                    print(c("90", f"        · {head.strip()[:160]}"), flush=True)
            return
        self._flush_prose()

        who = self._who(event)
        if k is EventKind.WAKE_ENQUEUED:
            print(c("94", f"    ⤲ wake queued        why={p.get('reason', p.get('kind', '?'))}  {who}"))
        elif k is EventKind.WAKE_COALESCED:
            print(c("90", f"    ⤲ wake coalesced     (folded into an existing wake)  {who}"))
        elif k is EventKind.WAKE_CLAIMED:
            print(c("94;1", f"    ⚡ beat dispatched    {who}"))
        elif k is EventKind.RUN_QUEUED:
            print(c("90", "        ▸ run queued"))
        elif k is EventKind.RUN_STARTED:
            print(c("95;1", "        ▸ BEAT STARTED — the agent loop begins (plan → act → evaluate)"))
        elif k is EventKind.RUN_TURN:
            print(c("90", f"        ▸ turn {p.get('index', p.get('turn', '?'))}"))
        elif k is EventKind.RUN_TOOL_USE:
            print(c("93", f"        → TOOL {p.get('tool', '?')}  {str(p.get('input', ''))[:120]}"))
        elif k is EventKind.RUN_TOOL_RESULT:
            err = p.get("is_error")
            tag = c("91", "ERR") if err else c("92", "ok")
            note = f"  {str(p.get('content', ''))[:120]}" if err else ""
            print(f"        ← {p.get('tool', '?')} [{tag}]{note}")
        elif k is EventKind.RUN_EVALUATED:
            print(c("96;1", f"        ⊢ EVALUATED  {str(p.get('outcome', p))[:140]}"))
        elif k is EventKind.RUN_DONE:
            print(c("95", "        ▪ beat done"))
        elif k is EventKind.TASK_CREATED:
            print(c("97", f"    + task created       {self._task(event)}"))
        elif k is EventKind.TASK_ASSIGNED:
            print(c("97", f"    → task assigned      {self._task(event)} {who}"))
        elif k is EventKind.TASK_STATUS:
            frm, to = p.get("from", p.get("old", "?")), p.get("to", p.get("status", p.get("new", "?")))
            print(c("97;1", f"    ◆ task {frm} → {to}   {self._task(event)}"))
        elif k is EventKind.TASK_CHILDREN_DONE:
            print(c("92;1", f"    ✓ all children done  {self._task(event)} — manager can integrate"))
        elif k is EventKind.TASK_DEPENDENCY_RESOLVED:
            print(c("97", f"    ↟ dependency cleared {self._task(event)}"))
        elif k is EventKind.RECOVERY_OPENED:
            print(c("91;1", f"    ! recovery opened    {p.get('reason', '?')}  {self._task(event)}"))
        elif k is EventKind.RECOVERY_RESOLVED:
            print(c("92", f"    ✓ recovery resolved  {self._task(event)}"))
        elif k is EventKind.RECOVERY_ESCALATED:
            print(c("91", f"    ↑ recovery escalated {self._task(event)}"))
        elif k is EventKind.MONITOR_DUE:
            print(c("94", f"    ⏰ monitor due        {self._task(event)}"))
        elif k is EventKind.ROUTINE_FIRED:
            print(c("94", f"    ⟳ routine fired      {p.get('routine', p)}"))
        elif k is EventKind.BUDGET_SOFT_THRESHOLD:
            print(c("93;1", f"    $ budget soft warn   {p}"))
        elif k is EventKind.BUDGET_HARD_STOP:
            print(c("91;1", f"    $ BUDGET HARD STOP   {p} — scope paused"))
        elif k is EventKind.BUDGET_RESUMED:
            print(c("92", f"    $ budget resumed     {p}"))
        elif k is EventKind.EMPLOYEE_HIRED:
            print(c("97", f"    ☺ employee hired     {who}"))
        elif k is EventKind.APPROVAL_DECIDED:
            print(c("97", f"    ⚖ approval decided   {p}"))
        else:
            print(c("90", f"    · {k.value}  {dict(p)}"))

    def _flush_prose(self) -> None:
        line = self._prose.strip()
        self._prose = ""
        if line:
            print(self._c("90", f"        · {line[:160]}"), flush=True)

    @staticmethod
    def _who(event: Event) -> str:
        return f"[{event.employee_id}]" if event.employee_id else ""

    @staticmethod
    def _task(event: Event) -> str:
        return f"({event.task_id})" if event.task_id else ""


# ── credentials + workspace ────────────────────────────────────────────────────────────────────────

def _load_env() -> None:
    """Fold the repo-root ``.env`` (or ``CHORUS_ENV_FILE``) into the environment."""
    path = Path(os.environ.get("CHORUS_ENV_FILE", ".env"))
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=False, capture_output=True, text=True
    ).stdout.rstrip()


def _last_run_outcome(org: Chorus, task_id: str) -> dict[str, object]:
    """The latest beat's raw outcome dict — for an errored beat this carries the phase + error."""
    runs = org._ledger.runs.for_task(task_id)  # demo: read the kernel's own store directly
    return dict(runs[-1].outcome) if runs else {}


def _seed_repo(path: Path) -> Path:
    """A throwaway git repo the employees branch their worktrees from.

    Seeded with a README and one passing smoke test so the `pytest` done-gate has a green baseline
    before the employee adds its own code + tests.
    """
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text("# company repo\n", encoding="utf-8")
    (path / "test_smoke.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.name=seed", "-c", "user.email=seed@x",
         "commit", "-m", "seed"],
        check=True, capture_output=True,
    )
    return path


def _build_company(base: Path, *, c: _C, timeout_s: float) -> tuple[Chorus, object, Path]:
    """Wire the public facade over the harness factory — the supported `Chorus.build` path.

    The factory owns dream + the model creds + per-employee git worktrees; ``Chorus.build`` plugs in
    its two seams (``beat_runner_for`` = how a beat runs, ``landers`` = how its work lands) over the
    *same* ledger, so the kernel and the execution layer share one source of truth.
    """
    import dream  # the agent runtime — imported only by this wiring, exactly as the facade docstring says

    from chorus_cli._beats import default_pricing_from_env
    from chorus_harness import EmployeeHarnessFactory

    seed = _seed_repo(base / "source")
    ledger = SqliteLedger.open(str(base / "company.db"))
    # Pin the engineer's DoD to the objective gate so a decomposed --team child goes DONE when the
    # kernel runs `pytest -q && ruff check .` (no read-only reviewer in the loop). Solo overrides the
    # DoD per-submit anyway, so this is a no-op for solo and the deterministic floor for the team.
    plugins = tuple(
        replace(p, dod_generator=_objective_engineer_dod) if p.name == "engineer" else p
        for p in default_roles()
    )
    factory = EmployeeHarnessFactory(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        base_url=os.environ["AZURE_OPENAI_BASE_URL"],
        deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        company_id="acme",
        roles=RoleRegistry.from_plugins(plugins),
        pricing=default_pricing_from_env(),
        seed=seed,
        work_root=base / "work",
        ledger=ledger,
        timeout_s=timeout_s,   # per-beat wall-clock budget; the 90s default is too tight from scratch
    )
    org = Chorus.build(
        ledger=ledger,
        org_repo=str(base / "org"),
        memory_repo=str(base / "memory"),
        dream=dream,
        beat_runner_for=factory,   # how a beat runs (+ a reviewer reads the author's worktree)
        landers=factory.landers,   # how the deliverable lands on company main
        caps=Caps(tick_interval_s=0.5),
        company_id="acme",
        roles=plugins,             # the kernel intake-DoD registry: engineer pinned to the objective gate
    )
    _step(f"built company  (deployment={os.environ['AZURE_OPENAI_DEPLOYMENT']}, "
          f"per-beat timeout={timeout_s:.0f}s)", c)
    return org, factory, factory.company_root / "repo"


# ── the two flows ───────────────────────────────────────────────────────────────────────────────────

async def _run_solo(org: Chorus, task_text: str, *, max_pulses: int, c: _C) -> str:
    """One engineer, single-stepped. Deterministic: each tick+drain runs the next step to completion."""
    _hr("HIRE — the org is just data (rows), not processes", c)
    org.hire(name="moe", role="manager")
    _step("hired moe (manager)", c)
    org.hire(name="eng1", role="engineer", reports_to="moe")
    _step("hired eng1 (engineer) → reports to moe", c)

    _hr("SUBMIT — hand the engineer a task in plain English", c)
    # We pin the Definition of Done explicitly: the objective CI gate `pytest -q && ruff check .`.
    # That is the same deterministic floor the engineer's role would run — the kernel executes it as a
    # real subprocess and the task only goes DONE when it exits 0. (Giving no DoD would instead pull
    # the role's *reviewed* build, which also needs a second LLM to sign off; the objective gate keeps
    # the demo deterministic and self-verifying.)
    gate = Verifier.command("pytest -q && ruff check .")
    task = org.submit(task_text, assignee="eng1", dod=gate)
    _step(f"submitted {task.id} → eng1   (DoD = objective gate: pytest -q && ruff check .)", c)
    print(c("90", f"    intent: {task_text}"))

    _hr("HEARTBEAT — each pulse: recover · cron · monitors · dispatch (watch the live stream)", c)
    failures = 0
    for n in range(1, max_pulses + 1):
        print(c("96", f"\n— pulse {n} —"))
        await org.tick()    # dispatch any ready beats (emits wake/run/task events to the narrator)
        await org.drain()   # block until this pulse's beats settle
        view = org.inspect.task(task.id)
        beat = view.latest_run.status if view.latest_run is not None else "-"
        print(c("96;1", f"  ↳ pulse {n} settled: task={view.status.value}  last_beat={beat}"))
        if view.status in _TERMINAL:
            break
        # When a beat errors, the *reason* lives in the run's outcome — surface it so the flow is honest.
        outcome = _last_run_outcome(org, task.id)
        if str(beat) == "failed" and outcome:
            print(c("91", f"    ✖ beat failed: {str(outcome)[:400]}"))
            failures += 1
            if failures >= 2:
                print(c("91;1", "    x same failure twice — stopping (this is an infra/model error, "
                                "not a code-repair loop). See the outcome above."))
                break
        else:
            failures = 0
    return org.inspect.task(task.id).status.value


async def _run_team(org: Chorus, goal_text: str, *, c: _C) -> str:
    """A manager decomposes the goal across two engineers, driven by the always-on heartbeat."""
    _hr("HIRE — a manager, two engineers, a reviewer", c)
    org.hire(name="moe", role="manager")
    org.hire(name="ada", role="engineer", reports_to="moe")
    org.hire(name="bo", role="engineer", reports_to="moe")
    org.hire(name="ria", role="reviewer", reports_to="moe")
    _step("hired moe(manager) · ada(engineer) · bo(engineer) · ria(reviewer)", c)

    _hr("SUBMIT — state a goal; the manager decomposes it", c)
    goal = org.submit(goal_text, assignee="moe")
    _step(f"submitted goal {goal.id} → moe", c)
    print(c("90", f"    goal: {goal_text}"))

    _hr("HEARTBEAT — org.start(): the concurrent always-on runner (employees work in the background)", c)
    org.start()
    # Bound the run: the deadline is a hard ceiling, but we exit as soon as the goal settles OR every
    # decomposed child has landed. A stall guard breaks out if no child changes status for a long
    # stretch (the classic symptom of a gate that can never be satisfied) instead of spinning silently.
    deadline = time.monotonic() + 600.0
    stall_after_s = 200.0
    rollup_grace_s = 300.0                  # let the manager integrate (incl. the kernel cap) close it
    last_child_sig: tuple[tuple[str, str], ...] = ()
    last_change = time.monotonic()
    rollup_since: float | None = None
    try:
        while time.monotonic() < deadline:
            await asyncio.sleep(4.0)
            g = org.inspect.task(goal.id)
            st = org.status()
            packet = org.inspect.scrum_packet(goal.id)
            kids = packet.children
            done = sum(1 for k in kids if k.status == TaskStatus.DONE.value)
            print(c("96;1", f"  ↳ goal={g.status.value}  running_beats={st.running_beats}  "
                            f"children={done}/{len(kids)} done"))
            if kids:
                print(c("90", "      " + "  ".join(
                    f"{(k.label or k.task_id[-4:])}={k.status}" for k in kids)))

            # Exit 1 — the goal task itself reached a terminal state (the manager's rollup signed off).
            if g.status in _TERMINAL:
                break
            # Once every child has landed, the only work left is the manager's integrate beat: its
            # `children_done` wake is enqueued the instant the last child finishes. KEEP the heartbeat
            # ticking so that wake gets claimed and the manager closes the goal — bounded by a grace
            # window so a genuinely stuck rollup can't hang the demo.
            if kids and all(k.status in _TERMINAL_VALUES for k in kids) and done == len(kids):
                if rollup_since is None:
                    rollup_since = time.monotonic()
                    print(c("94;1", "  ⏳ all child tasks landed on company main — waiting for the "
                                    "manager's integrate beat to close the goal…"))
                elif time.monotonic() - rollup_since > rollup_grace_s:
                    print(c("93;1", f"  ◑ the manager kept re-integrating without closing the goal "
                                    f"within {rollup_grace_s:.0f}s (the kernel integrate cap closes it "
                                    f"eventually); the deliverables ARE on company main "
                                    f"(goal still '{g.status.value}')."))
                    break

            # Stall guard — only meaningful once the goal is decomposed. A child status change resets it.
            child_sig = tuple((k.task_id, k.status) for k in kids)
            if child_sig != last_child_sig:
                last_child_sig = child_sig
                last_change = time.monotonic()
            elif kids and time.monotonic() - last_change > stall_after_s:
                print(c("91;1", f"  ✖ no child made progress for ~{stall_after_s:.0f}s — stopping. The "
                                f"goal is '{g.status.value}' with {done}/{len(kids)} children done; a "
                                f"done-gate is stuck (see the verdict lines above)."))
                break
    finally:
        await org.stop()  # signal the loop, then drain in-flight beats
    return org.inspect.task(goal.id).status.value


def _print_task_tree(org: Chorus, root_id: str, c: _C) -> None:
    """Render the live decomposition tree under ``root_id``, depth-indented (director → leads → eng)."""
    ledger = org._ledger  # demo: read the kernel's own store directly to walk parent→child

    def walk(task_id: str, indent: int) -> None:
        view = org.inspect.task(task_id)
        role = ""
        if view.assignee:
            emp = ledger.employees.get(view.assignee)
            role = f" {emp.role}" if emp is not None else ""
        beat = view.latest_run.status if view.latest_run is not None else "-"
        pad = "    " + "  " * indent
        label = (view.intent or "").strip().splitlines()[0][:54]
        print(c("90", f"{pad}{('└─ ' if indent else '◆ ')}{view.status.value:<11} "
                      f"[{view.assignee or '-'}{role}] beat={beat}  {label}"))
        for child in ledger.tasks.children(task_id):
            walk(child.id, indent + 1)

    walk(root_id, 0)


async def _run_org(org: Chorus, goal_text: str, *, c: _C) -> str:
    """A 3-level org: a director delegates two areas to two team leads, who each delegate to engineers.

    Same always-on heartbeat as ``--team``, but with two manager tiers so the subtree integrate (and
    the worktree-sync fix) runs at both levels. We poll the WHOLE tree, not just the goal's direct
    children, and exit when the goal settles or both area subtrees have landed.
    """
    _hr("HIRE — a 3-level org: director · 2 team leads · engineers + reviewer + pm + analyst", c)
    org.hire(name="vera", role="manager")                       # L1 — the director
    org.hire(name="moe", role="manager", reports_to="vera")     # L2 — text team lead
    org.hire(name="max", role="manager", reports_to="vera")     # L2 — math team lead
    # L3 — moe's text team
    org.hire(name="ada", role="engineer", reports_to="moe")
    org.hire(name="bo", role="engineer", reports_to="moe")
    org.hire(name="ria", role="reviewer", reports_to="moe")
    org.hire(name="pat", role="pm", reports_to="moe")
    # L3 — max's math team
    org.hire(name="cy", role="engineer", reports_to="max")
    org.hire(name="di", role="engineer", reports_to="max")
    org.hire(name="rex", role="reviewer", reports_to="max")
    org.hire(name="ana", role="analyst", reports_to="max")
    _step("hired vera(director) → moe,max(team leads) → ada,bo,cy,di(eng) · ria,rex(rev) · "
          "pat(pm) · ana(analyst)", c)

    _hr("SUBMIT — state the goal; the director decomposes across the two team leads", c)
    goal = org.submit(goal_text, assignee="vera")
    _step(f"submitted goal {goal.id} → vera", c)
    print(c("90", f"    goal: {goal_text[:160]}…"))

    _hr("HEARTBEAT — org.start(): two manager tiers integrate their subtrees as work lands", c)
    org.start()
    deadline = time.monotonic() + 1200.0   # a 3-level run needs more beats than --team
    stall_after_s = 300.0
    # After every leaf lands, keep ticking long enough for the director's integrate cascade to close
    # the goal. A well-behaved director accepts in one beat; a director that keeps re-decomposing is
    # still bounded — the kernel's integrate-iteration cap (max_integrate_iterations) mechanically
    # accepts the completed subtree after a few rounds. This window covers those extra rounds.
    rollup_grace_s = 600.0
    last_sig: tuple[tuple[str, str], ...] = ()
    last_change = time.monotonic()
    rollup_since: float | None = None
    try:
        while time.monotonic() < deadline:
            await asyncio.sleep(5.0)
            g = org.inspect.task(goal.id)
            st = org.status()
            # All non-terminal tasks in the whole tree, for a progress signature + a leaf rollup.
            tasks = org._ledger.tasks.all()
            leaves = [t for t in tasks if not org._ledger.tasks.has_children(t.id)]
            leaf_done = sum(1 for t in leaves if t.status.value in _TERMINAL_VALUES)
            print(c("96;1", f"  ↳ goal={g.status.value}  running_beats={st.running_beats}  "
                            f"tasks={len(tasks)}  leaves_terminal={leaf_done}/{len(leaves)}"))
            _print_task_tree(org, goal.id, c)

            # Exit 1 — the director's goal reached a terminal state (top subtree-review signed off).
            if g.status in _TERMINAL:
                break
            # Once every leaf has landed, the only work left is the manager integrate cascade rolling
            # UP the tree: engineers done → team leads' `children_done` wake fires → leads integrate →
            # leads done → the DIRECTOR's `children_done` wake is enqueued → director integrates → goal
            # done. That last wake is enqueued the instant the leads finish, so we KEEP the heartbeat
            # ticking and wait for the goal itself to close — bounding the wait with a grace window so a
            # genuinely stuck top-level rollup can't hang the demo.
            area_children = org._ledger.tasks.children(goal.id)
            leaves_landed = (area_children
                             and all(k.status.value in _TERMINAL_VALUES for k in area_children)
                             and leaves and leaf_done == len(leaves))
            if leaves_landed:
                if rollup_since is None:
                    rollup_since = time.monotonic()
                    print(c("94;1", "  ⏳ both area subtrees landed — all four modules are on company "
                                    "main; waiting for the director's integrate beat to close the goal…"))
                elif time.monotonic() - rollup_since > rollup_grace_s:
                    print(c("93;1", f"  ◑ the director kept re-integrating without closing the goal "
                                    f"within {rollup_grace_s:.0f}s (the kernel integrate cap closes it "
                                    f"eventually); every module IS on company main "
                                    f"(goal still '{g.status.value}')."))
                    break

            # Stall guard — a status change anywhere in the tree resets it.
            sig = tuple((t.id, t.status.value) for t in tasks)
            if sig != last_sig:
                last_sig = sig
                last_change = time.monotonic()
            elif len(tasks) > 1 and time.monotonic() - last_change > stall_after_s:
                print(c("91;1", f"  ✖ no task changed for ~{stall_after_s:.0f}s — stopping. goal="
                                f"'{g.status.value}', leaves_terminal={leaf_done}/{len(leaves)}."))
                break
    finally:
        await org.stop()
    return org.inspect.task(goal.id).status.value


# ── entrypoint ────────────────────────────────────────────────────────────────────────────────────

def _summary(final: str, company_main: Path, c: _C) -> None:
    _hr("RESULT — the complete repo that was stood up", c)
    print(c("97;1", f"  final task status : {final}"))
    print(c("97", "  company main — git log:"))
    print(_git(company_main, "log", "--oneline", "-8") or "    (nothing landed)")
    print(c("97", "\n  company main — tracked files (the repo that now exists):"))
    files = _git(company_main, "ls-files")
    print("\n".join(f"    {f}" for f in files.splitlines()) or "    (empty)")


async def _amain(args: argparse.Namespace) -> int:
    c = _C(on=not args.no_color and sys.stdout.isatty())
    _hr("chorus standup app — build → hire → submit → heartbeat → done", c)
    print("  Public API: `from chorus import Chorus`. dream is the agent runtime underneath.")
    print("  Every indented line below is a typed event chorus published — the real flow.")

    _load_env()
    if not all(os.environ.get(v) for v in _REQUIRED):
        print(c("93;1", "\n  No model creds found — printing the flow without running it.\n"))
        print("  Set these in the repo-root .env, then re-run:")
        for v in _REQUIRED:
            print(f"    {v}")
        print("\n  What WOULD happen:")
        print("    1. build a company (one shared ledger; the harness wires dream + creds)")
        print("    2. hire a manager + engineer(s) + reviewer (rows in the ledger)")
        print("    3. submit a task/goal in plain English")
        print("    4. the heartbeat ticks → wakes → dispatches a beat → the agent plans, edits")
        print("       code on its own git branch, runs the tests, a reviewer signs off")
        print("    5. the DoD goes green → the PR merges to company main → the task is DONE")
        return 0

    base = Path(tempfile.mkdtemp(prefix="chorus-standup-"))
    org, _factory, company_main = _build_company(base, c=c, timeout_s=args.timeout)
    org._event_bus.subscribe(Narrator(c).emit)  # the live in-process stream this app exists to show

    if args.org:
        final = await _run_org(org, args.task or _ORG_GOAL, c=c)
    elif args.team:
        final = await _run_team(org, args.task or _TEAM_GOAL, c=c)
    else:
        final = await _run_solo(org, args.task or _SOLO_TASK, max_pulses=args.pulses, c=c)

    _summary(final, company_main, c)
    db_path = base / "company.db"
    print(c("90", f"\n  (workspace: {base})"))
    print(c("97", f"  ledger db   : {db_path}"))

    # The report generator reads the same ledger and draws the org chart + decomposition tree.
    if args.report or args.org:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))  # make the sibling importable
            from report import write_report  # type: ignore[import-not-found]  # sibling in standup-app/

            out = base / "report.md"
            write_report(str(db_path), out_path=str(out))
            print(c("92;1", f"  decomposition report written → {out}"))
            print(c("90", f"  (regenerate any time: python standup-app/report.py --db {db_path})"))
        except Exception as exc:  # a report failure must never sink the run
            print(c("91", f"  report generation failed: {type(exc).__name__}: {exc}"))
    else:
        print(c("90", f"  report      : python standup-app/report.py --db {db_path}"))
    return 0


def main() -> int:
    # Force UTF-8 stdout so the box-drawing / arrow glyphs survive a redirect or pipe on Windows
    # (a raw console is already fine; cp1252 is only selected when stdout is not a TTY).
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description="Stand up a repo with chorus and watch the flow.")
    parser.add_argument("--team", action="store_true", help="manager decomposes across 2 engineers")
    parser.add_argument("--org", action="store_true",
                        help="3-level org: director → 2 team leads → engineers (+reviewer/pm/analyst)")
    parser.add_argument("--report", action="store_true",
                        help="write a decomposition report (org chart + task tree) at the end")
    parser.add_argument("--task", default=None, help="override the task / goal text")
    parser.add_argument("--no-color", action="store_true", help="plain ASCII output")
    parser.add_argument("--pulses", type=int, default=18, help="max heartbeat pulses (solo mode)")
    parser.add_argument("--timeout", type=float, default=240.0,
                        help="per-beat wall-clock budget in seconds (default 240; harness default is 90)")
    return asyncio.run(_amain(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
