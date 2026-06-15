"""The declarative current schema (spec 01) — one ``.sql`` file per table.

This is the human source of truth for what the ledger looks like *now* (like a Rails ``schema.rb``
or a dbmate ``schema.sql`` dump), organised per table the way Arceus's ``schema/`` is. It is **not**
applied at runtime — ``migrations/`` does the applying. ``tests/ledger/test_schema_parity`` asserts
that applying all migrations yields exactly this schema, so the two can never silently diverge.
"""
