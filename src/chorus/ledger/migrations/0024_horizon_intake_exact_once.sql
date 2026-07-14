-- Migration 0024 - make Horizon intake fingerprints exact-once at the database boundary.
-- The root delegation transaction creates Task, Team, contract, membership, wake, and audits together;
-- this partial unique index chooses one winning root when callers race on the same strategy request.

CREATE UNIQUE INDEX task_horizon_intake_fingerprint_uq
    ON task(origin_kind, origin_fingerprint)
    WHERE origin_kind = 'horizon_intake';