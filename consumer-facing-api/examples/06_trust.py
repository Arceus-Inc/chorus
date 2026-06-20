"""06 — trust presets.  OFFLINE: no model, no creds.

A task can run under a named *trust posture* that narrows what its beat may do — e.g. a low-trust task
is materialized read-only / plan-only, a standard task runs with its role's normal powers. Attach a
preset at submit, or set it later with ``org.trust.set_task``. (The narrowing is applied when the beat
materializes, so you need a live run to *see* it bite; here we just attach it.)

    uv run python consumer-facing-api/examples/06_trust.py
"""

from __future__ import annotations

from _common import offline_org

from chorus import TrustPreset


def main() -> None:
    org = offline_org().chorus
    org.hire(name="eng1", role="engineer")

    task = org.submit(
        "touch the payments module", assignee="eng1", trust_preset=TrustPreset.LOW_TRUST_REVIEW
    )
    print(f"submitted {task.id} under preset '{TrustPreset.LOW_TRUST_REVIEW.value}'")

    org.trust.set_task(task.id, preset=TrustPreset.STANDARD)
    print(f"re-set the task's posture to '{TrustPreset.STANDARD.value}'")
    print("at materialize: a low-trust beat is narrowed (read-only / plan); standard keeps the role's powers.")


if __name__ == "__main__":
    main()
