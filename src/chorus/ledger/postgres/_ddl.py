"""Translate the declarative ledger schema into Postgres-native DDL (spec 12 §6, §8).

The declarative ``chorus/ledger/schema/*.sql`` files are the single source of truth for the ledger's
*shape* (tables, columns, constraints, indexes). This module translates that shape into **native
Postgres types** — never lowest-common-denominator text:

- entity ids → ``uuid``           (chorus mints canonical uuidv7 text; PG enforces the shape)
- ``*_at`` timestamps → ``timestamptz``
- JSON documents → ``jsonb``
- flags → ``boolean``
- cents/tokens/amounts → ``bigint``; ``REAL`` → ``double precision``

The per-column decisions are explicit data below — auditable, and guarded by tests. Columns stay
``text`` when their content is *not* a chorus-minted entity id: polymorphic refs (``origin_id``,
``subject_id``, ``scope_id``), external principals (``*_user_id`` — e.g. ``"operator"``), semantic
system-principal ids (``"system-verifier"``), and symbolic refs (``employee_ref``, ``routine_key``).

Deriving the DDL at open() time (instead of a checked-in parallel file) makes drift between the two
dialects impossible: there is one schema, two renderings.
"""

from __future__ import annotations

import re
from importlib.resources import files

# --- the explicit type decisions -------------------------------------------------------------

# Entity-id PKs that are NOT uuids: semantic, human-authored ids.
_TEXT_ID_TABLES = {"system_principal"}

# Loose entity-id columns (no inline REFERENCES clause to derive them from). Everything here holds
# a chorus-minted id and becomes uuid.
_EXTRA_UUID_COLUMNS: set[tuple[str, str]] = {
    ("task", "checkout_run_id"),
    ("task", "execution_run_id"),
    ("task", "created_by_employee_id"),
    ("decision_record", "superseded_by"),
    ("routine_run", "coalesced_into_run_id"),
    ("run", "wake_id"),
    ("staffing_request", "workforce_plan_id"),
    ("wake", "task_id"),
    ("workforce_plan_employee", "plan_id"),
    ("workforce_plan_management_grant", "plan_id"),
}

# JSON document columns — exactly the set the repos serialise with dumps()/loads().
_JSONB_COLUMNS: set[tuple[str, str]] = {
    ("activity", "payload"),
    ("artifact", "resource_ref"),
    ("artifact_revision", "resource_ref"),
    ("decision_record", "rejected_alternatives"),
    ("decomposition_claim", "requested_children"),
    ("decomposition_claim", "child_task_ids"),
    ("dod", "spec"),
    ("dod", "verdict"),
    ("dod", "proposed_revision"),
    ("management_profile", "allowed_professions"),
    ("recovery_action", "evidence"),
    ("recovery_action", "wake_policy"),
    ("recovery_action", "monitor_policy"),
    ("routine", "env"),
    ("routine_revision", "env"),
    ("run", "outcome"),
    ("run", "usage"),
    ("task", "trust_boundary"),
    ("wake", "payload"),
    ("workforce_plan", "source_goal_ids"),
    ("workforce_plan_employee", "responsibilities"),
    ("workforce_plan_management_grant", "allowed_professions"),
}

# INTEGER flags with boolean semantics (repos bind/read Python bools).
_BOOLEAN_COLUMNS: set[tuple[str, str]] = {
    ("artifact", "is_primary"),
    ("budget_policy", "hard_stop_enabled"),
    ("delegation_contract", "can_subdelegate"),
    ("management_profile", "active"),
    ("management_profile", "can_lead"),
    ("management_profile", "can_subdelegate"),
    ("team_member", "can_subdelegate"),
    ("workforce_plan_management_grant", "can_lead"),
    ("workforce_plan_management_grant", "can_subdelegate"),
}

# INTEGER money/usage counters that must not wrap at 2^31.
_BIGINT_MARKERS = ("cents", "tokens", "amount")

_COLUMN_LINE = re.compile(r"^(\s*)(\w+)(\s+)(TEXT|INTEGER|REAL)\b(.*)$")
_COLUMN_LINE_ANY = re.compile(r"^(\s*)(\w+)\s+\w")
_CREATE_TABLE = re.compile(r"CREATE TABLE (\w+)\s*\(", re.I)
_REFERENCES = re.compile(r"REFERENCES\s+(\w+)\s*\(", re.I)
_INLINE_REFERENCE = re.compile(r"\s*REFERENCES\s+(\w+)\s*\(\s*(\w+)\s*\)", re.I)


def _split_statements(sql: str) -> list[str]:
    """``;``-separated statements with ``--`` comments stripped (same rules as the SQLite runner)."""
    without_comments = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    return [statement.strip() for statement in without_comments.split(";") if statement.strip()]


def _is_uuid_column(table: str, column: str, line_rest: str) -> bool:
    if (table, column) in _EXTRA_UUID_COLUMNS:
        return True
    if column == "id":
        return table not in _TEXT_ID_TABLES
    referenced = _REFERENCES.search(line_rest)
    if referenced is not None:
        # An FK is a uuid exactly when its target's id is a uuid.
        return referenced.group(1) not in _TEXT_ID_TABLES
    return False


def _translate_column(table: str, line: str) -> str:
    match = _COLUMN_LINE.match(line)
    if match is None:
        return line  # constraint / PRIMARY KEY / FOREIGN KEY / CHECK lines pass through
    indent, column, gap, sqlite_type, rest = match.groups()
    if sqlite_type == "TEXT":
        if _is_uuid_column(table, column, rest):
            pg_type = "uuid"
        elif column.endswith("_at") or column == "window_start":
            pg_type = "timestamptz"
        elif (table, column) in _JSONB_COLUMNS:
            pg_type = "jsonb"
        else:
            pg_type = "text"
    elif sqlite_type == "INTEGER":
        if (table, column) in _BOOLEAN_COLUMNS:
            pg_type = "boolean"
            rest = rest.replace("DEFAULT 0", "DEFAULT false").replace("DEFAULT 1", "DEFAULT true")
        elif any(marker in column for marker in _BIGINT_MARKERS):
            pg_type = "bigint"
        else:
            pg_type = "integer"
    else:  # REAL
        pg_type = "double precision"
    return f"{indent}{column}{gap}{pg_type}{rest}"


def _translate_statement(statement: str) -> str:
    table_match = _CREATE_TABLE.search(statement)
    if table_match is None:
        return statement  # CREATE [UNIQUE] INDEX — identical syntax on both engines
    table = table_match.group(1)
    lines = statement.splitlines()
    return "\n".join([lines[0], *(_translate_column(table, line) for line in lines[1:])])


def _defer_references(statement: str, table: str, targets: set[str]) -> tuple[str, list[str]]:
    """Strip inline ``REFERENCES <target>(col)`` clauses for ``targets`` out of a CREATE TABLE,
    returning the stripped statement plus equivalent ``ALTER TABLE … ADD FOREIGN KEY`` statements.

    Postgres validates FK targets at CREATE (SQLite doesn't), so a reference cycle — e.g.
    ``routine.latest_revision_id ⇄ routine_revision.routine_id`` — needs one edge added after both
    tables exist. The constraint itself is identical; only its creation time moves.
    """
    alters: list[str] = []
    lines = statement.splitlines()
    for index, line in enumerate(lines):
        column_match = _COLUMN_LINE_ANY.match(line)
        if column_match is None:
            continue
        reference = _INLINE_REFERENCE.search(line)
        if reference is None or reference.group(1) not in targets:
            continue
        column = column_match.group(2)
        target, target_column = reference.group(1), reference.group(2)
        lines[index] = line[: reference.start()] + line[reference.end() :]
        alters.append(
            f"ALTER TABLE {table} ADD FOREIGN KEY ({column}) REFERENCES {target}({target_column})"
        )
    return "\n".join(lines), alters


def _dependency_order(tables: dict[str, str]) -> tuple[list[str], dict[str, str], list[str]]:
    """(creation order, possibly-rewritten statements, deferred FK ALTERs).

    Kahn's sort over REFERENCES edges; on a cycle, the alphabetically-first stuck table has its
    unmet inline references deferred to ALTER statements and the sort continues. Deterministic.
    """
    statements = dict(tables)
    deps: dict[str, set[str]] = {}
    for name, statement in statements.items():
        targets = {match.group(1) for match in _REFERENCES.finditer(statement)}
        deps[name] = {target for target in targets if target != name and target in statements}
    ordered: list[str] = []
    deferred: list[str] = []
    remaining = dict(deps)
    while remaining:
        ready = sorted(name for name, waiting in remaining.items() if waiting <= set(ordered))
        if not ready:  # a reference cycle — break it by deferring one table's unmet FKs
            name = sorted(remaining)[0]
            unmet = remaining[name] - set(ordered)
            statements[name], alters = _defer_references(statements[name], name, unmet)
            deferred.extend(alters)
            remaining[name] -= unmet
            continue
        ordered.extend(ready)
        for name in ready:
            del remaining[name]
    return ordered, statements, deferred


# --- tenancy: company_id + FORCE RLS (the M5 shared-schema shape) ------------------------------

# The session's company travels as a transaction-/session-local GUC; the reset state on a pooled
# connection is '' (not NULL), so NULLIF guards both. NULL company -> writes violate NOT NULL and
# reads match zero rows: fail closed in both directions.
_COMPANY_GUC = "(NULLIF(current_setting('app.company_id', true), ''))::uuid"

# The company discriminator on every table. DEFAULT auto-stamps inserts from the session GUC, so
# the kernel's SQL never mentions company_id; the RLS WITH CHECK below validates it anyway.
_COMPANY_COLUMN = f"    company_id uuid NOT NULL DEFAULT {_COMPANY_GUC},"

# Unique indexes whose key is NOT anchored on a chorus-minted (globally-unique) id — without the
# company discriminator two companies would collide on equal fingerprints/keys/scopes. Indexes
# anchored on minted ids stay as-declared (global uniqueness is a superset of per-company).
# wake_queued_key_uq stays global: it is an ON CONFLICT target in repo SQL (the conflict spec must
# match the index columns on both engines) and its default key embeds an employee uuid; a crafted
# cross-company custom key fails loudly (RLS blocks the foreign DO UPDATE), never corrupts.
_COMPANY_SCOPED_UNIQUES = {
    "task_horizon_intake_fingerprint_uq",
    "routine_run_idempotency_uq",
    "budget_policy_scope_uq",
}

_UNIQUE_INDEX = re.compile(r"^(CREATE UNIQUE INDEX (\w+)\s+ON \w+)\s*\(", re.M)


def _with_company_column(statement: str) -> str:
    """Insert the company_id column as the first column of a CREATE TABLE statement."""
    lines = statement.splitlines()
    return "\n".join([lines[0], _COMPANY_COLUMN, *lines[1:]])


def _scope_unique_to_company(statement: str) -> str:
    match = _UNIQUE_INDEX.match(statement)
    if match is None or match.group(2) not in _COMPANY_SCOPED_UNIQUES:
        return statement
    return f"{match.group(1)} (company_id, {statement[match.end() :]}"


def _tenancy_statements(table: str) -> list[str]:
    """FORCE RLS + the company-isolation policy for one table.

    USING scopes reads, WITH CHECK scopes writes (a bug can't stamp a foreign company). The
    predicate is wrapped in a scalar subquery so the GUC evaluates once per statement (InitPlan),
    not per row. FORCE applies the policy to the table owner too; only superusers bypass it —
    production connects as a non-superuser role.
    """
    predicate = f"company_id = (SELECT {_COMPANY_GUC})"
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY {table}_company_isolation ON {table} "
        f"USING ({predicate}) WITH CHECK ({predicate})",
    ]


def postgres_ddl() -> list[str]:
    """Every ledger DDL statement, Postgres dialect: tenant-scoped tables in FK-dependency order,
    deferred FK constraints for reference cycles, RLS policies, then indexes."""
    schema_dir = files("chorus.ledger.schema")
    tables: dict[str, str] = {}
    indexes: list[str] = []
    for entry in sorted(schema_dir.iterdir(), key=lambda item: item.name):
        if not entry.name.endswith(".sql"):
            continue
        for statement in _split_statements(entry.read_text()):
            table_match = _CREATE_TABLE.search(statement)
            if table_match is not None:
                tables[table_match.group(1)] = _with_company_column(_translate_statement(statement))
            else:
                indexes.append(_scope_unique_to_company(_translate_statement(statement)))
    ordered, statements, deferred = _dependency_order(tables)
    tenancy = [statement for name in ordered for statement in _tenancy_statements(name)]
    return [statements[name] for name in ordered] + deferred + tenancy + indexes


__all__ = ["ledger_table_names", "postgres_ddl"]


def ledger_table_names() -> list[str]:
    """Every ledger table name, creation order — for deployments that grant a runtime role."""
    schema_dir = files("chorus.ledger.schema")
    tables: dict[str, str] = {}
    for entry in sorted(schema_dir.iterdir(), key=lambda item: item.name):
        if entry.name.endswith(".sql"):
            for statement in _split_statements(entry.read_text()):
                table_match = _CREATE_TABLE.search(statement)
                if table_match is not None:
                    tables[table_match.group(1)] = statement
    ordered, _, _ = _dependency_order(tables)
    return ordered
