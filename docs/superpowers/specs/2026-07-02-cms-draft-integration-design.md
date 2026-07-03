# `cms.draft` — CMS Integration (per-channel, swappable backend) — Design

**Status:** design, pre-implementation
**Spec ref:** marketer-employee.html §06 (Channel/Publisher — "composes the go-live, does not authorise
it"), §08 (`cms.draft` — CMS, *reversible write*, owner Channel), §07 (integrations).
**Builds on:** the `stage_go_live` gate (the *irreversible* Channel verbs), the local Strapi instance
(see the `strapi-cms-local-instance` note).

## Goal

Give the marketer a **reversible write to a CMS**: `cms.draft` takes finished content and stages it as an
*unpublished draft* in a CMS, returning a `DraftRef`. It is the one Channel act *below* the go-live gate —
publishing that draft live remains the gated `stage_go_live(publish)`. The verb is **channel-aware**
(blog / social / email) and **backend-swappable**: a keyless Markdown default for tests, and a real
Strapi backend for a live demo, behind one interface.

## Content model — per-channel types

Three content types, each a Strapi collection (Draft & Publish enabled) and a keyless Markdown mapping:

| `content_type` | required fields | optional | Strapi collection |
|---|---|---|---|
| `blog`   | `title`, `body`            | `slug`, `excerpt`, `seo_description` | `blog-posts` |
| `social` | `platform`, `text`         | `link`, `scheduled_at`               | `social-posts` |
| `email`  | `subject`, `body`          | `preheader`, `segment`               | `email-campaigns` |

`platform ∈ {linkedin, x, facebook, instagram}`. These Strapi types already exist (built during setup).

## Interfaces (`src/chorus_tools/cms/`)

```python
class ContentType(StrEnum):
    BLOG = "blog"; SOCIAL = "social"; EMAIL = "email"

# Domain object handed to a backend — one frozen, validated value per channel.
@dataclass(frozen=True, slots=True)
class CmsDraft:
    content_type: ContentType
    fields: Mapping[str, str]     # normalized, already validated per type (required present)

@dataclass(frozen=True, slots=True)
class DraftRef:
    backend: str                  # "markdown" | "strapi"
    content_type: ContentType
    ref_id: str                   # markdown: relative path · strapi: documentId
    url: str                      # a human-openable pointer (file path or admin URL)
    status: str = "draft"

class CmsBackend(Protocol):
    def create_draft(self, draft: CmsDraft) -> DraftRef: ...
```

Per-channel required-field validation lives in one place (`validate_fields(content_type, fields)`), reused
by the tool input and by `CmsDraft` construction — a malformed draft raises `ValueError`, never a silent
partial write.

## Backends

**`MarkdownCmsBackend(root: Path)`** — keyless default. Writes `{root}/{content_type}/{slug}.md` with YAML
frontmatter carrying `draft: true` + all fields; `ref_id` = the relative path. Deterministic, offline —
the real static-site workflow *and* the test default. `slug` derived from title/subject (or a stable hash
for social).

**`StrapiCmsBackend(base_url, token, *, client: httpx.Client)`** — the hosted backend. Maps
`content_type` → collection, then `POST {base_url}/api/{collection}?status=draft` with
`{"data": {...fields...}}` and `Authorization: Bearer {token}`. `?status=draft` is **required** (a plain
POST auto-publishes). Parses `data.documentId` → `DraftRef(ref_id=documentId,
url="{base_url}/admin/content-manager/collection-types/api::{singular}.{singular}/{documentId}")`. The
`httpx.Client` is **injected** so tests use `httpx.MockTransport` (no network); non-2xx → `CmsError` with a
recovery contract.

Backend selection is by **config, not the model**: `StrapiCmsBackend` when `STRAPI_URL` + `STRAPI_TOKEN`
are in env, else `MarkdownCmsBackend` rooted at the worktree. (`httpx` added to `pyproject` deps —
currently only transitively present.)

## The `cms_draft` tool (`src/chorus_tools/cms/_tool.py`)

`CmsDraftTool(BaseTool)`, mirroring `GoLiveTool`/`BrandLintTool`:
- **name** `cms_draft`; `ToolDeclaration(risk="low", tier_required=<REPO_WRITE_NET-compatible>,
  timeout_seconds=20.0)` — a *reversible* external write, below the go-live gate (contrast `stage_go_live`).
- **Input** (`CmsDraftInput`, pydantic): `content_type` + the union of fields; a `model_validator` enforces
  the required fields for the chosen type (flat schema, not `oneOf` — more robust for weaker models to
  call). Builds a validated `CmsDraft`.
- **execute:** call `backend.create_draft(draft)`; return the observation contract —
  `status="success"`, `summary` ("drafted a linkedin social post → documentId abc"), `next_actions`
  (["Review the draft; stage_go_live(publish) to publish it."]), `artifacts` (the `DraftRef` as a dict).
  Error paths (validation / backend failure) → `is_error=True` with `root_cause`/`safe_retry`/
  `stop_condition`, like `GoLiveTool._rejected`.

The tool takes **explicit fields** as input (the model fills title/body/platform/subject from its finished
draft) rather than parsing `content_draft.md` — reliable and channel-correct.

## Wiring

- **Register** in `_factory._capability_tool`: `if name == "cms_draft": return CmsDraftTool(_cms_backend_from_env(...))`.
- **Map** `"cms_draft": "cms_draft"` into `_CHORUS_TO_DREAM_TOOL` (identity — so `dream_tool_names` +
  the subagent projection keep it, exactly like `brand_lint`).
- **Marketer manifest:** add `cms_draft` to `tools`; add the Strapi host to the sandbox egress allowlist
  (net reach for the live backend — analogous to Tavily's `api.tavily.com`).
- **Brief:** one optional step — after a Brand-Critic PASS, `cms_draft` the finished content (naming its
  `content_type`), then `stage_go_live(publish, target=<DraftRef>)` for the gated publish. For a pure
  drafting task she can stop at `content_draft.md`.
- **Owner:** Mira directly (consistent with `stage_go_live` on her shelf); the Channel subagent defers.

## Pipeline linkage

`content_draft.md` (Brand-Critic PASS) → **`cms_draft(content_type, fields)`** →
`DraftRef{backend, documentId, url, status:"draft"}` → **`stage_go_live(publish, target=DraftRef)`**
(opens the human gate — built) → live. The reversible write and the gated publish compose.

## Testing (TDD)

- **`validate_fields` / `CmsDraft`** (unit): required-field presence per type; `ValueError` on missing.
- **`MarkdownCmsBackend`** (unit, deterministic): each type writes the right file with `draft: true`
  frontmatter + all fields; `DraftRef.ref_id` is the relative path.
- **`StrapiCmsBackend`** (unit, `httpx.MockTransport`): each type POSTs to the right collection with
  `?status=draft` and the right body; parses `documentId` → `DraftRef`; non-2xx → `CmsError`.
- **`CmsDraftTool.execute`** (unit, fake backend): success contract + each error path.
- **Wiring:** `dream_tool_names(("cms_draft",)) == ("cms_draft",)`; marketer manifest includes `cms_draft`;
  `_capability_tool` returns the tool; backend-from-env picks Strapi when env set, else Markdown.
- **Live e2e** (`examples/marketer_cms_draft_run.py`, gated on `STRAPI_URL`+`STRAPI_TOKEN`): a real beat
  where Mira drafts + `cms_draft`s a post into the running Strapi; assert a `documentId` came back and the
  entry is a draft (`publishedAt: null`) via a follow-up GET. The Markdown backend gives the deterministic
  keyless e2e when Strapi env is absent.

Gate: ruff + `mypy --strict src` + the new suites.

## Out of scope (deferred)

- **Publishing** (making a draft live) — that's `stage_go_live(publish)`, already gated; `cms_draft` only
  stages.
- **Update/delete** of an existing draft (v1 is create-only; reversibility holds because a draft isn't
  live).
- Other backends (WordPress/Ghost) — drop in behind `CmsBackend` later, verb unchanged.
- The Channel subagent as a distinct owner — Mira holds `cms_draft` directly for v1.

## Self-review

- **Spec coverage:** §08 `cms.draft` (CMS, reversible write, owner Channel) → the `cms_draft` verb, below
  the gate; §06 Channel "composes go-live, does not authorise" → `DraftRef` feeds `stage_go_live`. ✓
- **Swappable source:** `CmsBackend` protocol, Markdown default + Strapi, config-selected. ✓
- **Per-channel fidelity:** three content types + routing; flat validated input. ✓
- **Clean code:** frozen `CmsDraft`/`DraftRef`, one `validate_fields`, injected `httpx.Client`, no god
  file (interface / backends / tool split under `chorus_tools/cms/`). ✓
- **Safety:** reversible-only; publish stays gated; creds via env, host allowlisted. ✓
