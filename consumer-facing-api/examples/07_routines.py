"""07 — recurring work (routines).  OFFLINE: no model, no creds.

A routine spawns a task on a cron schedule. Create one, list them, inspect it, pause/resume its firing.
When the heartbeat runs, the tick's CRON step fires any due routine and spawns its task — so recurring
work flows through the same dispatch path as everything else.

    uv run python consumer-facing-api/examples/07_routines.py
"""

from __future__ import annotations

from _common import offline_org


def main() -> None:
    org = offline_org().chorus
    org.hire(name="eng1", role="engineer")

    view = org.routines.add(
        employee="eng1", intent_template="run the weekly dependency bump", schedule="0 9 * * 1"
    )
    print(f"added {view.id}: '{view.intent_template}'  status={view.status.value}")
    print(f"all routines: {[r.id for r in org.routines.list()]}")

    org.routines.pause(view.id)
    print(f"paused  → {org.routines.get(view.id).status.value}")
    org.routines.resume(view.id)
    print(f"resumed → {org.routines.get(view.id).status.value}")


if __name__ == "__main__":
    main()
