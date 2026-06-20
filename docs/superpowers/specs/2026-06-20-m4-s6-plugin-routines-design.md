# M4 S6 — Plugin-declared routines (+ S3 fail-closed env guard)

> Implements spec [13 §5](../../specs/divo/13-recurring-work.md) (plugin-declared routines) and the
> fail-closed half of §3 (env bindings). Branch `dev/m4-s6-plugin-routines` off `main` (S2 merged).

## Why

**S6** proves chorus's central claim — *the kernel is a fixed engine; an organization's behaviour is
data plugged into it*. A role plugin already adds an employee type with no scheduler/ledger/recovery
change; S6 extends that to **recurring** work: a plugin carries its own standing schedule, and a
**role-agnostic reconciler** (code that never says `pm`/`analyst`) turns those declarations into real
routines. Acceptance bar: a test imports a brand-new plugin, runs the reconciler, and a firing routine
appears — **zero diff under `src/chorus/`**. It also makes the already-merged PM/Analyst plugins
autonomous instead of inert.

**S3 guard** is the safety rail: routine `env` binds secret **refs, never values**. The kernel already
enforces "no inline secret" at beat-materialize (`assert_contained`); the guard pushes that check
**earlier — to where env is written** (add/revise/reconcile/registration), so a plaintext credential
can never even land in a routine row. The heavier allow-list resolution at materialize stays deferred
(full S3) until a routine actually consumes a secret.

## Grounding (Paperclip)

Paperclip treats routines as a **managed resource** a plugin *"provisions and re-resolves by stable
key"* (`missing|resolved|created|relinked|reset`), and keeps **provisioning separate from firing**
(`routines.ts: tickScheduledTriggers` is the heartbeat tick, not the resolver). Mapping:

- managed-resource-by-stable-key → `RoutineDeclaration.routine_key` + idempotent reconcile.
- "plugin becomes active for a scope" (Paperclip: configured for a company) → chorus: an employee of
  the role is **hired**. ⇒ **hire-time call-site**.
- Paperclip re-resolves on startup and on `company-portability.ts` import ⇒ the reconciler is a
  **standalone idempotent function** that S7 import will reuse, not logic buried in `hire`.
- We deliberately skip Paperclip's `relinked/reset` (recreating an operator-deleted routine):
  hire-time-once never fights the operator.

## Decisions (locked)

| Question | Decision |
|---|---|
| Reconcile call-site | **Hire-time** — `Chorus.hire` reconciles the role's declared routines for the new employee (idempotent ⇒ restart-safe). |
| What ships | **PM ships a real weekly routine**; the "no kernel change" bar is proven by a *separate throwaway test plugin*. Analyst stays declaration-free. |
| Env guard rule | **Key-heuristic**, reusing the kernel's existing `assert_contained` markers via one shared `assert_no_inline_secrets` predicate. |
| Declaration shape | A `tuple[RoutineDeclaration, ...]` **field on `RolePlugin`** (frozen dataclass; the registry already holds plugins) — not a free method. |
| Schedule change on an existing routine | **Deferred to S7 re-resolution** (hire-time mostly *creates*; revisions cover intent/policies/env, not the cron edge). Documented, not dropped. |

## Components

1. **`assert_no_inline_secrets(env: Mapping[str, str]) -> None`** (`chorus/trust/_containment.py`) —
   extracted predicate (reuses `_SECRET_MARKERS` / `_REF_PREFIX`): a secret-looking key whose value is
   not a `ref:` handle raises. `assert_contained` is refactored to call it. Routine paths call it too,
   raising `InvalidIntake` at the boundary.
2. **`RoutineDeclaration`** (`chorus/cron/_declaration.py`) — frozen dataclass per §5.1: `routine_key`,
   `intent_template`, `schedule`, `target`, `concurrency`, `catch_up`, `env`.
3. **`RolePlugin.declared_routines: tuple[RoutineDeclaration, ...] = ()`** — new optional field; default
   empty ⇒ existing plugins unchanged. `RoleRegistry._validate` validates each declaration fail-closed
   (valid cron + `assert_no_inline_secrets`).
4. **`add_routine(ledger, *, employee_id, intent_template, schedule, …) -> Routine`**
   (`chorus/cron/_add.py`) — the create path extracted from `RoutinesFacade.add`: env-guard → `parse_cron`
   → routine + rev1 + trigger. Facade resolves slug then delegates; the reconciler calls it directly.
   `RoutineRepo.by_key(employee_id, routine_key)` backs lookups (S2 unique index).
5. **`reconcile_declared_routines(ledger, *, employee_id, declarations) -> ReconcileResult`**
   (`chorus/cron/_reconcile.py`) — role-agnostic: absent → `add_routine` (*created*); present + changed
   → `revise_routine` (*revised*, `NoRoutineRevision` ⇒ *unchanged*). Returns `(created, revised,
   unchanged)`.
6. **Hire wiring** — `Chorus.hire` looks up the role's plugin in `self._roles` and calls the reconciler
   for the new employee. Only kernel touch; role-agnostic.
7. **PM declaration** — `pm_plugin()` ships a weekly planning-review `RoutineDeclaration`.

**Migration:** none — S2 added `routine_key` + the `(employee_id, routine_key)` unique index. Zero
schema change is itself part of the proof.

## Testing

- **Unit:** env-guard heuristic (secret key inline → reject; `ref:` ok; non-secret value ok);
  `RoutineDeclaration`; `add_routine` seeds rev1 + trigger; `reconcile` create / idempotent-no-op /
  revise-on-change; registry rejects inline-secret + bad-cron declarations.
- **Acceptance bar:** a fresh *test-only* plugin (e.g. a `widget` role) declaring a routine → register
  + hire + reconcile → routine + trigger exist and are due — exercising only the fixture + the public
  reconciler (no `src/chorus` edit).
- **Integration:** hire a PM → its weekly routine exists (`latest_revision_no=1`, `routine_key` set);
  re-hire is idempotent.

## Slices (TDD)

A env-guard · B declaration + plugin field + registry validation · C `add_routine` extract +
`by_key` · D reconciler · E hire wiring + PM declaration + acceptance · F gate + commit.
