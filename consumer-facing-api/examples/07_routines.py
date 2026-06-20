"""07 — recurring work: routines, revisions, env.  OFFLINE: no model, no creds.

A routine spawns a task on a cron schedule. This walks the whole lifecycle on the data surface:

* **add** a routine (with a secret-ref ``env`` binding) — it starts at revision 1;
* **revise** its definition — a new head revision; the live row tracks the head;
* **restore** an earlier revision — a *new* head that copies it (history is never rewritten);
* **pause / resume** its firing;
* and the **fail-closed env guard** — an inline secret is rejected before it can ever be stored.

When the heartbeat runs, the tick's CRON step fires any due routine and spawns its task through the
same dispatch path as everything else (see 01/02 for live dispatch).

    uv run python consumer-facing-api/examples/07_routines.py
"""

from __future__ import annotations

from _common import offline_org

from chorus import InvalidIntake


def main() -> None:
    org = offline_org().chorus
    org.hire(name="moe", role="manager")
    org.hire(name="eng1", role="engineer", reports_to="moe")

    # add — env binds a secret *ref*, never a raw value; routine_key is the stable identity.
    view = org.routines.add(
        employee="eng1",
        intent_template="run the weekly dependency bump",
        schedule="0 9 * * 1",
        routine_key="weekly-dep-bump",
        env={"GITHUB_TOKEN": "ref:github_token"},
    )
    print(f"added {view.id}: '{view.intent_template}'  rev={view.latest_revision_no}")

    # revise — a new head revision; the owner (or the owner's manager) may edit.
    revised = org.routines.revise(
        view.id, by="eng1", intent_template="run the weekly dependency bump AND security audit"
    )
    print(f"revised → rev={revised.latest_revision_no}: '{revised.intent_template}'")

    # restore — roll back to revision 1 through a *new* head (history stays intact).
    restored = org.routines.restore(view.id, revision_no=1, by="eng1")
    print(f"restored rev 1 → rev={restored.latest_revision_no}: '{restored.intent_template}'")

    # pause / resume firing.
    org.routines.pause(view.id)
    print(f"paused  → {org.routines.get(view.id).status.value}")
    org.routines.resume(view.id)
    print(f"resumed → {org.routines.get(view.id).status.value}")

    # fail-closed env guard — a secret-looking key must use a ref:, never a raw value.
    try:
        org.routines.add(
            employee="eng1", intent_template="leaky", schedule="0 9 * * 1",
            env={"GITHUB_TOKEN": "ghp_a_raw_secret"},
        )
    except InvalidIntake as exc:
        print(f"rejected inline secret (fail-closed): {exc}")


if __name__ == "__main__":
    main()
