"""Keyed M3 verification — prove a LIVE manager actually calls ``submit_task`` and ``assign_task``.

The happy-path loop never exercises these tools: when every child is done the structural guard withholds
them and the manager just accepts. They are *reactive* tools — they fire only when a delegated subtree
comes back with a real problem (``recommended_action == "react"``). So this harness stages exactly that
problem and runs one real manager beat against it, twice:

    Probe SUBMIT  — a big goal whose subtree came back with one child CANCELLED (a report could not
                    finish it). The manager must patch the gap with ``submit_task`` (a new child).
    Probe ASSIGN  — a subtree with one existing child STUCK on its original assignee. The manager must
                    reroute that existing child to its other report with ``assign_task``.

Each probe materializes the manager as its real role (the chorus capability tools registered into its
dream harness, bound to the ledger), writes the integrate packet it reads, runs ONE live beat, and then
checks the ledger actually mutated the way the tool should. Results are written to a standalone HTML
report under ``reports/``.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/m3_submit_assign_verify.py

Skips cleanly (exit 0) when the Azure env vars are unset.
"""

from __future__ import annotations

import asyncio
import html
import os
import uuid

_EXAMPLE_COMPANY = str(uuid.uuid5(uuid.NAMESPACE_URL, "chorus-example"))  # one stable demo org
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from chorus.events import Event, EventKind
from chorus.heartbeat import IntegrateContextPacket
from chorus.ledger import (
    Artifact,
    ArtifactType,
    DodStatus,
    Ledger,
    Run,
    RunStatus,
    Task,
    TaskStatus,
)
from chorus.lifecycle import CapabilityService, ChildPlan
from chorus.observability import EventBus
from chorus.outcomes import Verifier
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee
from chorus_cli._beats import default_pricing_from_env
from chorus_harness import EmployeeHarnessFactory

_REPORT = Path(__file__).resolve().parents[1] / "reports" / "m3-submit-assign-verify.html"


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


@dataclass
class ToolCall:
    tool: str
    input: str
    is_error: bool
    result: str


@dataclass
class ProbeResult:
    name: str
    tool_under_test: str
    goal: str
    staged: list[str]
    tool_calls: list[ToolCall] = field(default_factory=list)
    children_before: int = 0
    children_after: int = 0
    summary: str = ""
    passed: bool = False
    verdict_reason: str = ""


class _ToolBus(EventBus):
    """Capture every tool call the live manager makes during the beat."""

    def __init__(self) -> None:
        super().__init__(log_path=None)
        self.calls: list[ToolCall] = []
        self._pending: dict[str, str] = {}

    def emit(self, event: Event) -> None:
        p = event.payload
        if event.kind is EventKind.RUN_TOOL_USE:
            tool = str(p.get("tool", "?"))
            self._pending[tool] = str(p.get("input", ""))[:400]
            _log(f"    → TOOL {tool}  {str(p.get('input', ''))[:200]}")
        elif event.kind is EventKind.RUN_TOOL_RESULT:
            tool = str(p.get("tool", "?"))
            is_err = bool(p.get("is_error"))
            self.calls.append(
                ToolCall(
                    tool=tool,
                    input=self._pending.get(tool, ""),
                    is_error=is_err,
                    result=str(p.get("content", ""))[:300],
                )
            )
            _log(f"    ← {tool} [{'ERR' if is_err else 'ok'}]  {str(p.get('content', ''))[:160]}")


def _seed_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text("# text utils\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "-c",
            "user.name=s",
            "-c",
            "user.email=s@x",
            "commit",
            "-m",
            "seed",
        ],
        check=True,
        capture_output=True,
    )


def _mark_done_passing(ledger: Ledger, task_id: str, *, by: str) -> None:
    """Make a child read as a finished, green deliverable in the integrate packet."""
    run_id = f"run_{task_id}"
    ledger.runs.create(
        Run(
            id=run_id,
            employee_id=by,
            task_id=task_id,
            status=RunStatus.SUCCEEDED,
            outcome={"summary": f"{task_id} landed"},
        )
    )
    dod = ledger.dod.create(task_id, Verifier.command("pytest -q", artifact_class="file"))
    ledger.dod.record_verdict(dod.id, DodStatus.PASSED, verdict={"stdout": "ok"}, run_id=run_id)
    ledger.artifacts.create(
        Artifact(
            id=f"art_{task_id}",
            task_id=task_id,
            type=ArtifactType.PR,
            is_primary=True,
            resource_ref={"merged": True},
        )
    )
    ledger.tasks.set_status(task_id, TaskStatus.DONE)


async def _run_probe(
    factory: EmployeeHarnessFactory,
    ledger: Ledger,
    *,
    name: str,
    tool_under_test: str,
    parent_id: str,
    goal: str,
    stage: list[str],
) -> ProbeResult:
    result = ProbeResult(name=name, tool_under_test=tool_under_test, goal=goal, staged=stage)

    # The manager beat needs at least one prior run on the parent (the kickoff) so the packet's
    # iteration is well-defined, plus the live integrate run.
    ledger.runs.create(
        Run(
            id=f"{parent_id}_kick",
            employee_id="moe",
            task_id=parent_id,
            status=RunStatus.SUCCEEDED,
            outcome={"summary": "delegated"},
        )
    )
    integrate_run = f"{parent_id}_integrate"
    ledger.runs.create(
        Run(id=integrate_run, employee_id="moe", task_id=parent_id, status=RunStatus.RUNNING)
    )

    result.children_before = len(ledger.tasks.children(parent_id))
    recommend = IntegrateContextPacket.recommended_for(ledger, parent_id)
    _log(
        f"\n{'═' * 72}\n{name}  (verifying {tool_under_test}) — recommended_action={recommend}\n{'═' * 72}"
    )

    # Materialize the manager FOR THIS integrate beat: the factory drops `decompose`, and keeps
    # submit_task/assign_task because the subtree is not complete (recommend=react).
    mat = factory.materialize(ledger.employees.get("moe"), task_id=parent_id)  # type: ignore[arg-type]
    tools = list(getattr(mat.config, "tools", ()))
    _log(f"  manager tools this beat: {tools}")

    # Write the Scrum packet the manager reads from its worktree.
    IntegrateContextPacket.build(ledger, parent_task_id=parent_id).write(mat.working_dir)

    bus = _ToolBus()
    outcome = await mat.runner.run_task(
        task_id=parent_id, run_id=integrate_run, intent=goal, observer=bus.emit
    )
    result.tool_calls = bus.calls
    result.summary = outcome.summary or ""
    result.children_after = len(ledger.tasks.children(parent_id))
    return result


def _verify_submit(result: ProbeResult, ledger: Ledger, parent_id: str) -> None:
    new_children = result.children_after - result.children_before
    called = [c for c in result.tool_calls if c.tool == "submit_task" and not c.is_error]
    result.passed = bool(called) and new_children >= 1
    result.verdict_reason = (
        f"submit_task called {len(called)}x (ok); subtree grew {result.children_before}→"
        f"{result.children_after}"
        if result.passed
        else f"no successful submit_task (calls={[c.tool for c in result.tool_calls]}, "
        f"children {result.children_before}→{result.children_after})"
    )


def _verify_assign(result: ProbeResult, ledger: Ledger, parent_id: str, *, child_id: str) -> None:
    child = ledger.tasks.get(child_id)
    owner = child.assignee_employee_id if child is not None else None
    rerouted = owner == "bob"
    called = [c for c in result.tool_calls if c.tool == "assign_task" and not c.is_error]
    result.passed = bool(called) and rerouted
    result.verdict_reason = (
        f"assign_task called {len(called)}x (ok); child {child_id} now owned by {owner!r}"
        if result.passed
        else f"no successful reroute (calls={[c.tool for c in result.tool_calls]}, owner={owner!r})"
    )


def _render_html(results: list[ProbeResult], *, goal_headline: str) -> str:
    def esc(s: object) -> str:
        return html.escape(str(s))

    cards = []
    for r in results:
        badge = "PASS" if r.passed else "FAIL"
        badge_cls = "pass" if r.passed else "fail"
        calls_rows = (
            "".join(
                f"<tr class='{'err' if c.is_error else 'okrow'}'><td><code>{esc(c.tool)}</code></td>"
                f"<td><code>{esc(c.input)}</code></td><td>{'error' if c.is_error else 'ok'}</td>"
                f"<td><code>{esc(c.result)}</code></td></tr>"
                for c in r.tool_calls
            )
            or "<tr><td colspan='4' class='muted'>— no tool calls —</td></tr>"
        )
        staged = "".join(f"<li>{esc(s)}</li>" for s in r.staged)
        cards.append(f"""
        <section class="card">
          <div class="card-head">
            <h2>{esc(r.name)}</h2>
            <span class="badge {badge_cls}">{badge}</span>
          </div>
          <p class="sub">Tool under test: <code>{esc(r.tool_under_test)}</code></p>
          <p class="goal"><strong>Goal given to the manager:</strong><br>{esc(r.goal)}</p>
          <h3>Staged subtree (the problem the manager faced)</h3>
          <ul class="staged">{staged}</ul>
          <h3>Live manager tool calls</h3>
          <table>
            <thead><tr><th>tool</th><th>input</th><th>result</th><th>detail</th></tr></thead>
            <tbody>{calls_rows}</tbody>
          </table>
          <p class="verdict"><strong>Verdict:</strong> {esc(r.verdict_reason)}</p>
          <p class="muted">subtree size {r.children_before} → {r.children_after} · manager said: “{esc(r.summary)}”</p>
        </section>""")

    overall = "ALL PROBES PASSED" if all(r.passed for r in results) else "SOME PROBES FAILED"
    overall_cls = "pass" if all(r.passed for r in results) else "fail"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>M3 — submit_task / assign_task live verification</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; margin: 0; padding: 2rem;
          background: #0f1115; color: #e6e8eb; line-height: 1.5; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 .25rem; }}
  .lead {{ color: #9aa0a6; margin: 0 0 1.5rem; max-width: 70ch; }}
  .overall {{ display: inline-block; padding: .4rem .9rem; border-radius: 999px; font-weight: 700;
              letter-spacing: .03em; margin-bottom: 2rem; }}
  .overall.pass {{ background: #0e3a23; color: #4ade80; }}
  .overall.fail {{ background: #3a0e12; color: #f87171; }}
  .card {{ background: #16191f; border: 1px solid #262b33; border-radius: 12px; padding: 1.25rem 1.5rem;
           margin-bottom: 1.5rem; }}
  .card-head {{ display: flex; align-items: center; justify-content: space-between; }}
  h2 {{ font-size: 1.2rem; margin: 0; }}
  h3 {{ font-size: .8rem; text-transform: uppercase; letter-spacing: .06em; color: #9aa0a6;
        margin: 1.2rem 0 .4rem; }}
  .badge {{ padding: .2rem .7rem; border-radius: 999px; font-weight: 700; font-size: .85rem; }}
  .badge.pass {{ background: #0e3a23; color: #4ade80; }}
  .badge.fail {{ background: #3a0e12; color: #f87171; }}
  .sub, .goal {{ margin: .3rem 0; }}
  .goal {{ background: #0f1115; border-left: 3px solid #3b82f6; padding: .6rem .8rem; border-radius: 4px; }}
  ul.staged {{ margin: .3rem 0; padding-left: 1.2rem; }}
  table {{ width: 100%; border-collapse: collapse; font-size: .85rem; }}
  th, td {{ text-align: left; padding: .4rem .5rem; border-bottom: 1px solid #262b33; vertical-align: top; }}
  th {{ color: #9aa0a6; font-weight: 600; }}
  code {{ background: #0f1115; padding: .1rem .3rem; border-radius: 4px; font-size: .82em;
          word-break: break-word; }}
  tr.okrow td:nth-child(3) {{ color: #4ade80; }}
  tr.err td:nth-child(3) {{ color: #f87171; }}
  .verdict {{ margin-top: 1rem; }}
  .muted {{ color: #6b7280; font-size: .85rem; }}
  footer {{ color: #6b7280; font-size: .8rem; margin-top: 2rem; }}
</style></head>
<body>
  <h1>M3 — <code>submit_task</code> / <code>assign_task</code> live verification</h1>
  <p class="lead">A real manager (gpt deployment) reacting to a broken subtree. These reactive tools are
  withheld by the structural guard when work is complete, so each probe stages a genuine problem and runs
  one live manager beat against it, then checks the ledger actually changed.</p>
  <div class="overall {overall_cls}">{overall}</div>
  <p class="lead"><strong>Scenario:</strong> {esc(goal_headline)}</p>
  {"".join(cards)}
  <footer>Generated by examples/m3_submit_assign_verify.py · chorus M3 Slice 2</footer>
</body></html>"""


def main() -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        _log("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    base = Path(tempfile.mkdtemp(prefix="chorus-verify-"))
    os.chdir(base)
    seed = base / "seed"
    _seed_repo(seed)

    ledger = Ledger.open(
        os.environ.get("CHORUS_LEDGER_DSN", "postgresql://localhost/chorus"),
        company_id=_EXAMPLE_COMPANY,
    )
    try:
        registry = RoleRegistry.from_plugins(default_roles())
        factory = EmployeeHarnessFactory(
            api_key=api_key,
            base_url=base_url,
            deployment=deployment,
            company_id="acme",
            roles=registry,
            pricing=default_pricing_from_env(),
            seed=seed,
            work_root=base / "work",
            ledger=ledger,
        )
        ledger.employees.create(Employee(id="moe", name="Moe", role="manager"))
        ledger.employees.create(Employee(id="ada", name="Ada", role="engineer", reports_to="moe"))
        ledger.employees.create(Employee(id="bob", name="Bob", role="engineer", reports_to="moe"))
        svc = CapabilityService(ledger)

        # ── Probe SUBMIT ─────────────────────────────────────────────────────────────────────────
        big_goal = (
            "Build a Python text-utilities library with four functions: slugify, shout, "
            "snake_case, and truncate — each in its own module with a unit test."
        )
        ledger.tasks.submit(
            Task(id="lib", intent=big_goal, status=TaskStatus.BLOCKED, assignee_employee_id="moe")
        )
        svc.decompose(
            parent_id="lib",
            revision="lib_kick",
            children=[
                ChildPlan(label="slugify", intent="implement slugify + test", assignee="ada"),
                ChildPlan(label="shout", intent="implement shout + test", assignee="bob"),
                ChildPlan(label="snake_case", intent="implement snake_case + test", assignee="ada"),
                ChildPlan(label="truncate", intent="implement truncate + test", assignee="bob"),
            ],
        )
        kids = {c.origin_fingerprint: c.id for c in ledger.tasks.children("lib")}
        for label in ("slugify", "shout", "snake_case"):
            _mark_done_passing(ledger, kids[label], by="ada" if label != "shout" else "bob")
        ledger.tasks.set_status(kids["truncate"], TaskStatus.CANCELLED)  # bob couldn't finish it
        submit_res = asyncio.run(
            _run_probe(
                factory,
                ledger,
                name="Probe SUBMIT — patch a cancelled deliverable",
                tool_under_test="submit_task",
                parent_id="lib",
                goal=big_goal,
                stage=[
                    "slugify — done, DoD passed (ada)",
                    "shout — done, DoD passed (bob)",
                    "snake_case — done, DoD passed (ada)",
                    "truncate — CANCELLED: the assigned report could not finish it",
                ],
            )
        )
        _verify_submit(submit_res, ledger, "lib")
        _log(f"  ⇒ {submit_res.verdict_reason}")

        # ── Probe ASSIGN ─────────────────────────────────────────────────────────────────────────
        goal2 = (
            "Build a config loader: a parser module and a validator module, each with a test. "
            "Your report ada is stuck on the existing validator child task and cannot finish it — "
            "route that existing task to your other report, bob."
        )
        ledger.tasks.submit(
            Task(id="cfg", intent=goal2, status=TaskStatus.BLOCKED, assignee_employee_id="moe")
        )
        svc.decompose(
            parent_id="cfg",
            revision="cfg_kick",
            children=[
                ChildPlan(label="parser", intent="implement parser + test", assignee="ada"),
                ChildPlan(label="validator", intent="implement validator + test", assignee="ada"),
            ],
        )
        kids2 = {c.origin_fingerprint: c.id for c in ledger.tasks.children("cfg")}
        _mark_done_passing(ledger, kids2["parser"], by="ada")
        ledger.tasks.set_status(kids2["validator"], TaskStatus.BLOCKED)  # ada stuck, still open
        assign_res = asyncio.run(
            _run_probe(
                factory,
                ledger,
                name="Probe ASSIGN — reroute a stuck child",
                tool_under_test="assign_task",
                parent_id="cfg",
                goal=goal2,
                stage=[
                    "parser — done, DoD passed (ada)",
                    "validator — BLOCKED, still assigned to ada (the report is stuck)",
                ],
            )
        )
        _verify_assign(assign_res, ledger, "cfg", child_id=kids2["validator"])
        _log(f"  ⇒ {assign_res.verdict_reason}")

        results = [submit_res, assign_res]
        _REPORT.parent.mkdir(parents=True, exist_ok=True)
        _REPORT.write_text(_render_html(results, goal_headline=big_goal), encoding="utf-8")
        _log(f"\n{'═' * 72}")
        for r in results:
            _log(f"  {'✅' if r.passed else '❌'} {r.name}: {r.verdict_reason}")
        _log(f"\n📄 HTML report: {_REPORT}")
        return 0 if all(r.passed for r in results) else 1
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
