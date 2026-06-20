"""01 — hire, submit, watch it land.  LIVE: needs AZURE_OPENAI_* (see QUICKSTART.md).

The smallest end-to-end company. One engineer whose *role* defines the Definition of Done — a reviewed
build — so the operator never hand-writes a DoD. We single-step the heartbeat with ``tick`` + ``drain``
so the run is deterministic and reaches ``done`` in a few pulses; in production you'd ``org.start()``
and walk away (see 02).

    set -a; eval "$(grep -E '^AZURE_OPENAI_(API_KEY|BASE_URL|DEPLOYMENT)=' .env)"; set +a
    uv run python consumer-facing-api/examples/01_hire_and_submit.py
"""

from __future__ import annotations

import asyncio

from _common import git_log, have_creds, live_org

from chorus import TaskStatus

_TERMINAL = frozenset({TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.REJECTED})


async def main() -> None:
    if not have_creds():
        print("skipping (live example): set AZURE_OPENAI_* — see consumer-facing-api/QUICKSTART.md")
        return

    org = live_org(seed_files={"calc.py": "def add(a, b):\n    return a + b\n"})
    c = org.chorus
    c.hire(name="moe", role="manager")
    c.hire(name="eng1", role="engineer", reports_to="moe")
    c.hire(name="ria", role="reviewer", reports_to="moe")  # the engineer's reviewed build needs a reviewer

    task = c.submit(
        "In calc.py add subtract(a, b) returning a - b, and a test for it in test_calc.py.",
        assignee="eng1",
    )
    print(f"submitted {task.id} → eng1 (role DoD = reviewed_build)\n")

    for n in range(1, 13):
        await c.tick()
        await c.drain()
        view = c.inspect.task(task.id)
        print(f"  pulse {n}: {view.status.value}")
        if view.status in _TERMINAL:
            break

    print(f"\nfinal: {c.inspect.task(task.id).status.value}")
    print("company main:")
    print(git_log(org.company_main) or "  (nothing landed)")


if __name__ == "__main__":
    asyncio.run(main())
