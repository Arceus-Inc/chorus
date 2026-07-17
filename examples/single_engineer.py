"""M1 — one engineer, full vertical (spec 11 build plan, README roadmap).

A single ``Employee`` takes a task, runs it via dream, has its DoD generated at
intake and verified by the evaluator, then lands the outcome (PR → CI → repair →
merge). This proves the dream↔chorus seam and outcome-landing end to end.

This is a *shape* example against the scaffold — the facade methods are stubbed
(they raise ``NotImplementedError``) until M1 lands.
"""

from __future__ import annotations

import asyncio

import dream  # type: ignore[import-not-found]

from chorus import Chorus


async def main() -> None:
    c = Chorus.build(
        dsn="./chorus.db",
        org_repo="./org",
        memory_repo="./mem",
        dream=dream,
    )
    c.hire(name="alice", role="engineer")
    c.submit("Build the login page", assignee="alice")
    await c.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
