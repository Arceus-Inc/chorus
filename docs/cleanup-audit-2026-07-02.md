# Chorus Clean-Code Audit — 2026-07-02

Deep scan of `src/` against *Clean Code in Python* (Anaya, 2nd ed.) + the agent-harness-construction
checklist. Six parallel reviewers, one per subsystem. Codes (A1–J7) refer to the Anaya checklist.

## Headline

**The repo is mechanically very clean.** Across ~23k lines: 92 `@dataclass(frozen=True)` vs 1 plain,
zero mutable default args, zero bare `except:`, zero `except: pass` swallows, only 6 `# type: ignore`,
no commented-out code, no `print()` in library code, Protocol-based DI at every seam, domain models
carry zero storage imports (clean hexagonal boundary). Every reviewer independently called their slice
"unusually disciplined."

**The debt is structural and concentrated**, in four buckets:
1. A few genuine god-files/methods.
2. A cluster of broad `except Exception` seams that launder real bugs into "engine faults" or swallow silently.
3. Two provider-integration robustness/leak bugs in `chorus_tools`.
4. Repeated boilerplate (id-minting, row-mappers, backend-name strings, capability-tool dispatch).

---

## TIER 1 — Fix first (correctness / silent-failure / security-adjacent)

### 1.1 Provider error bodies leak into model-visible exceptions — `chorus_tools` (C7)
- `delivery/_resend_email.py:43`, `delivery/_strapi_publish.py:43`, `cms/_strapi.py:61,70` wrap
  `response.text[:200]` into `DeliveryError`/`CmsError`, which `_tool.py:123 _failed(str(exc))` renders
  verbatim into the model-visible `ToolResult`. Resend/Strapi 4xx bodies can echo `from`/`to` addresses
  and field detail.
- **Fix:** one `_raise_for_status(response, prefix, ErrType)` helper that logs the raw body server-side and
  surfaces only `f"{prefix} failed: HTTP {status_code}"`. This single helper also de-dupes the 5× copied
  `status_code // 100 != 2` check.

### 1.2 Unwrapped `response.json()` escapes the tool's `except` — `chorus_tools` (C2)
- `delivery/_resend_email.py:49`, `cms/_strapi.py:62-66,87`, `delivery/_strapi_publish.py:61`: a non-JSON
  2xx body raises `json.JSONDecodeError`, which is **not** a `DeliveryError`/`CmsError`, so the tool's
  `except DeliveryError` (`_tool.py:122`) misses it → opaque tool crash with no recovery contract.
- **Fix:** guard `.json()` and re-raise the domain error `from exc`. Also wrap
  `_decompose.py:61 model_validate` in the same `try/except ValidationError` guard every other tool uses.

### 1.3 Broad `except Exception` launders real bugs into "engine faults" (C3/C1)
Defensible *loops* that must not crash, but as written they classify programming bugs (AttributeError in
trace/pricing mapping, DoD resolution, `_write_integrate_packet`) as retryable engine faults and strand them:
- `adapters/dream_beat.py:256`, `heartbeat/_scheduler.py:626` and `:898`.
- **Fix:** wrap only the `run_task`/`run_role` await in the broad catch; let surrounding pure-ledger calls
  raise. Narrow to the dream error contract (`code`/`phase`) you already key on, and log at error level
  before classifying so real defects surface instead of becoming ops noise.

### 1.4 Silent swallows with zero logging (C1)
- `chorus_cli/_commands.py:124` `with suppress(Exception): beats.run_tick()` — a permanently-broken tick
  runner spins silently at 0.5s forever. Count consecutive failures; surface/deactivate after N.
- `chorus_cli/_commands.py:177-180` `_maybe_bootstrap_employee` `except Exception: return` — demo silently
  starts with an empty org. Narrow + report.
- `chorus_cli/_repl.py:49` — the CLI's only backstop discards the traceback (shows a cryptic one-liner,
  logs nothing). Keep the friendly line, but `logging.exception` the full trace to a file.
- `observability/_bus.py:89` `except Exception: continue` — FanoutBus isolation is correct *intent* but a
  dead sink is invisible forever. Log at debug/warn.

### 1.5 `sqlite3.IntegrityError` as control flow (C4)
- `chorus_cli/_commands.py:1341-1343, 1443-1445` rely on a DB integrity error to detect "already has a
  gate/DoD" — any *other* integrity violation is misreported. Check existence explicitly (as `_submit`
  already does at `:794`); reserve the exception for the true race.

### 1.6 Stringly-typed git-conflict detection + silent swallow — `workspace/_worktree.py` (B11/C3)
- `:141-147, 226-247` branch on `"CONFLICT" in (stdout+stderr)` (locale/version fragile); `sync_to_main`
  swallows any non-conflict git failure as a bare `False`.
- **Fix:** detect conflicts structurally (returncode + `git ls-files -u`); log the swallowed stderr.

---

## TIER 2 — Structural god-files (biggest maintainability wins)

### 2.1 `chorus_cli/_commands.py` — 1684 lines, ~35 handlers (C19) — the #1 target
Dispatch is already a clean **registry** (low-risk split). Break into `chorus_cli/commands/` where each
module self-registers into the shared `REGISTRY`; `_commands.py` becomes a one-line shim re-exporting it.
Proposed modules: `_shared.py` (fmt/preview/parse helpers + a new `require_args`), `_views.py` (extracted
renderer layer), `heartbeat.py`, `workforce.py`, `company.py`, `tasks.py`, `coordination.py`, `kernel.py`,
`accounting.py`, `budgets.py`, `governance.py`, `dod.py`, `routines.py`. Do the `_views.py` extraction +
`require_args` helper *in the same pass* — they resolve the presentation-tangling (C14), the ~25 copied
arity-check blocks (B11), and the handler-testability smell (H1) at once.

### 2.2 `heartbeat/_scheduler.py` — 1000-line `Scheduler` god-class (C19/D1)
Six reasons to change in one class. Split into collaborators the `tick` composes:
- **BeatExecutor** — `run_beat`, `_run_beat_with_retry`, `_capture_memory`, `_record_cost`.
- **ReviewCoordinator** — `_run_review`, `_reviewed_build_passes`, `_route_block`, `_resolve_reviewer`,
  `_review_runner`, `_review_intent`, `_open_review_recovery`.
- **RepairLadder** — `_climb_repair_ladder`, `_strand_errored`, `_apply_monitor_recovery`.
- `tick`/`_dispatch_beat`/`sort_key` stay as the kernel.
Also: the ~60-line dispatch gauntlet (`:354-412`) recomputes `task_id` 4×; extract each of the 7 gates to a
predicate returning a verdict enum and compute `task_id` once (C14/D2).

### 2.3 `ledger/_models.py` — 814 lines, ~30 enums + ~20 dataclasses (C19)
Split into a `_models/` package along the 7 clusters the file already labels: `work.py`, `scheduling.py`,
`outcomes.py`, `budget.py`, `governance.py`, `org.py`. Re-export from `__init__.py` so every
`from chorus.ledger._models import X` site is untouched.

### 2.4 `chorus_harness/_factory.py` — `materialize` god-method (D1) + role-content coupling
- `materialize` (`:381-524`, ~143 lines) has 7 responsibilities. Extract `_resolve_config`,
  `_prepare_worktree`, `_build_registry`; `build_harness` stays the thin assembly.
- **Role knowledge leaking into the generic factory (C14):** `_capability_tool` (`:162-176`) is an
  if/elif on tool-name (D2), the three capability-tool registration blocks (`:455-479`) hard-code each
  tool's collaborators, and `_team_roster` embeds ~40 lines of manager-only director prose. Move the
  reactive-tool policy behind a `plugin.shape_tools_for_beat(...)` hook and the director prose into the
  manager's `_brief.py`. **Data-drive the capability tools** with one `dict[str, (root, ledger) -> BaseTool]`
  table — this is the single change that most unblocks adding a new role.

---

## TIER 3 — Duplication (DRY), pick up alongside the above

- **id-minting `f"{prefix}_{uuid.uuid4().hex[:12]}"`** copied ~8× across `_enforcer.py:231`,
  `_resolver.py:179`, `facade.py`, `cron/_fire.py`, `_scheduler.py` (4×), `recovery/__init__.py`. One
  `chorus.ids.mint_id(prefix)` util. (A4/C14)
- **Ledger `_row_to_X` mappers** hand-written in 20 repos + the `loads(...) or {}/[]` idiom ~15× — the
  single largest duplication in the tree. Add field-coercion helpers (`loads_dict`/`loads_list`) to a repo
  base; consider a declarative field→coercer map. (C14)
- **Ledger insert-then-reselect + `assert opened is not None`** — same 4-line ceremony in 14 repos. Factor
  `_insert_returning(sql, params, id, mapper)` that raises a real error (not `assert`). Removes 14 asserts. (C14/C8)
- **Backend-name string literals** (`"strapi"/"resend"/"markdown"/"outbox"`) repeated 6+ places in
  `chorus_tools` — a `BackendName(StrEnum)`. The one primitive that escaped the otherwise-thorough enum
  treatment. (A4)
- **Duplicated helpers:** `_document_id` (cms vs delivery Strapi), `_require` (cms vs delivery `_types.py`),
  `_HTTP_TIMEOUT_S` (twice), the env-gated backend selection (3×), quote-stripping (`_env` vs `_repl`),
  `_OPERATOR`/ANSI codes (two CLI modules), RoutineRevision field-copy (cron 3×). (C14)

---

## TIER 4 — `assert` for invariants stripped under `python -O` (C8)
Load-bearing asserts that become silent `None`-flows under `-O`: `lifecycle/_decompose.py:144`,
`cron/_add.py:88`, `_factory.py:418`, and the 18 ledger `assert opened is not None` (folded into 3.3 above).
Replace with explicit `RuntimeError`/domain error.

---

## TIER 5 — Agent-harness (action-space) improvements

- **Marketer brief is a procedure, not an identity** — `marketer/_brief.py:15-108` is a 100-line numbered
  playbook (steps 2b/3b/6b/6c are on-demand recipes). Per the skill "keep the system prompt minimal and
  invariant; move large guidance into skills loaded on demand," ~50-60% belongs in SKILL.md files (a
  `go-live` skill, a `variety` skill). Today every beat pays the token cost of the go-live recipe even for
  a pure-draft task. Keep the invariant identity (who Mira is, the gate rule, DoD, house rules).
- **Non-idempotent send retry window** — `delivery/_tool.py:201-211 _failed` tells the model "retry once,"
  but email send is at-most-once only *after* a `DeliveryRecord` is written; a partial provider success
  (accepted, then read-timeout, no record) makes "retry" double-send. Distinguish publish (idempotent flip)
  from send (at-most-once) in the recovery guidance, or record intent before calling the transport.
- **`with_web_research` is a tested no-op** — `swarm/.../_optin.py:40-56` has no production caller (the
  marketer wires `WEB_RESEARCH_ORCHESTRATOR` directly). Adopt it as the seam for all research roles or
  delete it (YAGNI/dead code). (C15/A1)

---

## TIER 6 — Lower-priority nits
- Inject a `CommandRunner` Protocol into `Scheduler` (`_run_verify_command` shells out via a module global —
  the one un-injected dependency; H1).
- `TaskId`/`RunId`/`EmployeeId` `NewType`s (every id is a bare `str`; zero `TypeAlias` in the tree — A4).
- `facade.py dream: Any` — define a minimal Protocol for the dream surface chorus calls (A5).
- `observability/_inspector.py:33` `if False:` → `if TYPE_CHECKING:` for consistency (A1).
- `dod.py:159-179` verifier `if/elif` ladder → `{DoDKind: constructor}` table (only if kinds keep growing; D2).
- 48 `TODO/FIXME` markers (top: `repos/tasks.py` ×8, `_liveness.py` ×6, governance actions ×12) — triage.
- `_ledger.py:271-280` over-indented block (cosmetic; ruff/black would flag).

---

## Recommended sequencing
1. **Tier 1** as small, test-guarded fixes (the tools `_raise_for_status` + `.json()` guard is two edits
   fixing four HIGH items; the except-narrowing + swallow-logging are localized).
2. **Tier 3 id-minting + Tier 4 asserts** — cheap, mechanical, high safety.
3. **Tier 2 god-file splits** one at a time, each behind the existing test suite (registry/`__all__` re-exports
   keep call sites untouched). Start with `_commands.py` (lowest risk — registry already isolates handlers).
4. **Tier 5** brief→skills is the biggest agent-quality win; do it when iterating on the marketer.

Every split preserves public surfaces via re-exports; run `ruff` + `mypy --strict` + `pytest` after each.
