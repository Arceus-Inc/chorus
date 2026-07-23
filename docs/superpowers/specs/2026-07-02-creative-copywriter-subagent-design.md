# §06 Creative/Copywriter Subagent — Design

**Status:** design, pre-implementation
**Spec ref:** marketer-employee.html §06 (Creative / Copywriter), §08 (`variant.render · creative.gen`, owner *Creative*, surface *worktree*), §10 (variety — a handful of on-brand candidates)
**Builds on:** the Brand-Critic subagent pattern (`_subagents.py`), the `brand-voice` skill, the `brand_lint` tool.

## Goal

Give Mira a **variation engine**: a Tier-1 role subagent that takes a research-grounded **seed** post she
writes and drafts a handful of on-brand **variants** of it — varying angle, hook, and structure while
**preserving the seed's substantiated claims and citations**. Mira then prunes and promotes the
strongest into `content_draft.md`. This produces the variety the §10 read-back loop will later consume,
without touching today's proven single-draft → Brand-Critic → land loop.

## Division of labour (§06)

- **Mira (bet-owner)** — frames the piece, gathers facts (`web_research`), writes the grounded seed,
  **selects** the winner. Selection authority stays with her.
- **Creative (variety)** — diversifies *expression*, never *evidence*. Drafts variants, self-lints,
  reports. Writes to the worktree, never publishes, never selects.

This is *augment*, not replace: Mira still drafts simple single posts directly. She spawns Creative when
she wants a candidate set.

## Data flow

1. Mira reads `brand_spec.md` + loads the `brand-voice` skill.
2. Mira spawns `web_research` for facts she lacks (unchanged).
3. Mira drafts a research-grounded seed → **`content_seed.md`** (claims cited from the research).
4. Mira spawns **Creative**, handing it the seed. Creative:
   - reads `content_seed.md` + `brand_spec.md`, loads `brand-voice`,
   - drafts N variants → **`candidates/variant_NN.md`** (angle/hook/structure vary; the seed's cited
     claims are preserved verbatim — no new unsourced metric may be introduced),
   - runs `brand_lint` on each variant,
   - returns a **structured manifest** (per-variant: file, angle, `brand_lint` clean?).
5. Mira chooses among **{`content_seed.md` + the N variants}**, promotes/merges the strongest into
   `content_draft.md`.
6. `brand_critic` reviews `content_draft.md` → land (unchanged).

**File contract:** seed = `content_seed.md` (candidate 0); variants = `candidates/variant_NN.md`;
final = `content_draft.md`. The DoD (content_draft.md exists, ≥300 words) is **unchanged**.

## Components (clean, typed — no god files)

### `src/chorus_employee/marketer/_creative_manifest.py` (new)

The typed contract for what Creative returns, so the summary is data, not a stringly blob.

```python
@dataclass(frozen=True, slots=True)
class VariantEntry:
    file: str            # "candidates/variant_01.md"
    angle: str           # one-line description of this variant's angle
    brand_lint_clean: bool

@dataclass(frozen=True, slots=True)
class CreativeManifest:
    seed: str                          # "content_seed.md"
    variants: tuple[VariantEntry, ...]
```

- `CreativeManifest.from_payload(payload: dict) -> CreativeManifest` — validating parser (raises
  `ValueError` on malformed input; no `getattr`/`setattr`, no silent defaults for required fields).
- `creative_output_schema() -> dict` — the JSON schema handed to the subagent's `output_schema`.
- A **drift test** asserts the schema's `properties` keys equal the dataclass field names, so the schema
  and the dataclass can never silently diverge.

Rationale: dream validates the subagent's final message against `output_schema`; `from_payload` gives
chorus code (tests, the example) a typed handle on the same shape.

### `src/chorus_employee/marketer/_subagents.py` (extend)

Add `CREATIVE_SUBAGENT = SubagentSpec(...)` beside `BRAND_CRITIC_SUBAGENT`:

- `name="creative"`
- `description` — the imperative brief: read the seed + spec, load `brand-voice`, produce N on-brand
  variants that **vary expression and preserve the seed's cited claims**, run `brand_lint` on each,
  return the manifest. Hard rules: never introduce an unsourced metric; never edit the seed; write only
  under `candidates/`.
- `tools=("read_file", "write_file", "skill", "brand_lint")` — all within Mira's parent toolset
  (narrower-wins satisfied).
- `output_schema=creative_output_schema()`
- `max_turns=12` — read seed+spec, load skill, draft 3 variants, lint 3 → headroom.

**N = 3** variants ("a handful"), stated in the description; Mira can ask for more/fewer in the spawn prompt.

### `src/chorus_employee/marketer/_harness.py` (extend)

Add `CREATIVE_SUBAGENT` to `subagents=(…)`.

### `src/chorus_employee/marketer/_brief.py` (extend)

Insert an optional **variety** step in the workflow: when the task wants a candidate set (paid-ad copy,
headlines, A/B, or an explicit "give me options"), Mira writes `content_seed.md`, spawns `creative`,
prunes among seed + variants, promotes into `content_draft.md`, then the existing Brand-Critic step
runs. For a simple single post she skips Creative (augment, not mandatory).

## Testing (TDD)

Unit (`tests/employee/test_creative_manifest.py`, new):
- `from_payload` round-trips a well-formed payload → typed `CreativeManifest`.
- `from_payload` raises `ValueError` on missing/mis-typed fields.
- `creative_output_schema()` is an object schema; **drift test**: its `properties` == dataclass fields.

Declaration/wiring (`tests/employee/test_marketer_subagents.py`, extend):
- `CREATIVE_SUBAGENT` is declared, `name="creative"`, tools ⊆ parent, is a write agent
  (`write_file` in tools), carries the `output_schema`.
- manifest declares `creative`; projection keeps `write_file`+`brand_lint` on the child; dream offers
  `brand_lint` at runtime (same `compute_minimum_toolset` proof as brand_critic).
- brief mentions `content_seed.md` + `creative`.

Keyed e2e (`examples/marketer_creative_run.py`, new): a real run where Mira writes a seed, spawns
Creative, Creative produces linted variants, Mira promotes one; assert `candidates/` populated and
`content_draft.md` landed. Factory built **with `ledger=`** (the capability-tool registration path).

Gate: ruff + `mypy --strict src` + the new suites.

## Out of scope (deferred)

- The §10 read-back / offline-prune-as-eval (Approach C) — a later slice; the prune here is Mira's
  judgment, not a scoring tool.
- Element-level variant sets (headline/CTA JSON) — v1 candidates are full-draft files.
- A deterministic `variant.render` tool — generation is the subagent writing files (YAGNI).

## Self-review

- **Spec coverage:** §06 Creative (generate·many·draft, worktree, never publishes) → write subagent
  scoped to `candidates/`; §08 `variant.render·creative.gen` → the subagent's generative act (+ self
  `brand_lint`); §10 variety → N on-brand candidates feeding Mira's prune. ✓
- **Division of labour:** selection stays with Mira; Creative varies expression, preserves evidence. ✓
- **Additive:** DoD, lander, kernel unchanged; single-post loop intact. ✓
- **Clean code:** typed `CreativeManifest`/`VariantEntry` (frozen, slots); validating `from_payload`;
  schema/dataclass drift guarded by a test; manifest in its own file (no god file). ✓
