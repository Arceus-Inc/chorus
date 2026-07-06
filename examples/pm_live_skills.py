"""Live e2e — each PM skill, end to end, proving the Option C bundle loop.

Runs the PM once per Decision-core skill (evidence-brief, options-set-generator, decision-record,
recommendation-canvas). For each, we watch the bus for:
  - the `skill` tool loading that playbook (its body enters context), and
  - any `read_file` into `.harness/skills/...` — the payoff of Option C: the model reaching a skill's
    bundled reference files (recommendation-canvas points at `template.md` + `references/sample.md`).

The recommendation-canvas task explicitly asks the PM to read those bundled files, so its run exercises
the materialised-bundle path; the other three inline their templates in the SKILL.md body.

    # .env holds AZURE_OPENAI_* (loaded here via python-dotenv, not `uv run --env-file`)
    uv run python examples/pm_live_skills.py               # all four skills
    uv run python examples/pm_live_skills.py decision-record   # just one (cheaper to iterate)
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # populate os.environ from .env BEFORE importing chorus (imports may read env)

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")

from chorus.events import Event, EventKind  # noqa: E402
from chorus.roles import RoleRegistry, default_roles  # noqa: E402
from chorus.workforce import Employee  # noqa: E402
from chorus_employee.pm import pm_plugin  # noqa: E402
from chorus_harness import EmployeeHarnessFactory  # noqa: E402


@dataclass
class SkillTask:
    """One skill to exercise: the name to watch for + the intent that should trigger it."""

    skill: str
    intent: str


# Self-contained intents (inputs inline) so the PM authors directly with the skill — no research spawn.
_TASKS: tuple[SkillTask, ...] = (
    SkillTask(
        "evidence-brief",
        "Load your `evidence-brief` skill, then write an Evidence Brief to `plan.md` for the decision "
        "'Should we add SSO to the Team plan?'. Evidence to synthesise: (1) 12 of 40 enterprise trials "
        "cited 'no SSO' as a blocker [sales notes, high confidence]; (2) support saw 8 SSO requests last "
        "quarter [Zendesk, medium]; (3) one competitor ships SSO on their $99 tier [single blog post, "
        "low]. Give confidence, coverage, contradictions, and open questions.",
    ),
    SkillTask(
        "options-set-generator",
        "Load your `options-set-generator` skill, then write an Options Set (>=3 distinct options) to "
        "`plan.md` for 'How to improve onboarding activation'. Constraints: one 3-engineer team, 6 weeks, "
        "must not regress signup conversion. Include a tradeoff matrix and second-order effects.",
    ),
    SkillTask(
        "decision-record",
        "Load your `decision-record` skill, then write a Decision Record to `plan.md` for the decision "
        "'We will adopt weekly release trains'. Include >=2 alternatives considered, rationale, risks with "
        "mitigations, success metrics, and explicit revisit triggers.",
    ),
    SkillTask(
        "recommendation-canvas",
        "Load your `recommendation-canvas` skill. Its body references a bundled `template.md` and "
        "`references/sample.md` — READ BOTH of those bundled files first, then produce a full AI "
        "Recommendation Canvas to `plan.md` for 'SmartReminders — an AI-timed invoice-reminder feature "
        "for freelancers'. Follow the template's structure and match the depth of the sample.",
    ),
    # --- Discovery group ---
    SkillTask(
        "problem-statement",
        "Load your `problem-statement` skill and READ its bundled `template.md` + `references/sample.md`, "
        "then write a crisp user problem statement to `plan.md` for: freelance designers miss invoice due "
        "dates because reminders are manual and easy to forget.",
    ),
    SkillTask(
        "problem-framing-canvas",
        "Load your `problem-framing-canvas` skill and READ its bundled `template.md` + "
        "`references/sample.md`, then frame the problem space to `plan.md` for: low activation in a B2B "
        "onboarding flow, separating the problem, context, and constraints from any fix.",
    ),
    SkillTask(
        "discovery-process",
        "Load your `discovery-process` skill and READ its bundled `template.md` + `references/sample.md`, "
        "then draft an end-to-end discovery plan to `plan.md` for validating demand for an AI "
        "meeting-notes feature (goals, segments, methods, synthesis).",
    ),
    SkillTask(
        "jobs-to-be-done",
        "Load your `jobs-to-be-done` skill and READ its bundled `template.md` + `references/sample.md`, "
        "then produce a JTBD analysis to `plan.md` for freelancers managing client invoicing — functional, "
        "social, and emotional jobs, plus pains and desired gains.",
    ),
    SkillTask(
        "proto-persona",
        "Load your `proto-persona` skill and READ its bundled `template.md` + `references/sample.md`, "
        "then write a proto-persona to `plan.md` for the primary user of an AI invoice-reminder tool.",
    ),
)


@dataclass
class Trace:
    """What the bus revealed for one skill run."""

    skills_loaded: list[str] = field(default_factory=list)
    skill_errors: list[str] = field(default_factory=list)
    bundle_reads: list[str] = field(default_factory=list)
    offloaded_reads: int = 0


def _short(value: object, n: int = 200) -> str:
    s = str(value).replace("\n", " / ")
    return s if len(s) <= n else s[:n] + "..."


def _skill_name(raw: object) -> str:
    if isinstance(raw, dict):
        return str(raw.get("name", raw))
    return _short(raw, 60)


def _observer_for(trace: Trace):
    def _obs(ev: Event) -> None:
        p = ev.payload
        if ev.kind is EventKind.RUN_TOOL_USE:
            tool = p.get("tool")
            if tool == "skill":
                name = _skill_name(p.get("input"))
                trace.skills_loaded.append(name)
                print(f"  [SKILL ->] load {name}")
            elif tool == "read_file":
                path = _short(p.get("input"), 120)
                if ".harness/skills" in path:
                    trace.bundle_reads.append(path)
                    print(f"  [BUNDLE ->] read_file {path}")
            elif tool == "read_offloaded":
                trace.offloaded_reads += 1
                print(f"  [OFFLOAD ->] read_offloaded {_short(p.get('input'), 100)}")
        elif ev.kind is EventKind.RUN_TOOL_RESULT:
            if p.get("tool") == "skill":
                flag = " (ERROR)" if p.get("is_error") else ""
                if p.get("is_error"):
                    trace.skill_errors.append(_short(p.get("content_preview")))
                print(f"  [SKILL <-]{flag} {_short(p.get('content_preview'))}")
        elif ev.kind is EventKind.RUN_DONE:
            print("  == beat done ==")

    return _obs


async def _run_one(factory: EmployeeHarnessFactory, task: SkillTask) -> tuple[Trace, bool, str]:
    emp = Employee(id=f"piper-{task.skill}", name="Piper", role="pm")
    mat = factory.materialize(emp)
    trace = Trace()

    print(f"\n{'=' * 78}\nSKILL: {task.skill}\nworktree: {mat.working_dir}")
    verifier = pm_plugin().dod_generator(task.intent)
    outcome = await mat.runner.run_task(
        task_id=f"skill-{task.skill}",
        intent=task.intent,
        run_id=f"run-{task.skill}",
        verification=verifier.verification_steps(),
        rubric=verifier.rubric(),
        observer=_observer_for(trace),
    )
    plan = mat.working_dir / "plan.md"
    plan_len = len(plan.read_text(encoding="utf-8")) if plan.is_file() else 0
    print(
        f"  loaded={trace.skills_loaded} bundle_reads={len(trace.bundle_reads)} "
        f"offloaded_reads={trace.offloaded_reads} passed={outcome.passed} plan.md={plan_len}B"
    )
    return trace, outcome.passed, str(mat.working_dir)


async def main() -> int:
    key = os.environ.get("AZURE_OPENAI_API_KEY")
    base = os.environ.get("AZURE_OPENAI_BASE_URL")
    dep = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (key and base and dep):
        print(
            "skipping: set AZURE_OPENAI_API_KEY / AZURE_OPENAI_BASE_URL / AZURE_OPENAI_DEPLOYMENT"
        )
        return 0

    only = sys.argv[1] if len(sys.argv) > 1 else None
    tasks = [t for t in _TASKS if only is None or t.skill == only]
    if not tasks:
        print(f"no such skill: {only!r}; choose from {[t.skill for t in _TASKS]}")
        return 2

    # Fresh workspace each invocation: a persisted worktree would keep a prior run's plan.md, and the PM
    # would short-circuit ("already done") instead of loading the skill. e2e results must be uncontaminated.
    company_root = Path.cwd() / ".chorus" / "work" / "pm-skills"
    if company_root.exists():
        shutil.rmtree(company_root, ignore_errors=True)

    factory = EmployeeHarnessFactory(
        api_key=key,
        base_url=base,
        deployment=dep,
        company_id="pm-skills",
        roles=RoleRegistry.from_plugins(default_roles()),
        timeout_s=900.0,
    )

    rows: list[tuple[str, Trace, bool]] = []
    for task in tasks:
        trace, passed, _ = await _run_one(factory, task)
        rows.append((task.skill, trace, passed))

    print(f"\n{'=' * 78}\nSUMMARY — each PM skill, end to end\n{'=' * 78}")
    print(f"{'skill':24}  {'loaded?':8}  {'bundle':7}  {'offload':8}  {'DoD':6}")
    for name, trace, passed in rows:
        loaded = "yes" if name in trace.skills_loaded else "NO"
        print(
            f"{name:24}  {loaded:8}  {len(trace.bundle_reads):<7}  "
            f"{trace.offloaded_reads:<8}  {'pass' if passed else 'fail'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
