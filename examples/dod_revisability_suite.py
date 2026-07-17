"""The §1 DoD-revisability suite — tighten free, loosen only with §5 sign-off, end to end.

Revisability is a pure ledger path (no model, no keys): each scenario seeds a manager-led task, calls
``revise_dod``, and — for a loosen — resolves the §5 ``loosen_dod`` gate, capturing the in-force DoD
before and after. Writes ``reports/m1-dod-revisability.html``.

    uv run python examples/dod_revisability_suite.py
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
from chorus.ledger import Ledger, Task, TaskStatus
from chorus.lifecycle import (
    NoRevision,
    RevisionAuthorityError,
    assign_task,
    revise_dod,
)
from chorus.outcomes import Verifier
from chorus.workforce import Employee

_REPORT = Path(__file__).resolve().parents[1] / "reports" / "m1-dod-revisability.html"
_NOW = datetime(2026, 6, 19, 12, 0, tzinfo=UTC)
_USER = "founder"


@dataclass
class Scenario:
    name: str
    edit: str
    actor: str
    before: str
    after: str
    note: str


def _ledger() -> Ledger:
    _bump_demo_salt()
    lg = Ledger.open(
        os.environ.get("CHORUS_LEDGER_DSN", "postgresql://localhost/chorus"),
        company_id=str(uuid.uuid4()),  # fresh org per open — slugs reset
    )
    lg.employees.create(Employee(id="moe", name="moe", role="manager"))
    lg.employees.create(Employee(id="ada", name="ada", role="engineer", reports_to="moe"))
    lg.tasks.submit(Task(id=_id("t1"), intent="ship", status=TaskStatus.IN_PROGRESS))
    assign_task(lg, _id("t1"), "ada")
    return lg


def _dod(lg: Ledger) -> str:
    verifier = lg.dod.verifier_for_task(_id("t1"))
    if verifier is None:
        return "(none)"
    steps = verifier.verification_steps()
    return steps[0].command if steps else verifier.kind.value


def _tighten() -> Scenario:
    lg = _ledger()
    lg.dod.create(_id("t1"), Verifier.command("pytest"))
    before = _dod(lg)
    revise_dod(
        lg,
        task_id=_id("t1"),
        new_verifier=Verifier.command("pytest && ruff check"),
        revised_by="moe",
    )
    after = _dod(lg)
    lg.close()
    return Scenario(
        "tighten (add a check)",
        "pytest -> pytest && ruff check",
        "manager",
        before,
        after,
        "a manager raises the bar — applied immediately, no approval.",
    )


def _loosen(decision: ApprovalDecision, label: str, note: str) -> Scenario:
    lg = _ledger()
    lg.dod.create(_id("t1"), Verifier.command("pytest && ruff check"))
    before = _dod(lg)
    outcome = revise_dod(
        lg, task_id=_id("t1"), new_verifier=Verifier.command("pytest"), revised_by="moe"
    )
    assert outcome.approval_id is not None
    GovernanceResolver(lg).resolve(
        outcome.approval_id, decision=decision, decided_by_user_id=_USER, now=_NOW
    )
    after = _dod(lg)
    lg.close()
    return Scenario(
        f"loosen ({label})",
        "pytest && ruff check -> pytest",
        "manager + sign-off",
        before,
        after,
        note,
    )


def _authority_rejected() -> Scenario:
    lg = _ledger()
    lg.dod.create(_id("t1"), Verifier.command("pytest"))
    before = _dod(lg)
    try:
        revise_dod(
            lg, task_id=_id("t1"), new_verifier=Verifier.command("echo ok"), revised_by="ada"
        )
        after = "(unexpectedly applied)"
    except RevisionAuthorityError:
        after = before  # rejected — the worker cannot touch its own gate
    lg.close()
    return Scenario(
        "worker self-revise (blocked)",
        "pytest -> echo ok",
        "engineer (the worker)",
        before,
        after,
        "a worker cannot revise the gate that verifies its own work.",
    )


def _no_change_rejected() -> Scenario:
    lg = _ledger()
    lg.dod.create(_id("t1"), Verifier.command("pytest"))
    before = _dod(lg)
    try:
        revise_dod(lg, task_id=_id("t1"), new_verifier=Verifier.command("pytest"), revised_by="moe")
        after = "(unexpectedly applied)"
    except NoRevision:
        after = before
    lg.close()
    return Scenario(
        "no-op edit (rejected)",
        "pytest -> pytest",
        "manager",
        before,
        after,
        "an identical DoD is not a revision.",
    )


def _scenarios() -> list[Scenario]:
    return [
        _tighten(),
        _loosen(
            ApprovalDecision.APPROVE,
            "approved",
            "lowering the bar needs sign-off; approved -> in force.",
        ),
        _loosen(ApprovalDecision.DENY, "denied", "denied -> the stricter DoD is kept."),
        _authority_rejected(),
        _no_change_rejected(),
    ]


def _outcome_class(before: str, after: str) -> str:
    if before == after:
        return "no"  # nothing changed (kept / rejected)
    return "ok"


def _render(scenarios: list[Scenario]) -> str:
    def esc(value: object) -> str:
        return html.escape(str(value))

    rows = "".join(
        f"""<tr>
          <td>{esc(s.name)}</td>
          <td>{esc(s.actor)}</td>
          <td><code>{esc(s.before)}</code></td>
          <td class="arrow">&rarr;</td>
          <td><code class="{_outcome_class(s.before, s.after)}">{esc(s.after)}</code></td>
          <td class="note">{esc(s.note)}</td>
        </tr>"""
        for s in scenarios
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>§1 DoD revisability — tighten free, loosen with sign-off</title><style>
body{{font-family:ui-sans-serif,system-ui,sans-serif;margin:2rem;background:#0f1115;color:#e6e8eb}}
h1{{font-size:1.4rem}} .lead{{color:#9aa0a6;max-width:78ch}}
table{{width:100%;border-collapse:collapse;margin-top:1.2rem;font-size:.9rem}}
th{{text-align:left;color:#9aa0a6;font-weight:500;font-size:.74rem;text-transform:uppercase;
letter-spacing:.05em;padding:.4rem .5rem;border-bottom:1px solid #262b33}}
td{{padding:.5rem .5rem;border-bottom:1px solid #1c2027;vertical-align:top}}
code{{background:#16191f;padding:.1rem .4rem;border-radius:4px}}
code.ok{{color:#4ade80}} code.no{{color:#f87171}}
.arrow{{color:#6b7280;text-align:center}} .note{{color:#9aa0a6;font-size:.82rem}}
.summary{{display:inline-block;margin-top:1rem;padding:.4rem .9rem;border-radius:999px;
background:#0e3a23;color:#4ade80;font-weight:700}}
</style></head><body>
<h1>§1 DoD revisability — a manager raises the bar freely; lowering it needs sign-off</h1>
<p class="lead">A task's Definition-of-Done is revisable only through a typed, audited path. A
<b>tighten</b> (adding an obligation) by the assignee's manager applies immediately; a <b>loosen</b> is
staged behind a §5 <code>loosen_dod</code> gate while the old, stricter DoD stays in force — so the gate
that verifies a worker's output can never be quietly weakened.</p>
<div class="summary">{len(scenarios)} scenarios · tighten immediate · loosen gated · all enforced</div>
<table>
<thead><tr><th>scenario</th><th>who</th><th>DoD before</th><th></th><th>DoD after</th>
<th>what it shows</th></tr></thead>
<tbody>{rows}</tbody>
</table>
<footer class="note" style="margin-top:1.2rem">examples/dod_revisability_suite.py · chorus §1 DoD
revisability (over §5 governance)</footer>
</body></html>"""


def main() -> int:
    scenarios = _scenarios()
    for s in scenarios:
        sys.stdout.write(f"{s.name:28} {s.before:22} -> {s.after}\n")
    _REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT.write_text(_render(scenarios), encoding="utf-8")
    sys.stdout.write(f"\nHTML report: {_REPORT}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
