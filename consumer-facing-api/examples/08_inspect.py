"""08 — the read model.  OFFLINE: no model, no creds.

``status()`` is the one-call company glance; ``org.inspect.*`` is the detail — a resolved task view
(assignee, liveness, blockers), the *stuck* inbox (non-terminal work with no action path), and the org
rollup. 'Working vs stuck' is answered structurally from the ledger, never guessed from timing.

    uv run python consumer-facing-api/examples/08_inspect.py
"""

from __future__ import annotations

from _common import offline_org


def main() -> None:
    org = offline_org().chorus
    org.hire(name="moe", role="manager")
    org.hire(name="eng1", role="engineer", reports_to="moe")

    a = org.submit("build the dashboard", assignee="eng1")
    b = org.submit("wire the API", assignee="eng1", depends_on=(a.id,))  # waits on `a`
    org.submit("an unowned idea")  # sits in the backlog

    s = org.status()
    print(f"status(): {len(s.employees)} employees · {s.open_tasks} open · {s.running_beats} running")

    tv = org.inspect.task(b.id)
    print(f"task {b.id}: status={tv.status.value} assignee={tv.assignee} blockers={tv.blockers}")

    print(f"stuck inbox: {[t.id for t in org.inspect.stuck()]}")

    r = org.inspect.org_report()
    print(f"org report: {r.employees} employees · {r.tasks_total} tasks · {r.completion_rate:.0%} done")


if __name__ == "__main__":
    main()
