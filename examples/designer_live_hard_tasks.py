"""Hard, goal-only Designer tasks — stress Dara on on-system fidelity, accessibility, and taste, at
increasing difficulty. Each intent states ONLY the goal (the surface to design): no tools, skills, or
sections are named, so the Designer must choose its own method — read the system, explore on-system
variants, self-lint tokens + a11y, and write a buildable ``design_spec.md``.

Tasks (easy -> very hard):
  1. baseline  — a settings page, DESIGN.md provided: must stay on-system, cover states + a11y.
  2. author    — NO design system yet: must author a DESIGN.md (canonical 9-section) *and* the spec.
  3. dense     — a data-dense dashboard table (filters, bulk actions, every state, keyboard + WCAG AA).
  4. drift     — a drifted LoginForm.tsx (hardcoded hex/px): audit vs DESIGN.md, fix on-system, spec it.

Each run copies the produced artifacts to ``reports/designer-artifacts/<key>/`` for offline review.

Run all, or one by index:
    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    python examples/designer_live_hard_tasks.py [1|2|3|4]

Skips cleanly (exit 0) when the AZURE_OPENAI_* env vars are unset.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")

from chorus.events import Event, EventKind
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee
from chorus_employee.designer import DESIGN_SPEC_DOC, DESIGN_SYSTEM_DOC, designer_plugin
from chorus_harness import EmployeeHarnessFactory

# --- a compact but real design system (canonical 9-section format) seeded for on-system tasks --------

_DESIGN_MD = """\
# Nimbus — Design System

## 1. Visual Theme
Calm, dense, developer-grade. Dark-first. Content over chrome. Nothing decorative earns its pixels.

## 2. Color Palette & Roles
Semantic tokens only — never raw hex in a surface.
- `color.bg.canvas` = #0B0E14   (app background)
- `color.bg.surface` = #141922  (cards, panels)
- `color.bg.raised` = #1C2230   (menus, popovers)
- `color.border.subtle` = #232A38
- `color.text.primary` = #E6EAF2  (contrast 12.6:1 on canvas)
- `color.text.secondary` = #9BA6B8 (contrast 5.1:1 on canvas)
- `color.accent.default` = #4C8DFF (primary action)
- `color.accent.hover` = #6BA0FF
- `color.danger.default` = #FF5C5C
- `color.success.default` = #3FCF8E

## 3. Typography Rules
- Family: `Inter` (UI), `JetBrains Mono` (code/values).
- Scale (rem): `text.xs` 0.75 / `text.sm` 0.875 / `text.md` 1.0 / `text.lg` 1.25 / `text.xl` 1.5.
- Weights: 400 body, 500 labels, 600 headings. Line-height 1.5 body, 1.25 headings.

## 4. Component Stylings
- `Button`: variants `primary` (accent bg), `secondary` (surface bg + subtle border), `ghost`, `danger`.
  Radius `radius.md` 8px. Height 36px. Focus ring 2px `color.accent.default` at 2px offset.
- `Input`: surface bg, subtle border, 36px height, `text.sm` label above.
- `Table`: 44px rows, sticky header `bg.raised`, zebra off, row hover `bg.raised`.
- `Badge`: pill, `text.xs`, semantic color roles.

## 5. Layout Principles
- Spacing scale (px, 4-based): `space.1` 4 / `space.2` 8 / `space.3` 12 / `space.4` 16 / `space.6` 24 / `space.8` 32.
- 12-column grid, max content width 1200px, gutter `space.6`.
- Left nav 240px, collapses to icons < 960px.

## 6. Depth & Elevation
Two levels only: surface (flat) and raised (`shadow.sm` = 0 1px 2px rgba(0,0,0,.4)). No heavy shadows.

## 7. Do's and Don'ts
- DO use semantic tokens; DO keep one primary action per view.
- DON'T hardcode hex or px outside the scale; DON'T use color as the only state signal.

## 8. Responsive Behavior
Breakpoints: `sm` 640 / `md` 960 / `lg` 1200. Below `md`: nav collapses, tables become stacked cards.

## 9. Agent Prompt Guide
When generating UI: dark surfaces, semantic tokens, Inter, 4px spacing rhythm, one primary action,
visible focus rings, every interactive state defined, WCAG AA contrast minimum.
"""

# A component that has drifted off-system: raw hex, off-scale px, no focus ring, color-only error.
_DRIFTED_LOGIN = """\
export function LoginForm() {
  return (
    <form style={{ background: '#12151c', padding: '18px', borderRadius: '5px' }}>
      <label style={{ color: '#8f9bb3', fontSize: '13px' }}>Email</label>
      <input style={{ background: '#0d1017', border: '1px solid #2b2b2b', height: '40px' }} />
      <label style={{ color: '#8f9bb3', fontSize: '13px' }}>Password</label>
      <input style={{ background: '#0d1017', border: '1px solid #2b2b2b', height: '40px' }} />
      <span style={{ color: 'red' }}>Invalid credentials</span>
      <button style={{ background: '#3b7ce0', color: '#fff', height: '38px', borderRadius: '5px' }}>
        Sign in
      </button>
    </form>
  );
}
"""


def _seed_design_system(work: Path) -> None:
    (work / DESIGN_SYSTEM_DOC).write_text(_DESIGN_MD, encoding="utf-8")


def _seed_drift(work: Path) -> None:
    (work / DESIGN_SYSTEM_DOC).write_text(_DESIGN_MD, encoding="utf-8")
    (work / "LoginForm.tsx").write_text(_DRIFTED_LOGIN, encoding="utf-8")


# --- tasks (increasing difficulty) -------------------------------------------

_TASKS = [
    {
        "key": "baseline",
        "company": "designer-hard-baseline",
        "run": "run-baseline",
        "seed": _seed_design_system,
        "intent": (
            "Our product Nimbus already has a design system (see DESIGN.md in your working directory). "
            "Design the user **Account Settings** page: profile fields, password change, and a danger "
            "zone to delete the account. It must stay on the existing system. Write a spec an engineer "
            "can build directly to."
        ),
    },
    {
        "key": "author",
        "company": "designer-hard-author",
        "run": "run-author",
        "seed": None,  # no DESIGN.md — the designer must establish one
        "intent": (
            "We are building Relay, a self-hosted webhook-inspection tool for developers, and we have no "
            "design system yet. Design the first-run onboarding flow (connect a source, send a test "
            "event, see it arrive) and establish the visual language it uses. Deliver something an "
            "engineer can build directly to."
        ),
    },
    {
        "key": "dense",
        "company": "designer-hard-dense",
        "run": "run-dense",
        "seed": _seed_design_system,
        "intent": (
            "On the Nimbus system (see DESIGN.md), design the **Events** screen: a dense, sortable table "
            "of incoming webhook events with column filters, multi-select bulk actions (retry, delete), "
            "and pagination. It must be fully operable by keyboard and meet WCAG AA. Account for what the "
            "screen shows before any events arrive, while loading, and when a fetch fails. Write a spec "
            "an engineer can build directly to."
        ),
    },
    {
        "key": "drift",
        "company": "designer-hard-drift",
        "run": "run-drift",
        "seed": _seed_drift,
        "intent": (
            "The file LoginForm.tsx in your working directory has drifted off our design system (see "
            "DESIGN.md). Audit it, list every place it violates the system or accessibility, give the "
            "exact on-system fix for each, and write the corrected, buildable spec for the login form."
        ),
    },
]


def _short(value: object, n: int = 180) -> str:
    s = str(value).replace("\n", " / ")
    return s if len(s) <= n else s[:n] + "..."


def _observer(ev: Event) -> None:
    p = ev.payload
    if ev.kind is EventKind.RUN_TOOL_USE:
        print(f"  [tool ->] {p.get('tool')}  {_short(p.get('input'))}")
    elif ev.kind is EventKind.RUN_TOOL_RESULT:
        flag = " (ERROR)" if p.get("is_error") else ""
        print(f"  [tool <-] {p.get('tool')}{flag}")
    elif ev.kind is EventKind.RUN_EVALUATED:
        keys = {k: v for k, v in p.items() if k != "dream_kind"}
        print(f"  [EVALUATED] {_short(keys, 600)}")
    elif ev.kind is EventKind.RUN_DONE:
        print("== beat done ==")


def _artifacts_dir(key: str) -> Path:
    root = Path("chorus") if Path("chorus").is_dir() else Path(".")
    out = root / "reports" / "designer-artifacts" / key
    out.mkdir(parents=True, exist_ok=True)
    return out


async def _run_task(task: dict, key: str, base: str, dep: str) -> None:
    # Clean slate FIRST — before the factory opens the ledger/worktree — so a prior run's artefacts
    # don't trip the planner's idempotency guard (and Windows can't lock the dir out from under rmtree).
    workroot = Path("chorus") if Path("chorus").is_dir() else Path(".")
    company_dir = workroot / ".chorus" / "work" / task["company"]
    with contextlib.suppress(Exception):
        if company_dir.exists():
            shutil.rmtree(company_dir)

    roles = RoleRegistry.from_plugins(default_roles())
    factory = EmployeeHarnessFactory(
        api_key=key,
        base_url=base,
        deployment=dep,
        company_id=task["company"],
        roles=roles,
        timeout_s=900.0,
    )

    mat = factory.materialize(Employee(id="dara", name="Dara", role="designer"))
    if task["seed"]:
        task["seed"](mat.working_dir)

    verifier = designer_plugin().dod_generator(task["intent"])
    print("\n" + "=" * 78)
    print(f"TASK [{task['key']}]  DoD -> {verifier.kind.value}")
    print(f"intent: {task['intent']}")
    print("=" * 78)

    outcome = await mat.runner.run_task(
        task_id=task["run"],
        intent=task["intent"],
        run_id=task["run"],
        verification=verifier.verification_steps(),
        rubric=verifier.rubric(),
        observer=_observer,
    )
    print(f"\n[{task['key']}] passed = {outcome.passed}")
    print(f"[{task['key']}] summary = {outcome.summary}")

    out = _artifacts_dir(task["key"])
    saved = []
    for name in (DESIGN_SPEC_DOC, DESIGN_SYSTEM_DOC):
        f = mat.working_dir / name
        if f.is_file():
            shutil.copy2(f, out / name)
            saved.append(
                f"{name} ({f.stat().st_size} B, {len(f.read_text(encoding='utf-8').split())} words)"
            )
    (out / "_meta.txt").write_text(
        f"key={task['key']}\npassed={outcome.passed}\nsummary={outcome.summary}\n"
        f"intent={task['intent']}\nworking_dir={mat.working_dir}\n",
        encoding="utf-8",
    )
    print(f"[{task['key']}] artifacts -> {out}  :: {', '.join(saved) if saved else '(none)'}")


async def main() -> int:
    key = os.environ.get("AZURE_OPENAI_API_KEY")
    base = os.environ.get("AZURE_OPENAI_BASE_URL")
    dep = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (key and base and dep):
        print(
            "skipping: set AZURE_OPENAI_API_KEY / AZURE_OPENAI_BASE_URL / AZURE_OPENAI_DEPLOYMENT"
        )
        return 0

    which = sys.argv[1] if len(sys.argv) > 1 else None
    tasks = _TASKS
    if which is not None:
        tasks = [_TASKS[int(which) - 1]]

    for task in tasks:
        await _run_task(task, key, base, dep)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
