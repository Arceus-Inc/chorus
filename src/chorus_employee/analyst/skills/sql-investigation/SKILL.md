---
name: sql-investigation
description: How to investigate a question against a SQL data warehouse correctly and efficiently.
when_to_use: Use when the data lives in a SQL warehouse (warehouse_query) and the question needs aggregation, grouping, ranking, or window calculations across tables.
---

# SQL Investigation

`warehouse_query` runs read-only SQL against the local warehouse. Use SQL for what SQL is good at
(grouping, joining, ranking, windows) and the notebook for what it is good at (stats, modelling,
plotting).

## Steps

1. **Discover the schema.** `SELECT name FROM sqlite_master WHERE type='table'` to list tables, then
   `PRAGMA table_info(<table>)` for each table's columns and types. Never assume column names.
2. **Sanity-check the grain.** `SELECT COUNT(*) FROM <table>` and a `SELECT * ... LIMIT 5` so you know
   what one row represents (the grain) before you aggregate.
3. **Aggregate at the grain you need.** Use `GROUP BY` for per-category totals, `ORDER BY ... LIMIT`
   for top-N, and window functions (`LAG`/`LEAD`/`SUM() OVER (...)`) for period-over-period change and
   running totals.
4. **Validate.** Cross-check a SQL aggregate against a quick recomputation in `notebook_run`
   (`pd.read_sql_query`) when the result is load-bearing for a conclusion.

## Rules

- The tool is read-only — never attempt INSERT/UPDATE/DELETE; compute derived values in SQL or the
  notebook, do not write back.
- Beware text-sorted "months": order by an explicit month index, not the string, when sequence matters.
- Quote the exact SQL you used in your findings so the result is reproducible.
