"""02 — a team with a goal: decompose → build (concurrent | dependent) → review → integrate.

LIVE (needs AZURE_OPENAI_*), driven by ``org.start()`` — the concurrent always-on heartbeat.

The whole org in one script. The operator states a *goal* and hands it to the manager; that's it. From
there the company runs itself:

  • the **manager** decomposes the goal into child tasks (some independent, some dependent);
  • **independent** children run **concurrently** — both engineers work at once, up to
    ``Caps.max_concurrent_runs`` (watch ``running`` reach 2);
  • a **dependent** child stays ``blocked`` until its blockers finish, then runs;
  • each engineer's build is gated by the **reviewer** (its role DoD is a reviewed build);
  • the manager **integrates** the finished subtree → the goal lands ``done``.

``org.start()`` runs all of it in the background; we just poll the read model to narrate it.

    set -a; eval "$(grep -E '^AZURE_OPENAI_(API_KEY|BASE_URL|DEPLOYMENT)=' .env)"; set +a
    uv run python consumer-facing-api/examples/02_team_goal.py
"""

from __future__ import annotations

import asyncio
import time

from _common import git_log, have_creds, live_org

from chorus import Chorus, TaskStatus

_TERMINAL = frozenset({TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.REJECTED})

GOAL = (
    "Build a small math library in mathx.py, with tests in test_mathx.py. There are two INDEPENDENT "
    "pieces the engineers can do in parallel: (A) add subtract(a, b) returning a - b; (B) add "
    "multiply(a, b) returning a * b. Then there is one piece that DEPENDS on both: (C) add describe() "
    "returning a one-line string that names every operation (add, subtract, multiply). Decompose A and "
    "B as independent child tasks and C as a child that depends on both A and B."
)


def _children(c: Chorus, goal_id: str) -> tuple[object, ...]:
    """The manager's child rows, once it has decomposed (empty while it is still planning)."""
    try:
        return c.inspect.scrum_packet(goal_id).children
    except Exception:
        return ()


async def main() -> None:
    if not have_creds():
        print("skipping (live example): set AZURE_OPENAI_* — see consumer-facing-api/QUICKSTART.md")
        return

    org = live_org(seed_files={"mathx.py": "def add(a, b):\n    return a + b\n"})
    c = org.chorus
    c.hire(name="moe", role="manager")
    c.hire(name="ada", role="engineer", reports_to="moe")
    c.hire(name="bo", role="engineer", reports_to="moe")
    c.hire(name="ria", role="reviewer", reports_to="moe")

    goal = c.submit(GOAL, assignee="moe")  # to the manager — it decomposes
    print(f"goal {goal.id} → moe (manager)\nstarting the concurrent heartbeat…\n")

    c.start()  # the always-on runner — employees work in the background, concurrently
    try:
        deadline = time.monotonic() + 900.0
        while time.monotonic() < deadline:
            await asyncio.sleep(5.0)
            g = c.inspect.task(goal.id)
            running = c.status().running_beats
            kids = _children(c, goal.id)
            shown = ", ".join(f"{k.label}={k.status}" for k in kids) or "(planning)"  # type: ignore[attr-defined]
            print(f"  goal={g.status.value}  running_beats={running}  children=[{shown}]", flush=True)
            if g.status in _TERMINAL:
                break
    finally:
        await c.stop()  # signal + drain in-flight beats

    print(f"\nfinal goal: {c.inspect.task(goal.id).status.value}")
    print("company main:")
    print(git_log(org.company_main) or "  (nothing landed)")


if __name__ == "__main__":
    asyncio.run(main())
