# Email Send Executor — `email.send` behind the go-live gate — Design

**Status:** design, pre-implementation
**Spec ref:** marketer-employee.html §08 (`email.send` — Channel, send·gate), §11 (human-gated reach).
**Builds on:** the publish executor slice (PublishBackend seam, DeliveryIndex, `execute_go_live`,
duplicate-gate guards) — this is the second reach behind the same seam, exactly as that spec deferred it.

## The shape

No new model-facing tool and no new gate machinery. `execute_go_live(content_type='email')` routes to
a **send** executor instead of publish — same fail-closed matrix (approved gate only, exactly once per
approval, only the standing staged draft), same delivery index, same probe-first brief. The delivered
action recorded is `GoLiveAction.SEND`.

## Decisions

- **Backends: Outbox + Resend live** (user choice). `OutboxEmailBackend` is the keyless default — an
  approved send writes a complete `.eml`-style file under `outbox/` in the worktree (the exact
  Markdown-backend analogy: delivery you can open in a text editor). `ResendEmailBackend` is selected
  when `RESEND_API_KEY` is in env (mirrors the cms Strapi selection). Same `EmailBackend` protocol.
- **The approved content sends — never model-retyped text.** At execute time the send executor reads
  the staged email draft back from the CMS (`CmsBackend.read_draft`) and sends THAT. The model cannot
  smuggle different copy past the gate; what the human approved is what ships.
- **Routing is config, never the model.** Sender + recipients come from env (`EMAIL_FROM`,
  `EMAIL_TO` comma-list) via a frozen `EmailRouting`. The §11 blast radius stays with the operator;
  the `segment` field on the draft is descriptive metadata until an audience store exists.

## Components

### `cms` additions
- `CmsBackend.read_draft(ref_id, content_type) -> CmsDraft` — the inverse of staging.
  - Markdown: parse the file's YAML frontmatter (it holds exactly `draft.fields()`) → typed draft.
  - Strapi: `GET /api/{collection}/{ref_id}?status=draft` → map fields → typed draft.
  - Unknown ref / malformed file → `CmsError`.

### `delivery` additions (small files, mirrors publish)
- `_email_types.py` — `EmailMessage` (frozen: sender, recipients tuple, subject, body, preheader)
  built from `EmailRouting` + `EmailDraft`; `EmailRouting` (frozen: sender, recipients, validated
  non-empty) with `email_routing_from_env()` (defaults `mira@localhost` → `outbox@localhost`).
- `_email_backend.py` — `EmailBackend` protocol: `send(message: EmailMessage) -> PublishedRef`
  (raises `DeliveryError`). `PublishedRef` is reused as the generic landed-ref.
- `_outbox_email.py` — `OutboxEmailBackend(root)`: writes `outbox/{n:04d}-{slug(subject)}.eml` with
  `From/To/Subject/X-Preheader` headers + body; returns `PublishedRef(backend="outbox", ...)`.
- `_resend_email.py` — `ResendEmailBackend(api_key, *, client)`: `POST https://api.resend.com/emails`
  `{from, to, subject, text}` with bearer auth → `{"id"}` → `PublishedRef(backend="resend",
  ref_id=id, url=https://resend.com/emails/{id})`. Non-2xx / missing id → `DeliveryError`.
  MockTransport-tested; live e2e needs the user's `RESEND_API_KEY`.
- `_send.py` — `EmailDelivery(cms_backend, email_backend, routing)`: `send(draft: DraftRef) ->
  PublishedRef` — reads the staged draft back, builds the message, sends. The one place content
  meets transport.
- `_config.py` — `email_delivery_from_env(markdown_root)`: cms backend from env (existing) +
  Resend-when-keyed-else-Outbox + routing from env.
- `_tool.py` — `ExecuteGoLiveTool(ledger, publish_backend, email_delivery)`: `content_type=email` →
  `email_delivery.send(draft)` recorded as `SEND`; other types → publish as today. All guards
  (gate matrix, duplicate-gate resolution, idempotency, standing-draft-only) apply unchanged.

### Wiring
- Factory: build `EmailDelivery` beside the publish backend and pass both.
- Brief 6b/6c: mention `content_type="email"` explicitly (stage with cms_draft(email …), the go-live
  action is `send`, execute publishes nothing — it SENDS to the configured audience).

## Testing (TDD)
- `read_draft` round-trips per backend: create → read equals original (markdown parse + Strapi
  MockTransport GET); unknown/malformed → `CmsError`.
- `EmailRouting`/`EmailMessage` validation + env parsing (comma list, defaults).
- Outbox: file exists with headers + body; sequential names; returns landed ref.
- Resend (MockTransport): endpoint/auth/payload shape; id → ref; non-2xx → `DeliveryError`.
- `EmailDelivery`: reads the STAGED content (not input), composes routing, propagates errors.
- Tool: email content_type routes to send, records action `send`, full fail-closed matrix untouched
  (existing tests keep passing); email without configured delivery → rejected.
- Live e2e `examples/marketer_email_send_run.py`: 3-step (stage → approve → execute) — Resend when
  keyed, outbox otherwise; the delivery record holds the Resend message id.

## Out of scope
- Audience/segment resolution (recipient lists from a store) — routing stays env-config.
- Deliverability skill, warmup, send caps (`RateCap` binding) — follow-up hardening.
- HTML templating — v1 sends the markdown body as text.
