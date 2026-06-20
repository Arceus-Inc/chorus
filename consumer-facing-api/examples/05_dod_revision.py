"""05 — revising a Definition of Done.  OFFLINE: no model, no creds.

Every task carries a DoD: the objective bar that says what 'done' means. A manager may revise it — a
*tighten* (a stricter bar) applies immediately; a *loosen* would open a governance gate (see 03) so the
relaxation is reviewed. Only the assignee's manager may revise.

    uv run python consumer-facing-api/examples/05_dod_revision.py
"""

from __future__ import annotations

from _common import offline_org

from chorus import Verifier


def main() -> None:
    org = offline_org().chorus
    org.hire(name="moe", role="manager")
    org.hire(name="eng1", role="engineer", reports_to="moe")
    task = org.submit("add the export endpoint", assignee="eng1", dod=Verifier.command("pytest -q"))
    print(f"submitted {task.id} with DoD: `pytest -q`")

    outcome = org.dod.revise(task.id, Verifier.command("pytest -q && ruff check ."), by="moe")
    print(f"moe (the manager) tightened the DoD → {type(outcome).__name__}")
    print("now `done` requires both the tests and the linter to pass.")
    print("(a *loosen* — fewer checks — would instead open a §03 approval gate.)")


if __name__ == "__main__":
    main()
