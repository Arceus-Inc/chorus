"""Authored Postgres migrations — immutable ``NNNN_name.sql`` deltas over the frozen baseline.

Empty today: the baseline (``schema/*.sql``) subsumes all history. The first post-baseline schema
change lands here as ``0002_<name>.sql`` (the baseline occupies id ``0001``). See
``chorus.ledger._migrations`` for the applied-set rules and authoring conventions.
"""
