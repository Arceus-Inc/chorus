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
import re
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
from chorus.lifecycle import seed_agents_md
from chorus.roles import RolePlugin, RoleRegistry, SandboxTier

_REQUIRED = ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_BASE_URL", "AZURE_OPENAI_DEPLOYMENT")
_TERMINAL = frozenset({TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.REJECTED})
_TERMINAL_VALUES = frozenset(s.value for s in _TERMINAL)  # child views carry status as a plain string

# The objective CI gate, pinned as the engineers' Definition of Done in --team mode (see
# ``_objective_engineer_dod``). It is the SAME deterministic floor solo uses.
#
# It is NOT hardcoded to Python: the gate runs ``gate_check.py`` (seeded into every worktree by
# ``_seed_repo``), which detects the deliverable's stack from its marker files (package.json,
# Cargo.toml, go.mod, pyproject/*.py) and runs the matching tests + lint. A hardcoded
# ``pytest -q && ruff check .`` was a real bug: the seed ships a Python ``test_smoke.py``, so pytest
# was always vacuously green and a TypeScript/Rust/Go deliverable was never actually verified.
# ``python gate_check.py`` is portable across cmd.exe and /bin/sh (both resolve ``python`` on PATH).
_TEAM_GATE = "python gate_check.py"


def _objective_engineer_dod(intent: str) -> Verifier:
    """Engineer DoD = the objective command gate the kernel runs in the worktree (same as solo).

    The engineer role's *default* DoD is a **reviewed build**: the kernel runs the gate AND a read-only
    reviewer must sign off the diff. In practice a weak/over-eager reviewer conflates "judge the diff"
    with "run the gate" — and its read-only sandbox cannot run the tests — so it returns
    ``needs-changes`` forever. Every decomposed child then loops, the parent goal sits ``blocked``, and
    the run spins out its deadline (the bug this fixes). Pinning ``Verifier.command`` makes a child go
    ``done`` exactly when the stack-aware gate exits 0 in its own worktree — deterministic and
    self-verifying, with no reviewer in the loop. (Solo already does this explicitly at submit.)

    The gate is the stack-aware ``gate_check.py`` (NOT a Python-only ``pytest``), so a Node/TypeScript,
    Rust, or Go deliverable is verified by its own toolchain — the engineer's DoD is not restricted to
    one language.
    """
    return Verifier.command(_TEAM_GATE)


# A PM's deliverable is a written plan/spec, verified by ``plan_check.py`` (seeded into every worktree):
# the named plan file exists and is non-empty. The filename is taken from the task's own intent (the
# manager names a per-area plan file like ``plan-presence.md`` so two parallel PMs never write the same
# path and collide on merge); it defaults to ``plan.md`` when the intent names none.
_PLAN_FILE_RE = re.compile(r"plan[-\w]*\.md")


def _objective_pm_dod(intent: str) -> Verifier:
    """PM DoD = the objective command gate the kernel runs in the worktree (the spec file is present).

    The PM role's *default* DoD is an agent review, which needs a Reviewer in the loop; this org hires
    none, so a PM task would otherwise never reach ``done``. Pinning ``Verifier.command`` makes a PM go
    ``done`` exactly when its plan file exists and is non-empty in its own worktree — deterministic and
    self-verifying, the same objective-floor pattern the engineers use. The gate checks the SPECIFIC
    plan file the area's intent names, so each area's PM is verified against its own spec.
    """
    match = _PLAN_FILE_RE.search(intent)
    plan_file = match.group(0) if match is not None else "plan.md"
    return Verifier.command(f"python plan_check.py {plan_file}", artifact_class="spec")


def _pin_objective_dod(plugin: RolePlugin) -> RolePlugin:
    """Override the engineer + PM DoDs with their objective command gates (no reviewer in the loop).

    Engineer → ``python gate_check.py`` (stack-aware tests + lint). PM → ``python plan_check.py <file>``
    (the named plan file is present + non-empty), plus the UNRESTRICTED sandbox + run_command the
    engineer uses so the kernel's in-beat gate runs. Every other role passes through unchanged.
    """
    if plugin.name == "engineer":
        return replace(plugin, dod_generator=_objective_engineer_dod)
    if plugin.name == "pm":
        pm_manifest = replace(
            plugin.manifest,
            sandbox=SandboxTier.UNRESTRICTED,
            tools=tuple(dict.fromkeys((*plugin.manifest.tools, "run_command"))),
        )
        return replace(plugin, dod_generator=_objective_pm_dod, manifest=pm_manifest)
    return plugin

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
# HARD_TASKS.md #15 (presence chatroom) driven through the SAME org guardrails as _ORG_GOAL. The four
# leaf modules are FLAT, top-level, and mutually INDEPENDENT (no cross-imports, no shared package
# __init__.py) so all four engineer branches merge onto company main with zero overlap — this is what
# kept an earlier ad-hoc run from landing (engineers each rewrote chatroom/__init__.py → merge
# collisions) and from deadlocking (managers split each module from its tests into separate worktrees).
_CHATROOM_GOAL = (
    "Build a deterministic, pure-Python presence chatroom WITH A RUNNABLE WEB UI, as THREE areas "
    "built by THREE separate teams. Decompose into EXACTLY three child tasks — one WHOLE area per team "
    "lead (a manager report, identified by id in the list below) — and assign each area to a DIFFERENT "
    "team lead. Your three children are: child 1 = AREA A (BOTH its modules rooms.py + messages.py + "
    "their tests test_rooms.py/test_messages.py), child 2 = AREA B (BOTH its modules presence.py + "
    "typing.py + their tests test_presence.py/test_typing.py), and child 3 = AREA C (the single "
    "integration module app.py + test_app.py). NEVER make more or fewer than three children, NEVER "
    "assign two areas to the same lead, and NEVER drop an area. Your first decompose MUST already "
    "cover all three areas. EVERY one of your three children is structurally IDENTICAL: a WHOLE area "
    "handed to ONE team lead, whose OWN team writes that area's team spec file FIRST (with its own PM) "
    "and THEN builds that area's module(s). Treat all three areas the SAME way — there is NO separate, "
    "shared, or up-front 'spec' phase and NO global plan task; each area's spec is written INSIDE that "
    "area's team by that team's lead, NEVER by you.\n"
    "ANTI-PATTERNS — these are the most common and costly mistakes; do NOT do any of them: (1) Do NOT "
    "create a 'write the plan' or 'write the spec' child task, and do NOT make ONE manager write a plan "
    "while OTHER managers build from it — that drops whole areas. Each PM-first planning step is "
    "INTERNAL to a single team and is run by THAT team's own lead, NEVER by you. (2) Do NOT scope an "
    "AREA A or AREA B child to a SINGLE backend module (e.g. a 'rooms' child and a separate 'messages' "
    "child) — each of those two areas spans TWO modules inside ONE child. (3) Do NOT create any PM, "
    "spec, planning, build, verification, or integration child yourself, and do NOT decompose an area "
    "into per-module children — each team lead runs its OWN decomposition from the brief you hand it. "
    "If any AREA A/B child names fewer than its two modules, or if ANY child is a plan/spec-only task, "
    "you have FAILED: STOP and re-form the three children so child 1 = AREA A (rooms.py + messages.py + "
    "tests), child 2 = AREA B (presence.py + typing.py + tests), child 3 = AREA C (app.py + "
    "test_app.py). The five module files rooms.py, messages.py, presence.py, typing.py, AND app.py "
    "MUST all be accounted for across exactly three area children before you finish decomposing. "
    "(CLARIFICATION for reviewers/integrators: using PEP 585 builtin "
    "generic annotations like dict[str, str], list[int], set[str], and an optional `from __future__ "
    "import annotations`, is ALLOWED and is NOT a violation — those are builtin syntax and do NOT "
    "import the standard-library `typing` module, and have NOTHING to do with the sibling app module "
    "`typing.py`. The 'no cross-imports' rule below ONLY forbids the four BACKEND modules importing "
    "each other; it does NOT forbid stdlib/builtin generics, and does NOT forbid app.py importing the "
    "backends lazily. NEVER reject an already-delivered, gate-passing module on the grounds that it "
    "'imports typing'.):\n"
    "- AREA A — messaging & history (team spec file `plan-messaging.md`; modules rooms.py + "
    "messages.py): (1) rooms.py defining Room (join(user)/leave(user) membership plus its OWN "
    "internal per-room message list via add_message/messages) and RoomRegistry (get(name) "
    "create-on-demand), with tests in test_rooms.py asserting join adds a member, leave removes a "
    "member, and messages are stored per-room and do not bleed across rooms; and (2) messages.py "
    "defining a MessageStore with add(room_id, text) that assigns deterministic monotonic ids per "
    "room and history(room_id, limit=None, before_id=None) returning at most `limit` messages with "
    "`before_id` an exclusive cursor (only ids strictly < before_id), with tests in test_messages.py "
    "asserting a message persists and that pagination with limit + before_id returns the right "
    "slice.\n"
    "- AREA B — presence & typing (team spec file `plan-presence.md`; modules presence.py + "
    "typing.py): (1) presence.py defining a PresenceTracker with connect(user, conn_id), "
    "heartbeat(conn_id, now), drop(conn_id), and recompute(now) that expires connections older than a "
    "fixed timeout and returns the current online-user set, with tests in test_presence.py asserting "
    "a user goes offline when its only connection drops (and on timeout); and (2) typing.py defining "
    "a TypingTracker with start(room, user, now) and typing(room, now) that debounces typing events "
    "per user within a fixed window and returns the set of users currently typing, with tests in "
    "test_typing.py asserting typing is debounced and expires.\n"
    "- AREA C — the RUNNABLE web UI (team spec file `plan-app.md`; ONE module app.py + "
    "test_app.py): a single "
    "integration module app.py that wires the four backend modules into a runnable, stdlib-only web "
    "chat UI. app.py MUST define `create_app(deps=None)` returning a request-handler/router object, "
    "AND a top-level `serve(port=None)` function that builds a stdlib `http.server.HTTPServer` with "
    "that handler and calls `serve_forever()` (port defaults to the PORT env var or 8000), AND an "
    "`if __name__ == \"__main__\":` block whose body is exactly `serve()`. The `serve` function is "
    "MANDATORY and is what makes the UI ACTUALLY RUNNABLE via `python app.py`; an app.py without a "
    "working `serve` + __main__ block is INCOMPLETE and must be rejected. The server serves an HTML "
    "chat page plus small JSON endpoints (POST a message to a room, GET a room's messages/history, "
    "GET the online-presence set, GET who is typing). app.py is the ONE module that MAY use the four "
    "backend modules — but it MUST import "
    "them LAZILY INSIDE functions (NEVER at module top level) and accept them via DEPENDENCY "
    "INJECTION: `create_app(deps=None)` uses the injected `deps` when one is given, and when `deps is "
    "None` it builds the REAL deps by lazily importing the actual modules BY THEIR REAL NAMES — "
    "`import rooms`, `import messages`, `import presence`, `import typing` — and constructing their "
    "objects (rooms.RoomRegistry(), messages.MessageStore(), presence.PresenceTracker(), "
    "typing.TypingTracker()). The ONLY real backend modules are rooms.py / messages.py / presence.py "
    "/ typing.py: NEVER import a `backend`, `service`, `chat`, `db`, or any other package that does "
    "not exist in this repo — doing so makes `python app.py` crash with ModuleNotFoundError at "
    "startup. test_app.py MUST build the app with INJECTED FAKE deps (simple "
    "in-file stub objects) for its main assertions so they pass WITHOUT importing any backend module, "
    "asserting that posting "
    "a message then fetching that room's messages returns it, that the chat page renders, AND that "
    "app.py exposes a callable top-level `serve` (assert `callable(app.serve)`); PLUS exactly ONE "
    "real-wiring smoke test that calls `create_app()` with NO arguments (the `deps is None` path) and "
    "asserts it returns a handler object WITHOUT raising — this single test MAY import the real "
    "backend modules and is what PROVES `python app.py` actually constructs at runtime (it would fail "
    "if app.py imported a non-existent module); it must still NOT bind a socket. So the runnable "
    "real-deps path is gate-checked by pytest. Keep "
    "app.py stdlib-only (http.server, json, html, os), deterministic, and ruff-clean; a socket is "
    "bound ONLY under the __main__ block — never at import time and never in tests.\n"
    "AREA C DEPENDS ON AREA A AND AREA B: the director MUST set the AREA C child's `depends_on` to "
    "BOTH the AREA A and AREA B children, so the app engineer's worktree branches from a company main "
    "that ALREADY carries rooms.py/messages.py/presence.py/typing.py — which the real-wiring smoke "
    "test (`create_app()` with no deps) needs in order to import them. app.py still keeps lazy imports "
    "+ dependency injection so the injected-fake tests never import the backends; only the one smoke "
    "test and real runtime (`python app.py`) hit the real modules.\n"
    "Every module, every test file, AND every team spec file lives at the REPOSITORY ROOT as a FLAT "
    "top-level file (e.g. ./rooms.py and ./test_rooms.py, ./app.py and ./test_app.py, "
    "./plan-messaging.md, ./plan-presence.md, ./plan-app.md) — NEVER inside a `src/`, `tests/`, "
    "`docs/`, or any other subdirectory, and NEVER a package. Each team spec file in particular MUST "
    "be written at the repo root as `./plan-messaging.md` / `./plan-presence.md` / `./plan-app.md` "
    "(NOT under docs/, NOT under any exec-plans/active/ folder, NOT anywhere else): the spec gate runs "
    "`python plan_check.py <plan-name>` against the repo ROOT, so a spec written into a subdirectory "
    "FAILS the gate and deadlocks the engineers that depend on it. The FIVE module files rooms.py, "
    "messages.py, "
    "presence.py, typing.py, AND app.py must ALL be accounted for across your THREE area children "
    "before you finish decomposing (AREA A = rooms+messages, AREA B = presence+typing, AREA C = app). "
    "The four BACKEND modules are fully self-contained: rooms/messages/presence/typing must NEVER "
    "import one another, so their engineer branches never collide; ONLY app.py (the integration "
    "layer) may import them, and only lazily inside functions.\n"
    "Assign each of your three area children to a DIFFERENT team lead — NOT to a PM and NOT to an "
    "engineer. Your ENTIRE job is those three area children: do NOT create any PM, spec, planning, "
    "build, verification, or integration task YOURSELF, and do NOT decompose an area into per-module "
    "children — each team lead runs its OWN decomposition from the brief you hand it. In EACH of the "
    "three area child intents, instruct the lead to have its PM write the area's team spec file FIRST "
    "AT THE REPO ROOT using the EXACT filename for that area (AREA A -> `./plan-messaging.md`, AREA B "
    "-> `./plan-presence.md`, AREA C -> `./plan-app.md` — never a generic name like plan-sprint1.md, "
    "plan.md, or a subdirectory path), and that spec MUST describe THIS area's specific named modules "
    "and their named classes/methods from the area descriptions above (e.g. AREA A is rooms.py's "
    "Room/RoomRegistry + messages.py's MessageStore). Do NOT let any team write a generic 'walking "
    "skeleton', 'vertical slice', CRUD, notes-app, database/SQLite, or any other off-topic spec — "
    "every spec and every module MUST be about THIS chatroom area and its named modules. Each engineer "
    "task must name its specific module (rooms.py / messages.py / presence.py / typing.py / app.py). "
    "Then "
    "have its engineers build to that spec — two engineers for AREA A and AREA B (one module each), "
    "one engineer for AREA C's single app.py. Within a team, every "
    "leaf engineer task is SELF-CONTAINED: the SAME engineer writes BOTH the module AND its test in "
    "that one task; NEVER split a module's implementation and its tests into separate tasks (a "
    "test-only task runs in its own worktree, cannot see the module, and will deadlock). Keep "
    "everything deterministic: pass `now` explicitly to time-based calls (no wall-clock; the only "
    "socket is app.py's __main__ server). The done-gate `python gate_check.py` run in each engineer's "
    "own task IS the check — do NOT create separate verification or integration child tasks." + _NO_THRASH
)


# The OBJECTIVE rollup DoD pinned on the chatroom GOAL (the director's task). Without it, a delegated
# parent integrates *mechanically* — the kernel lands it ``done`` the instant its subtree is terminal,
# even if the director only built ONE area (the run-18 false-``done`` regression). This ``command`` DoD
# is the STRUCTURAL decomposition guard: the kernel runs it in the director's worktree (= company main
# after every area merged) at the integrate beat, and the rollup-honesty gate parks the goal BLOCKED
# (not DONE) if it fails. It asserts all 13 named deliverables — 5 modules, their 5 tests, and the 3
# per-area plan files — exist at the flat repo root, then chains to the same stack-aware
# ``gate_check.py``. So a decomposition that drops an area (e.g. no presence.py) fails the goal HONESTLY
# instead of reporting ``done`` on a half-built repo. Kept to single-quoted Python inside one
# double-quoted ``python -c`` arg so it is portable across cmd.exe and /bin/sh (no nested double quotes).
_CHATROOM_ROLLUP_FILES = (
    "rooms.py messages.py presence.py typing.py app.py "
    "test_rooms.py test_messages.py test_presence.py test_typing.py test_app.py "
    "plan-messaging.md plan-presence.md plan-app.md"
)
_CHATROOM_ROLLUP_CMD = (
    'python -c "'
    "import sys,subprocess,pathlib; "
    f"req='{_CHATROOM_ROLLUP_FILES}'.split(); "
    "missing=[f for f in req if not pathlib.Path(f).exists()]; "
    "sys.exit('rollup gate: missing required deliverable(s): '+', '.join(missing)) if missing "
    "else sys.exit(subprocess.run([sys.executable,'gate_check.py']).returncode)"
    '"'
)
_CHATROOM_ROLLUP_DOD = Verifier.command(_CHATROOM_ROLLUP_CMD, timeout_s=900)

# spec 15 — the cross-child coherence gate, pinned as the GOAL's objective rollup DoD. The kernel's
# `_integrate_floor_verdict` runs it in the integrator's worktree (= company main once the subtree
# merged) at the director's integrate beat: `python -m chorus.coherence` reconciles the merged tree to
# the manager-authored `AGENTS.md` (declared modules present, no duplicate public symbol, `__init__`
# exports the declared API, no orphan module, the package imports clean). A non-zero exit parks the goal
# BLOCKED with the precise violations, and the adaptive integrate loop re-dispatches the manager to
# reconcile — so a split-brain subtree can never land a silent `done`. chorus is on the worktree venv,
# so `python -m chorus.coherence` resolves there.
_COHERENCE_ROLLUP_DOD = Verifier.command(
    "python -m chorus.coherence", artifact_class="subtree", timeout_s=900
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
    """Fold the repo-root ``.env`` (or ``CHORUS_ENV_FILE``) into the environment.

    The repo ``.env`` is AUTHORITATIVE: it overrides any pre-existing shell value rather than
    deferring to it. Using ``setdefault`` here was a footgun — a stale session var (e.g. a
    leftover ``AZURE_OPENAI_DEPLOYMENT=gpt-5.4-mini``) would silently defeat the pinned config and
    starve the planner so it never emits ``<spec>`` (BUG-101). Any override of a *differing* live
    value is announced so the substitution is never silent.
    """
    path = Path(os.environ.get("CHORUS_ENV_FILE", ".env"))
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


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=False, capture_output=True, text=True
    ).stdout.rstrip()


def _last_run_outcome(org: Chorus, task_id: str) -> dict[str, object]:
    """The latest beat's raw outcome dict — for an errored beat this carries the phase + error."""
    runs = org._ledger.runs.for_task(task_id)  # demo: read the kernel's own store directly
    return dict(runs[-1].outcome) if runs else {}


# The stack-aware Definition-of-Done gate, seeded into every worktree as ``gate_check.py`` and run by
# the kernel as ``python gate_check.py``. It detects the deliverable's stack from its marker files and
# runs the matching tests + lint, so the engineer's DoD is NOT restricted to Python. Kept dependency-
# free (stdlib only) and lint-clean (ruff E/F/I/B/UP/SIM/RUF, line-length 100) so it passes its own
# Python gate.
_GATE_CHECK_PY = '''\
#!/usr/bin/env python3
"""Stack-aware Definition-of-Done gate.

Detects the project's stack from marker files in the current directory and runs the matching
verification command(s): Node/TypeScript (package.json), Rust (Cargo.toml), Go (go.mod), and Python
(pyproject/*.py). Exits non-zero on the first failing gate. This replaces a hardcoded Python-only
``pytest -q && ruff check .`` so the harness can verify any deliverable, not just Python.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()


def _run(cmd: list[str]) -> int:
    print(f"[gate] $ {\' \'.join(cmd)}", flush=True)
    exe = shutil.which(cmd[0])
    if exe is None:
        print(f"[gate] tool not found on PATH: {cmd[0]}", flush=True)
        return 127
    return subprocess.run([exe, *cmd[1:]], cwd=str(ROOT)).returncode


def _has_py_sources() -> bool:
    for p in ROOT.rglob("*.py"):
        parts = set(p.parts)
        if p.name == "gate_check.py" or ".git" in parts or "node_modules" in parts:
            continue
        return True
    return False


def _node_scripts() -> dict[str, str]:
    try:
        data = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    scripts = data.get("scripts", {})
    return scripts if isinstance(scripts, dict) else {}


def main() -> int:
    steps: list[list[str]] = []

    if (ROOT / "package.json").is_file():
        scripts = _node_scripts()
        if not (ROOT / "node_modules").is_dir():
            steps.append(["npm", "install", "--no-audit", "--no-fund"])
        if "build" in scripts:
            steps.append(["npm", "run", "build"])
        if "test" in scripts:
            steps.append(["npm", "test", "--silent"])
        elif (ROOT / "tsconfig.json").is_file():
            steps.append(["npx", "tsc", "--noEmit"])

    if (ROOT / "Cargo.toml").is_file():
        steps.append(["cargo", "test"])

    if (ROOT / "go.mod").is_file():
        steps.append(["go", "test", "./..."])

    # Python is also the default floor when no other stack is detected.
    if _has_py_sources() or not steps:
        steps.append(["pytest", "-q"])
        steps.append(["ruff", "check", "."])

    for cmd in steps:
        rc = _run(cmd)
        if rc != 0:
            print(f"[gate] FAILED (rc={rc}): {\' \'.join(cmd)}", flush=True)
            return rc
    print("[gate] all gates passed", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


# The PM's Definition-of-Done gate, seeded into every worktree as ``plan_check.py`` and run by the
# kernel as ``python plan_check.py <plan-file>``. A PM's deliverable is a written spec, so its gate is
# simply: the named plan file exists and is non-empty. Kept stdlib-only and lint-clean so it passes the
# repo's own Python gate. The filename is an ARGUMENT (not hardcoded) so each area's PM is verified
# against its OWN plan file (e.g. plan-messaging.md vs plan-presence.md) — a PM that branches off a main
# already carrying a sibling area's plan can't vacuously pass on that sibling's file.
_PLAN_CHECK_PY = '''\
#!/usr/bin/env python3
"""PM Definition-of-Done gate: the named plan file exists and is non-empty."""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "plan.md"
    plan = Path(name)
    if plan.is_file() and plan.stat().st_size > 0:
        print(f"[plan] OK: {name} is present and non-empty", flush=True)
        return 0
    print(f"[plan] FAILED: {name} is missing or empty", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
'''


def _seed_repo(path: Path) -> Path:
    """A throwaway git repo the employees branch their worktrees from.

    Seeded with a README, one passing smoke test so the gate has a green baseline, and the
    stack-aware ``gate_check.py`` so the Definition-of-Done can verify ANY stack (not just Python)
    before the employee adds its own code + tests.
    """
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text("# company repo\n", encoding="utf-8")
    (path / "test_smoke.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    (path / "gate_check.py").write_text(_GATE_CHECK_PY, encoding="utf-8")
    (path / "plan_check.py").write_text(_PLAN_CHECK_PY, encoding="utf-8")
    # spec 15: seed the cross-child coherence contract so it is on company main from the start (the
    # manager re-writes it to the real module map / public API / ownership on its kickoff beat).
    seed_agents_md(path, goal_intent="the deliverable described in the goal")
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
    #
    # Pin the PM's DoD the same way: the PM's default DoD is an agent review, but this org hires no
    # reviewer, so a PM task would never go DONE. ``_objective_pm_dod`` makes it DONE when its plan file
    # exists (the kernel runs `python plan_check.py <file>`). The PM writes that file with write_file;
    # bump its sandbox to UNRESTRICTED (matching the engineer) and grant run_command so the kernel's
    # in-beat gate actually runs — dream otherwise gates a non-path command behind an interactive
    # approval the kernel can't supply.
    plugins = tuple(_pin_objective_dod(p) for p in default_roles())
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
    # We pin the Definition of Done explicitly: the objective, stack-aware gate `python gate_check.py`.
    # That is the same deterministic floor the engineer's role would run — the kernel executes it as a
    # real subprocess and the task only goes DONE when it exits 0. (Giving no DoD would instead pull
    # the role's *reviewed* build, which also needs a second LLM to sign off; the objective gate keeps
    # the demo deterministic and self-verifying.) The gate detects the deliverable's stack, so the DoD
    # is not restricted to Python.
    gate = Verifier.command(_TEAM_GATE)
    task = org.submit(task_text, assignee="eng1", dod=gate)
    _step(f"submitted {task.id} → eng1   (DoD = objective gate: {_TEAM_GATE})", c)
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


async def _run_org(
    org: Chorus, goal_text: str, *, c: _C, rollup_dod: Verifier | None = None
) -> str:
    """A 3-level org: a director delegates two areas to two team leads, who each delegate to engineers.

    Same always-on heartbeat as ``--team``, but with two manager tiers so the subtree integrate (and
    the worktree-sync fix) runs at both levels. We poll the WHOLE tree, not just the goal's direct
    children, and exit when the goal settles or both area subtrees have landed.

    ``rollup_dod`` pins an OBJECTIVE ``command`` DoD on the GOAL (the director's task). The kernel runs
    it at the director's integrate beat and the rollup-honesty gate parks the goal BLOCKED (not DONE) if
    it fails — the structural decomposition guard. ``None`` keeps the manager's mechanical rollup.
    """
    _hr("HIRE — a 3-level org: 1 director · 2 managers · each lead = 3 engineers + 1 PM", c)
    org.hire(name="vera", role="manager")                       # L1 — the director
    org.hire(name="moe", role="manager", reports_to="vera")     # L2 — manager A
    org.hire(name="max", role="manager", reports_to="vera")     # L2 — manager B
    # L3 — moe's team: 3 engineers + 1 PM
    org.hire(name="ada", role="engineer", reports_to="moe")
    org.hire(name="bo", role="engineer", reports_to="moe")
    org.hire(name="cy", role="engineer", reports_to="moe")
    org.hire(name="pat", role="pm", reports_to="moe")
    # L3 — max's team: 3 engineers + 1 PM
    org.hire(name="di", role="engineer", reports_to="max")
    org.hire(name="ev", role="engineer", reports_to="max")
    org.hire(name="fi", role="engineer", reports_to="max")
    org.hire(name="quinn", role="pm", reports_to="max")
    _step("hired vera(director) → moe,max(managers) → "
          "ada,bo,cy,pat(pm) | di,ev,fi,quinn(pm)", c)

    _hr("SUBMIT — state the goal; the director decomposes across the two team leads", c)
    goal = org.submit(goal_text, assignee="vera", dod=rollup_dod)
    _step(f"submitted goal {goal.id} → vera", c)
    if rollup_dod is not None:
        _step("goal DoD = objective rollup gate: all required deliverables exist + gate_check passes", c)
    print(c("90", f"    goal: {goal_text[:160]}…"))

    _hr("HEARTBEAT — org.start(): two manager tiers integrate their subtrees as work lands", c)
    org.start()
    deadline = time.monotonic() + 1200.0   # 2-manager generic tasks settle within ~20 min
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
                    print(c("94;1", "  ⏳ all area subtrees landed — every module (incl. app.py) is on "
                                    "company main; waiting for the director's integrate beat to close the goal…"))
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
        org_goal = _CHATROOM_GOAL if args.chatroom else _ORG_GOAL
        # spec 15: the goal's integrate is gated on the coherence checker reconciling the merged tree to
        # AGENTS.md — the kernel's _integrate_floor_verdict runs it against company main, so a split-brain
        # subtree parks the goal BLOCKED (with the precise violations) instead of a silent `done`.
        rollup = _CHATROOM_ROLLUP_DOD if args.chatroom else _COHERENCE_ROLLUP_DOD
        final = await _run_org(org, args.task or org_goal, c=c, rollup_dod=rollup)
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
            from report import (
                write_report,  # type: ignore[import-not-found]  # sibling in standup-app/
            )

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
                        help="3-level org: 1 director → 2 managers → 2 engineers + 1 PM each")
    parser.add_argument("--chatroom", action="store_true",
                        help="with --org: run HARD_TASKS #15 (presence chatroom) instead of the demo goal")
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
