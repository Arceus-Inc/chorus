"""BudgetPolicyRepo — the spend cap (spec 01 Cluster E ``budget_policy``, spec 04)."""

from __future__ import annotations

import sqlite3

from chorus.ledger._models import BudgetPolicy, BudgetScope
from chorus.ledger.repos._base import from_iso, utcnow_iso


class BudgetPolicyRepo:
    """Create + look up ``budget_policy`` rows (one per scope/metric/window)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, policy: BudgetPolicy) -> BudgetPolicy:
        """Create a policy; the scope index makes it exact-once per scope/metric/window."""
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO budget_policy (id, scope_type, scope_id, amount, metric, warn_percent, "
            "hard_stop_enabled, window_kind, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                policy.id,
                policy.scope_type.value,
                policy.scope_id,
                policy.amount,
                policy.metric,
                policy.warn_percent,
                1 if policy.hard_stop_enabled else 0,
                policy.window_kind,
                now,
                now,
            ),
        )
        self._conn.commit()
        created = self.get(policy.id)
        assert created is not None  # just inserted in this transaction
        return created

    def get(self, policy_id: str) -> BudgetPolicy | None:
        row = self._conn.execute(
            "SELECT * FROM budget_policy WHERE id = ?", (policy_id,)
        ).fetchone()
        return _row_to_policy(row) if row is not None else None

    def set_amount(self, policy_id: str, amount: int) -> None:
        """Raise (or lower) a policy's cap — the human ``raise_budget_and_resume`` path (spec 04 §3)."""
        now = utcnow_iso()
        self._conn.execute(
            "UPDATE budget_policy SET amount = ?, updated_at = ? WHERE id = ?",
            (amount, now, policy_id),
        )
        self._conn.commit()

    def find(
        self,
        *,
        scope_type: BudgetScope,
        scope_id: str,
        metric: str = "cost_cents",
        window_kind: str = "monthly",
    ) -> BudgetPolicy | None:
        """The unique policy for a scope/metric/window, or ``None``."""
        row = self._conn.execute(
            "SELECT * FROM budget_policy WHERE scope_type = ? AND scope_id = ? AND metric = ? "
            "AND window_kind = ?",
            (scope_type.value, scope_id, metric, window_kind),
        ).fetchone()
        return _row_to_policy(row) if row is not None else None

    def by_scope(self, scope_type: BudgetScope, scope_id: str) -> list[BudgetPolicy]:
        """All policies for a scope (across metrics/windows)."""
        rows = self._conn.execute(
            "SELECT * FROM budget_policy WHERE scope_type = ? AND scope_id = ? ORDER BY metric, id",
            (scope_type.value, scope_id),
        ).fetchall()
        return [_row_to_policy(row) for row in rows]


def _row_to_policy(row: sqlite3.Row) -> BudgetPolicy:
    return BudgetPolicy(
        id=row["id"],
        scope_type=BudgetScope(row["scope_type"]),
        scope_id=row["scope_id"],
        amount=row["amount"],
        metric=row["metric"],
        warn_percent=row["warn_percent"],
        hard_stop_enabled=bool(row["hard_stop_enabled"]),
        window_kind=row["window_kind"],
        created_at=from_iso(row["created_at"]),
        updated_at=from_iso(row["updated_at"]),
    )
