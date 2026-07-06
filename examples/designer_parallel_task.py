"""One-off parallel Designer hard task with a LOOSE, intent-only prompt.

Deliberately states ONLY the design intent (the surface + goal) — no design system, no tools, no
skills, no sections named — so Dara must choose her own method end-to-end: author a DESIGN.md (choosing
a house style via the design_exemplar tool), research patterns, explore on-system variants, self-lint
tokens + a11y, run the Design-Critic loop, and write a buildable design_spec.md.

Unique company id (designer-hard-parallel) so it runs alongside the `author` task without a worktree
collision. Skips cleanly (exit 0) when the AZURE_OPENAI_* env vars are unset.
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

_COMPANY = "designer-hard-parallel"
_RUN = "run-parallel"
# Intent only: the product and the surface, nothing about HOW to design it.
_INTENT = (
    "We're building Cadence, a calm team stand-up tool that replaces the daily sync meeting with async "
    "written check-ins. Design the screen a team member sees when they open the app to write and post "
    "their check-in for the day."
)


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


def _artifacts_dir() -> Path:
    root = Path("chorus") if Path("chorus").is_dir() else Path(".")
    out = root / "reports" / "designer-artifacts" / "parallel"
    out.mkdir(parents=True, exist_ok=True)
    return out


async def main() -> int:
    key = os.environ.get("AZURE_OPENAI_API_KEY")
    base = os.environ.get("AZURE_OPENAI_BASE_URL")
    dep = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (key and base and dep):
        print("skipping: set AZURE_OPENAI_API_KEY / AZURE_OPENAI_BASE_URL / AZURE_OPENAI_DEPLOYMENT")
        return 0

    workroot = Path("chorus") if Path("chorus").is_dir() else Path(".")
    company_dir = workroot / ".chorus" / "work" / _COMPANY
    with contextlib.suppress(Exception):
        if company_dir.exists():
            shutil.rmtree(company_dir)

    roles = RoleRegistry.from_plugins(default_roles())
    factory = EmployeeHarnessFactory(
        api_key=key, base_url=base, deployment=dep, company_id=_COMPANY,
        roles=roles, timeout_s=900.0,
    )
    mat = factory.materialize(Employee(id="dara", name="Dara", role="designer"))

    verifier = designer_plugin().dod_generator(_INTENT)
    print("\n" + "=" * 78)
    print(f"TASK [parallel]  DoD -> {verifier.kind.value}")
    print(f"intent: {_INTENT}")
    print("=" * 78)

    outcome = await mat.runner.run_task(
        task_id=_RUN, intent=_INTENT, run_id=_RUN,
        verification=verifier.verification_steps(), rubric=verifier.rubric(), observer=_observer,
    )
    print(f"\n[parallel] passed = {outcome.passed}")
    print(f"[parallel] summary = {outcome.summary}")

    out = _artifacts_dir()
    saved = []
    for name in (DESIGN_SPEC_DOC, DESIGN_SYSTEM_DOC):
        f = mat.working_dir / name
        if f.is_file():
            shutil.copy2(f, out / name)
            saved.append(f"{name} ({f.stat().st_size} B, {len(f.read_text(encoding='utf-8').split())} words)")
    (out / "_meta.txt").write_text(
        f"key=parallel\npassed={outcome.passed}\nsummary={outcome.summary}\n"
        f"intent={_INTENT}\nworking_dir={mat.working_dir}\n",
        encoding="utf-8",
    )
    print(f"[parallel] artifacts -> {out}  :: {', '.join(saved) if saved else '(none)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
