# Go-Live Publish Executor — `execute_go_live` (blog publish) — Design

**Status:** design, pre-implementation
**Spec ref:** marketer-employee.html §05 (the dark node — "ship is a gate, not an action"), §08
(`publish.schedule` — Channel, send·gate), §09/§11 (human-gated reach).
**Builds on:** `cms_draft` (the staged draft + standing-draft index), `stage_go_live` (the gate),
the Strapi blog (`/blog` — published posts are publicly live).

## The gap this closes

Approving a `stage_go_live` gate today wakes the assignee — and nothing else. `TaskGateAction.on_approve`
(AUTHORIZATION) sets the task `todo` + wakes Mira, but she has no tool to execute the approved reach: an
approved go-live is a dead end. This slice builds the **executor**: the fail-closed verb that turns an
*approved* gate into an *actual publish* — the Strapi draft flips to published and the post appears on
the public blog.

## Decisions locked in brainstorming

- **Driver: Mira executes** (user choice) — on wake she calls `execute_go_live`; the kernel does not
  auto-execute. Fragility is contained by mechanism, not hope:
  - **Fail-closed:** the tool verifies in the ledger that THIS task's gate is `APPROVED`. Pending /
    denied / absent can never execute.
  - **Self-resolving:** the tool looks the gate up by the beat's `task_id` (new
    `ApprovalRepo.for_subject`) — the model never has to remember an approval id (optional input
    disambiguates if given).
  - **Idempotent:** one delivery per approval (`.harness/deliveries.json`); a re-call returns the
    standing delivery, never double-publishes.
- **Scope: publish first.** The blog publish path is fully live (Strapi); `email.send` arrives later
  behind the same seam. Non-publish reach stays gated-but-inexecutable for now.
- **No kernel changes** in this slice. (Optional follow-up: enrich the on-approve wake payload with
  `cause: gate_approved` for observability; not needed for correctness since the tool self-resolves.)

## Pipeline completed

`content_draft.md` → `cms_draft` (Strapi DRAFT, invisible on `/blog`) → `stage_go_live(publish)`
(gate opens, task blocks) → **human approves** → Mira wakes → **`execute_go_live(content_type)`**
→ Strapi draft → PUBLISHED → **the post is live on `http://localhost:1337/blog/`** → delivery
recorded → done.

## Strapi contract (pinned live against the local instance)

`PUT /api/{collection}/{documentId}?status=published` with body `{"data": {}}` publishes the existing
draft — fields preserved, `publishedAt` set, entry immediately visible on the public API (the blog).
Verified 2026-07-02 with a probe draft (created → published → publicly readable → deleted).

## Components (`src/chorus_tools/delivery/`, small typed files — no god file)

### `_types.py`
- `PublishedRef` (frozen, slots): `backend`, `ref_id`, `url` — what a backend knows after publishing.
- `DeliveryRecord` (frozen, slots): `approval_id`, `action` (`GoLiveAction`), `target`,
  `published: PublishedRef` — flattened `as_dict()` / validating `from_dict()` for the index.
- `DeliveryError(RuntimeError)` — a backend failed to deliver.

### `_backend.py`
`PublishBackend` protocol: `publish(draft: DraftRef) -> PublishedRef` (raises `DeliveryError`).
The seam `email.send`'s `EmailBackend` will sit beside later.

### `_strapi_publish.py`
`StrapiPublishBackend(base_url, token, *, client: httpx.Client)` — routes `draft.content_type` →
collection (same map as `StrapiCmsBackend`), `PUT …/{documentId}?status=published` with `{"data":{}}`.
Blog content publishes to a human URL: `{base}/blog/#/post/{documentId}`; other types → admin URL.
Injected client (MockTransport-tested); non-2xx or missing `documentId` → `DeliveryError`.

### `_markdown_publish.py`
`MarkdownPublishBackend(root)` — the keyless default, symmetric with `MarkdownCmsBackend`: publishing
flips `draft: true` → `draft: false` in the frontmatter of the file at `DraftRef.ref_id` (exactly how
a static site goes live). Missing file → `DeliveryError`.

### `_index.py`
`DeliveryIndex` — worktree JSON map `approval_id → DeliveryRecord` at `.harness/deliveries.json`
(mirrors `CmsDraftIndex`: absent/malformed = empty; `standing_delivery()` / `record()`).

### `_config.py`
`publish_backend_from_env(markdown_root)` — Strapi when `STRAPI_URL`+`STRAPI_TOKEN` set, else Markdown.
Config picks the backend, never the model.

### `_tool.py` — `ExecuteGoLiveTool` (`execute_go_live`)
- Input (`ExecuteGoLiveInput`, pydantic): `content_type` (`ContentType`) + optional `approval_id`.
- `execute` flow (every exit typed, nothing stringly):
  1. Validate input → else rejected (schema recovery contract).
  2. `BeatContext.read(working_dir)` → no beat context → rejected (outside a beat).
  3. Resolve the gate: `approval_id` given → `approvals.get` and require `subject_id == task_id`;
     else newest `TASK_GATE` approval for this task via `approvals.for_subject(task_id)`.
  4. Status matrix: absent → rejected "stage_go_live first" · `PENDING` → rejected "await approval" ·
     `DENIED`/other → rejected "denied — do not publish" · `APPROVED` → proceed.
  5. Idempotency: standing delivery for this approval → return it ("already delivered").
  6. Resolve WHAT to publish from the standing-draft index (`{content_type}:{task_id}`) — the model
     cannot name an arbitrary document; only the staged draft is publishable. Absent → rejected
     "nothing staged — run cms_draft first".
  7. `backend.publish(draft_ref)` → `DeliveryError` → failed (recovery contract).
  8. Record the `DeliveryRecord`; return the observation contract (status `delivered`, the live URL in
     summary + artifacts).

### Ledger addition
`ApprovalRepo.for_subject(subject_id) -> list[Approval]` (newest first) — read-only query, unit-tested.

## Wiring
- `_CHORUS_TO_DREAM_TOOL`: identity-map `execute_go_live` (projection-safe, like `brand_lint`).
- Factory materialize: register `ExecuteGoLiveTool(ledger, publish_backend_from_env(root / "cms_drafts"))`
  when `execute_go_live ∈ config.tools` and the ledger is bound (needs both ledger + worktree).
- Marketer manifest: `execute_go_live` joins her shelf.
- Brief step 6d: staged a go-live and been re-woken on the same task → call
  `execute_go_live(content_type=…)`; if it reports the gate is still pending, stop and wait — never
  try to publish around the gate.

## Testing (TDD)
- **Types:** `PublishedRef`/`DeliveryRecord` frozen + dict round-trip + validation errors.
- **Index:** standing/record/persist/overwrite (mirror of the cms index suite).
- **Strapi backend (MockTransport):** PUT to the right collection/documentId with `?status=published`
  + bearer; blog URL shape; non-2xx → `DeliveryError`.
- **Markdown backend:** flips `draft: true → false` in place; missing file → `DeliveryError`.
- **Ledger:** `for_subject` returns the task's approvals newest-first; empty for unknown subject.
- **Tool (fake ledger + fake backend):** the full fail-closed matrix — no beat context / no gate /
  pending / denied / approved-executes / wrong-task approval_id rejected / idempotent second call /
  no staged draft. Nothing publishes on any rejected path.
- **Wiring:** identity map; manifest holds the tool; factory registers it.
- **Live e2e** (`examples/marketer_go_live_run.py`): Mira drafts → `cms_draft` (draft invisible on
  `/blog`) → `stage_go_live(publish)` (task blocks) → script approves the gate → tick → Mira wakes and
  `execute_go_live` → **public GET shows the post published** (the blog now renders it) → delivery
  recorded, task done.

## Out of scope (deferred)
- `email.send` executor + `OutboxEmailBackend`/Resend — next slice, same seam.
- Action-typed gate payloads (today the gate's reason is prose; the executor publishes the standing
  draft, the only executable reach). RateCap/daily-cap guardrails (§11) — follow-up.
- Kernel wake-payload enrichment (`cause: gate_approved`) — optional observability follow-up.

## Self-review
- §05 dark node closed: gate → approve → execute → world visibly changes (the blog). ✓
- Fail-closed everywhere: unapproved reach cannot execute; only the staged draft is publishable. ✓
- Idempotent: one delivery per approval; re-calls return the standing record. ✓
- Clean code: frozen slotted types, protocol seam, per-file responsibility, validating parsers,
  injected HTTP client, config-selected backend. ✓
