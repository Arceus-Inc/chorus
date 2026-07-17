"""The declarative current episodic schema (spec 07) — one ``.sql`` file per table.

Mirrors ``chorus.ledger.schema``: the human source of truth for what the episodic store looks like
*now*. Not applied at runtime — ``migrations/`` does the applying.
``tests/memory/test_schema_parity`` asserts that applying all migrations yields exactly this schema.
"""
