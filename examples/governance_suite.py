"""The §5 governance suite — all four governed actions + revision_requested, end to end.

Governance is a pure ledger mutation (no model), so this runs deterministically with no API keys: each
scenario opens a real gate over a real :class:`Ledger` and resolves it through the live
:class:`GovernanceResolver`, capturing the subject's status before and after. Writes
``reports/m3-governance.html``.

    uv run python examples/governance_suite.py
"""

from __future__ import annotations

from chorus.ids import derive_id

_demo_salt = {"n": 0}  # bumped per ledger open — scenario reruns in one database can't collide


def _bump_demo_salt() -> None:
    _demo_salt["n"] += 1


def _id(name: str) -> str:
    """A readable per-scenario entity id (deterministic within a scenario, unique across them)."""
    return derive_id("demo", str(_demo_salt["n"]), name)


import os
import uuid

_EXAMPLE_COMPANY = str(uuid.uuid5(uuid.NAMESPACE_URL, "chorus-example"))  # one stable demo org

import html
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from chorus.governance import ApprovalDecision, GovernanceResolver
from chorus.ledger import (
    ApprovalAction,
    ApprovalGate,
    ApprovalSubjectKind,
    Artifact,
    ArtifactType,
    Ledger,
    Task,
    TaskStatus,
)
from chorus.lifecycle import CapabilityService, ChildPlan, assign_task
from chorus.workforce import Employee, EmployeeStatus, LedgerWorkforce

_REPORT = Path(__file__).resolve().parents[1] / "reports" / "m3-governance.html"
_NOW = datetime(2026, 6, 19, 12, 0, tzinfo=UTC)
_USER = "founder"


@dataclass
class Scenario:
    action: str
    decision: str
    subject: str
    before: str
    after: str
    note: str


def _ledger() -> Ledger:
    _bump_demo_salt()
    return Ledger.open(
        os.environ.get("CHORUS_LEDGER_DSN", "postgresql://localhost/chorus"),
        company_id=str(uuid.uuid4()),  # fresh org per scenario — slugs reset
    )


def _hire(decision: ApprovalDecision) -> Scenario:
    lg = _ledger()
    LedgerWorkforce(lg.employees).hire(name="Ada", role="engineer", status=EmployeeStatus.PENDING)
    gate = GovernanceResolver(lg).open(
        action=ApprovalAction.HIRE_EMPLOYEE,
        subject_kind=ApprovalSubjectKind.EMPLOYEE,
        subject_id="ada",
        reason="hire Ada",
    )
    before = lg.employees.get("ada").status.value  # type: ignore[union-attr]
    out = GovernanceResolver(lg).resolve(
        gate.id, decision=decision, decided_by_user_id=_USER, now=_NOW
    )
    lg.close()
    return Scenario(
        "hire_employee",
        decision.value,
        "employee ada",
        before,
        out.subject_status,
        "approve activates the pending hire; deny terminates it.",
    )


def _plan(decision: ApprovalDecision) -> Scenario:
    lg = _ledger()
    lg.employees.create(Employee(id="moe", name="moe", role="manager"))
    for emp in ("ada", "bob"):
        lg.employees.create(Employee(id=emp, name=emp, role="engineer", reports_to="moe"))
    lg.tasks.submit(Task(id=_id("G"), intent="ship", status=TaskStatus.TODO))
    assign_task(lg, _id("G"), "moe")
    CapabilityService(lg).decompose(
        parent_id=_id("G"),
        revision=_id("r1"),
        children=[
            ChildPlan(label="api", intent="api", assignee="ada"),
            ChildPlan(label="ui", intent="ui", assignee="bob"),
        ],
    )
    gate = GovernanceResolver(lg).open_plan_gate(_id("G"), reason="sign off the plan")
    before = "children blocked"
    GovernanceResolver(lg).resolve(gate.id, decision=decision, decided_by_user_id=_USER, now=_NOW)
    after = ", ".join(
        f"{c.origin_fingerprint}={c.status.value}" for c in lg.tasks.children(_id("G"))
    )
    lg.close()
    return Scenario(
        "plan_approval",
        decision.value,
        "task G plan",
        before,
        after,
        "approve releases the children; revise cancels them and re-plans.",
    )


def _board(decision: ApprovalDecision) -> Scenario:
    lg = _ledger()
    lg.employees.create(Employee(id="ada", name="ada", role="engineer"))
    lg.tasks.submit(
        Task(id=_id("t1"), intent="pr", status=TaskStatus.DONE, assignee_employee_id="ada")
    )
    lg.artifacts.create(Artifact(id=_id("ar1"), task_id=_id("t1"), type=ArtifactType.PR))
    gate = GovernanceResolver(lg).open(
        action=ApprovalAction.BOARD_APPROVAL,
        subject_kind=ApprovalSubjectKind.ARTIFACT,
        subject_id=_id("ar1"),
        reason="promote the PR",
    )
    out = GovernanceResolver(lg).resolve(
        gate.id, decision=decision, decided_by_user_id=_USER, now=_NOW
    )
    lg.close()
    return Scenario(
        "board_approval",
        decision.value,
        "artifact ar1 (pr)",
        "landed",
        out.subject_status,
        "approve promotes the deliverable to the board.",
    )


def _task_gate(decision: ApprovalDecision) -> Scenario:
    lg = _ledger()
    lg.employees.create(Employee(id="ada", name="ada", role="engineer"))
    lg.tasks.submit(
        Task(id=_id("t1"), intent="ship", status=TaskStatus.IN_PROGRESS, assignee_employee_id="ada")
    )
    gate = GovernanceResolver(lg).open_task_gate(
        _id("t1"), gate_kind=ApprovalGate.ACCEPTANCE, reason="sign off"
    )
    before = lg.tasks.get(_id("t1")).status.value  # type: ignore[union-attr]
    out = GovernanceResolver(lg).resolve(
        gate.id, decision=decision, decided_by_user_id=_USER, now=_NOW
    )
    lg.close()
    return Scenario(
        "task_gate",
        decision.value,
        "task t1 (acceptance)",
        before,
        out.subject_status,
        "the human acceptance gate; revise sends the work back to todo.",
    )


def _scenarios() -> list[Scenario]:
    return [
        _hire(ApprovalDecision.APPROVE),
        _hire(ApprovalDecision.DENY),
        _plan(ApprovalDecision.APPROVE),
        _plan(ApprovalDecision.REQUEST_REVISION),
        _board(ApprovalDecision.APPROVE),
        _task_gate(ApprovalDecision.APPROVE),
        _task_gate(ApprovalDecision.REQUEST_REVISION),
    ]


def _decision_class(decision: str) -> str:
    return {"approve": "ok", "deny": "no", "request_revision": "rev"}.get(decision, "muted")


def _render(scenarios: list[Scenario]) -> str:
    def esc(value: object) -> str:
        return html.escape(str(value))

    rows = "".join(
        f"""<tr>
          <td><code>{esc(s.action)}</code></td>
          <td><span class="pill {_decision_class(s.decision)}">{esc(s.decision)}</span></td>
          <td>{esc(s.subject)}</td>
          <td class="muted">{esc(s.before)}</td>
          <td class="arrow">&rarr;</td>
          <td><b>{esc(s.after)}</b></td>
          <td class="note">{esc(s.note)}</td>
        </tr>"""
        for s in scenarios
    )
    actions = sorted({s.action for s in scenarios})
    decisions = sorted({s.decision for s in scenarios})
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>§5 governance — the governed-action queue</title><style>
body{{font-family:ui-sans-serif,system-ui,sans-serif;margin:2rem;background:#0f1115;color:#e6e8eb}}
h1{{font-size:1.4rem}} .lead{{color:#9aa0a6;max-width:76ch}}
table{{width:100%;border-collapse:collapse;margin-top:1.2rem;font-size:.9rem}}
th{{text-align:left;color:#9aa0a6;font-weight:500;font-size:.74rem;text-transform:uppercase;
letter-spacing:.05em;padding:.4rem .5rem;border-bottom:1px solid #262b33}}
td{{padding:.5rem .5rem;border-bottom:1px solid #1c2027;vertical-align:top}}
code{{background:#16191f;padding:.1rem .4rem;border-radius:4px}}
.pill{{padding:.1rem .55rem;border-radius:999px;font-weight:600;font-size:.78rem}}
.pill.ok{{background:#0e3a23;color:#4ade80}} .pill.no{{background:#3a0e12;color:#f87171}}
.pill.rev{{background:#3a300e;color:#fbbf24}}
.muted{{color:#6b7280}} .arrow{{color:#6b7280;text-align:center}} .note{{color:#9aa0a6;font-size:.82rem}}
.summary{{display:inline-block;margin-top:1rem;padding:.4rem .9rem;border-radius:999px;
background:#0e3a23;color:#4ade80;font-weight:700}}
</style></head><body>
<h1>§5 governance — the generalized governed-action queue</h1>
<p class="lead">One resolver dispatches every governed action to its handler over one atomic, audited
ledger transaction. Each row is a real gate opened and resolved through the live
<code>GovernanceResolver</code> — the subject's status before and after the human decision.</p>
<div class="summary">{len(scenarios)} gates · {len(actions)} actions · {len(decisions)} decisions ·
all resolved</div>
<table>
<thead><tr><th>action</th><th>decision</th><th>subject</th><th>before</th><th></th><th>after</th>
<th>what it does</th></tr></thead>
<tbody>{rows}</tbody>
</table>
<p class="note" style="margin-top:1.4rem">actions: {esc(", ".join(actions))} · the empty default
policy gates nothing, so every existing run is unchanged until an org opts in.</p>
<footer class="note">examples/governance_suite.py · chorus §5 governance (Approach A)</footer>
</body></html>"""


def main() -> int:
    scenarios = _scenarios()
    for s in scenarios:
        sys.stdout.write(f"{s.action:15} {s.decision:18} {s.subject:22} {s.before} -> {s.after}\n")
    _REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT.write_text(_render(scenarios), encoding="utf-8")
    sys.stdout.write(f"\nHTML report: {_REPORT}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
