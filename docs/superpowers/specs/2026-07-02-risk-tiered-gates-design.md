# Risk-Tiered Go-Live Gates — LOW executes on AgentReview alone — Design

**Status:** design, pre-implementation
**Spec ref:** marketer-employee.html §09 ("Graded, not blanket — risk-tiered approval": LOW =
Brand-Critic only · MED = Brand-Critic + one approver · HIGH = + human/legal), §11 blast radii.
**Builds on:** stage_go_live (the gate), execute_go_live (the executor), brand_lint, the
Brand-Critic subagent, the delivery/standing-draft indexes.

## The gap

Today every `stage_go_live` opens a human AUTHORIZATION gate — the gate is blanket, not graded.
The spec is explicit that a $0 organic post needs no human: LOW-tier reach should clear on
**AgentReview (the Brand-Critic) alone**, while MED/HIGH keep the human. Blast radius should set
the bar, and the bar should be policy, not vibes.

## Decisions locked (user)

1. **LOW is authorized by a policy-approved gate row.** `stage_go_live` still opens the Approval
   row for LOW-tier reach, then immediately resolves it APPROVED with
   `decided_by_user_id="policy:low-risk"`. One uniform audit trail — every reach has a gate row and
   a named decider — and `execute_go_live` is UNTOUCHED: it just finds an approved gate. All
   existing guards (duplicate-gate resolution, idempotent delivery, standing-draft-only) keep
   working unchanged.
2. **The tier table is a configurable policy with the spec's table as the shipped default.**
   A frozen `RiskPolicy` value; operators override via env (the same pattern as email routing).
3. **LOW requires a RECORDED Brand-Critic verdict** — not a conversational PASS. The critic's
   verdict becomes a durable, content-hash-bound record that `stage_go_live` checks mechanically.

## Threat model detail (why the verdict tool has a lint floor)

dream enforces subagent tools ⊆ parent tools, so any tool the Brand-Critic holds, Mira also holds
— a bare `submit_brand_verdict(pass)` could be called by the parent to smuggle a PASS. The tool
therefore re-verifies mechanically: it runs the brand_lint scan on the content itself and REFUSES
to record PASS while the scan is dirty. A recorded PASS thus always carries deterministic evidence,
whoever called the tool. (Caller-identity enforcement can tighten this later if dream exposes
spawn depth in tool context.)

## Components

### `RiskTier` + `RiskPolicy` (`chorus_tools/_risk.py`)
- `RiskTier` StrEnum: `LOW | MEDIUM | HIGH`.
- `RiskPolicy` frozen: `low_targets: frozenset[str]` (normalized target names whose $0 publish is
  LOW), `spend_cap_cents: int`.
- `classify(input: GoLiveInput) -> RiskTier`, pure:
  - `spend` → `HIGH` if `amount_cents > spend_cap_cents` else `MEDIUM`
  - `send` → `MEDIUM` (full-list → HIGH needs an audience store; deferred)
  - `publish` → `LOW` if normalized target ∈ `low_targets` else `MEDIUM`
- `risk_policy_from_env()`: `GO_LIVE_LOW_TARGETS` (comma list, default empty — spec-faithful:
  nothing is LOW until the operator says so) + `GO_LIVE_SPEND_CAP_CENTS` (default 50_000).

### Brand-verdict record (`chorus_tools/brand/`)
- `BrandVerdict` frozen: `verdict: pass|fail`, `content_ref`, `content_sha256`, `task_id`,
  `notes`; validating dict round-trip.
- `BrandVerdictIndex` — worktree JSON at `.harness/brand-verdicts.json`, keyed by
  `content_sha256` (the hash binds the verdict to the exact bytes reviewed; edit-after-review
  invalidates it by construction). Mirrors the cms/delivery indexes.
- `SubmitBrandVerdictTool` (`submit_brand_verdict`): input `(verdict, content_ref, notes)`;
  reads the file, computes sha256, runs the brand_lint scan; **refuses to record PASS on a dirty
  scan** (records FAIL-with-findings instead); writes the index; also emits a ledger Activity
  (REVIEW_VERDICT-style) for the durable audit stream. Identity-mapped; added to the
  Brand-Critic's toolset (and thus Mira's shelf, per the intersection rule — safe because of the
  lint floor).

### `stage_go_live` LOW branch
After the existing guards, classify the tier:
- `MEDIUM`/`HIGH`: today's behavior, with the tier named in the gate reason.
- `LOW`: look up a PASS `BrandVerdict` whose `content_sha256` matches the CURRENT bytes of
  `content_ref` and whose `task_id` is this beat's task. Present → open the gate and approve it
  in-row via `approvals.approve(decided_by_user_id="policy:low-risk")` — **directly, not through
  the GovernanceResolver** (the resolver's on_approve flips the task to todo + wakes; mid-beat
  that would fight the running beat — the row flip alone is correct here). Response:
  "auto-authorized (LOW risk, brand verdict <hash8>) — call execute_go_live now". Absent/stale/
  FAIL → fall back to the normal human gate, reason noting the downgrade ("LOW-eligible but no
  current brand verdict"). Fail-closed in every branch.

### Brief + critic prompt
- Critic system prompt: after reaching a verdict, record it with `submit_brand_verdict` — the
  verdict does not exist until recorded.
- Brief 6b: on a LOW-eligible task the flow is unchanged (draft → critic PASS → cms_draft →
  stage_go_live) — the only difference is the gate may come back auto-authorized, in which case
  proceed straight to execute_go_live in the same beat.

## Testing (TDD)
- classify: full matrix (each action × cap boundary × target membership); env parsing + defaults.
- verdict tool: PASS refused on dirty lint (records FAIL); PASS recorded with matching hash on
  clean content; index round-trip; ledger activity written.
- stage LOW: auto-approves with policy decider ONLY when a hash-current PASS exists; stale hash /
  FAIL / missing → human gate; MED/HIGH unchanged; auto-approved gate is immediately executable
  by execute_go_live (integration: stage → execute in one flow, no human).
- e2e (keyed): a LOW-target publish task — Mira drafts, critic records PASS, cms_draft,
  stage_go_live returns auto-authorized, execute_go_live publishes — task done with ZERO human
  steps; the gate row shows decided_by="policy:low-risk". A MED task in the same run still blocks.

## Out of scope
- HIGH-tier differentiated approver roles (legal chain) — approval routing is a later slice.
- Full-list vs sub-list send distinction (needs an audience store).
- Caller-identity enforcement on the verdict tool (needs dream to expose spawn depth).
