"""04 — budgets (token-salary caps).  OFFLINE: no model, no creds.

Every employee and the company can carry a spend cap. Budgets are a two-gate model: a *soft* gate
warns at ``warn_percent``; a *hard* gate pauses the scope when the cap is hit — no new beat starts for
a paused scope until a human ``raise_``s the cap (above observed spend) or ``dismiss_incident``s it.

A live breach needs real spend, so here we just arm the caps; the resume/dismiss verbs are shown so you
know the shape.

    uv run python consumer-facing-api/examples/04_budgets.py
"""

from __future__ import annotations

from _common import offline_org

from chorus import BudgetScope, BudgetWindow


def main() -> None:
    org = offline_org().chorus
    org.hire(name="eng1", role="engineer")

    org.budgets.set(
        BudgetScope.EMPLOYEE, "eng1", 500_00, warn_percent=80, window=BudgetWindow.MONTHLY
    )
    print("armed a $500/month cap on eng1 (warn at 80%)")
    print("on a hard breach the scope pauses; to recover:")
    print("  org.budgets.raise_(policy_id, new_amount_cents, by='cfo')   # lift the cap + resume")
    print("  org.budgets.dismiss_incident(incident_id, by='cfo')         # ack + leave it paused")


if __name__ == "__main__":
    main()
