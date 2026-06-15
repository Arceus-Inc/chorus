"""Migration 0001 — the M1 core schema (spec 01 Clusters A, C, D, F).

The walking-skeleton tables: ``employee``, ``goal``, ``task``, ``run``, ``dod``, ``artifact``.
DDL is written in the SQLite ∩ Postgres intersection (spec 12): TEXT ids, TEXT timestamps,
TEXT JSON, partial-unique indexes, and a single-assignee CHECK. The two execution locks are
authoritative ``task`` columns set by a conditional-UPDATE CAS (spec 01 invariant 4) — soft
references, not FK-constrained (``task`` and ``run`` reference each other).

Immutable once shipped (spec 01 §schema-versioning): never edit; add a new migration instead.
"""

from __future__ import annotations

from chorus.ledger._migrations import Migration

MIGRATION_0001 = Migration(
    id="0001_m1_core",
    statements=(
        # --- Cluster D: employee (the Workforce) ---
        """
        CREATE TABLE employee (
            id                   TEXT PRIMARY KEY,
            name                 TEXT NOT NULL,
            role                 TEXT NOT NULL,
            reports_to           TEXT REFERENCES employee(id),
            memory_scope         TEXT NOT NULL DEFAULT 'project',
            status               TEXT NOT NULL DEFAULT 'idle',
            budget_monthly_cents INTEGER NOT NULL DEFAULT 0,
            spent_monthly_cents  INTEGER NOT NULL DEFAULT 0,
            pause_reason         TEXT,
            paused_at            TEXT,
            last_beat_at         TEXT,
            created_at           TEXT NOT NULL,
            updated_at           TEXT NOT NULL
        )
        """,
        "CREATE INDEX employee_reports_to_idx ON employee(reports_to)",
        # --- Cluster D: goal (the alignment tree) ---
        """
        CREATE TABLE goal (
            id                TEXT PRIMARY KEY,
            title             TEXT NOT NULL,
            level             TEXT NOT NULL DEFAULT 'company',
            status            TEXT NOT NULL DEFAULT 'active',
            parent_id         TEXT REFERENCES goal(id),
            owner_employee_id TEXT REFERENCES employee(id),
            created_at        TEXT NOT NULL,
            updated_at        TEXT NOT NULL
        )
        """,
        # --- Cluster A: task (the universal work unit) ---
        """
        CREATE TABLE task (
            id                    TEXT PRIMARY KEY,
            parent_id             TEXT REFERENCES task(id),
            goal_id               TEXT REFERENCES goal(id),
            intent                TEXT NOT NULL,
            status                TEXT NOT NULL DEFAULT 'backlog',
            priority              TEXT NOT NULL DEFAULT 'medium',
            assignee_employee_id  TEXT REFERENCES employee(id),
            assignee_user_id      TEXT,
            checkout_run_id       TEXT,
            execution_run_id      TEXT,
            depth                 INTEGER NOT NULL DEFAULT 0,
            request_depth         INTEGER NOT NULL DEFAULT 0,
            origin_kind           TEXT NOT NULL DEFAULT 'manual',
            origin_id             TEXT,
            origin_fingerprint    TEXT NOT NULL DEFAULT 'default',
            created_by_employee_id TEXT,
            created_by_user_id    TEXT,
            created_at            TEXT NOT NULL,
            updated_at            TEXT NOT NULL,
            started_at            TEXT,
            completed_at          TEXT,
            cancelled_at          TEXT,
            CONSTRAINT task_single_assignee
                CHECK (assignee_employee_id IS NULL OR assignee_user_id IS NULL)
        )
        """,
        "CREATE INDEX task_assignee_status_idx ON task(assignee_employee_id, status)",
        "CREATE INDEX task_parent_idx ON task(parent_id)",
        "CREATE INDEX task_goal_idx ON task(goal_id)",
        "CREATE INDEX task_status_idx ON task(status)",
        "CREATE INDEX task_origin_idx ON task(origin_kind, origin_id)",
        # exact-once partial-unique indexes — one per self-spawned kind (spec 01, deliberate)
        """
        CREATE UNIQUE INDEX task_open_routine_uq
            ON task(origin_kind, origin_id, origin_fingerprint)
            WHERE origin_kind = 'routine_execution' AND origin_id IS NOT NULL
                  AND execution_run_id IS NOT NULL
                  AND status IN ('backlog','todo','in_progress','in_review','blocked')
        """,
        """
        CREATE UNIQUE INDEX task_active_stranded_recovery_uq
            ON task(origin_kind, origin_id)
            WHERE origin_kind = 'stranded_recovery' AND origin_id IS NOT NULL
                  AND status NOT IN ('done','cancelled')
        """,
        """
        CREATE UNIQUE INDEX task_active_stale_run_eval_uq
            ON task(origin_kind, origin_id)
            WHERE origin_kind = 'stale_run_eval' AND origin_id IS NOT NULL
                  AND status NOT IN ('done','cancelled')
        """,
        """
        CREATE UNIQUE INDEX task_active_productivity_review_uq
            ON task(origin_kind, origin_id)
            WHERE origin_kind = 'productivity_review' AND origin_id IS NOT NULL
                  AND status NOT IN ('done','cancelled')
        """,
        # --- Cluster C: run (one beat — THIN; liveness is witnessed) ---
        """
        CREATE TABLE run (
            id                   TEXT PRIMARY KEY,
            employee_id          TEXT NOT NULL REFERENCES employee(id),
            task_id              TEXT NOT NULL REFERENCES task(id),
            wake_id              TEXT,
            status               TEXT NOT NULL DEFAULT 'queued',
            lease_expires_at     TEXT,
            liveness_state       TEXT,
            continuation_attempt INTEGER NOT NULL DEFAULT 0,
            outcome              TEXT NOT NULL DEFAULT '{}',
            usage                TEXT NOT NULL DEFAULT '{}',
            started_at           TEXT,
            finished_at          TEXT,
            created_at           TEXT NOT NULL
        )
        """,
        "CREATE INDEX run_employee_started_idx ON run(employee_id, started_at)",
        "CREATE INDEX run_status_lease_idx ON run(status, lease_expires_at)",
        # --- Cluster F: dod (definition-of-done + verification record, 1:1 with task) ---
        """
        CREATE TABLE dod (
            id                 TEXT PRIMARY KEY,
            task_id            TEXT NOT NULL REFERENCES task(id),
            kind               TEXT NOT NULL,
            spec               TEXT NOT NULL DEFAULT '{}',
            artifact_class     TEXT,
            revision           INTEGER NOT NULL DEFAULT 1,
            status             TEXT NOT NULL DEFAULT 'pending',
            verdict            TEXT,
            verified_by_run_id TEXT REFERENCES run(id),
            created_at         TEXT NOT NULL,
            updated_at         TEXT NOT NULL
        )
        """,
        "CREATE UNIQUE INDEX dod_task_uq ON dod(task_id)",
        "CREATE INDEX dod_kind_idx ON dod(kind)",
        "CREATE INDEX dod_status_idx ON dod(status)",
        # --- Cluster F: artifact (the landed outcome) ---
        """
        CREATE TABLE artifact (
            id            TEXT PRIMARY KEY,
            task_id       TEXT NOT NULL REFERENCES task(id),
            type          TEXT NOT NULL,
            provider      TEXT,
            external_id   TEXT,
            url           TEXT,
            review_state  TEXT,
            health_status TEXT,
            is_primary    INTEGER NOT NULL DEFAULT 0,
            resource_ref  TEXT,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        )
        """,
        "CREATE INDEX artifact_task_idx ON artifact(task_id)",
    ),
)

__all__ = ["MIGRATION_0001"]
