# `brand_lint` Tool — Design (harness-principled)

**Status:** design, pre-implementation
**Spec ref:** marketer-employee.html §08 (Tools & skills — `brand.lint · claim.check`, owner *Brand-Critic*, surface *read*), §10 (validation sandwich)
**Skill lens:** agent-harness-construction (action space · observation · recovery · context budget)

## Goal

Give the **Brand-Critic** a deterministic primitive it can ground its verdict on: a single read-only
verb that scans a drafted content file against the brand voice rules and returns structured findings —
prohibited phrases and unsubstantiated claims. It is the *mechanical* half of the §10 validation
sandwich (deterministic rules), complementing the Brand-Critic's *agentic* judgment. No external
integration: the "brand kit" is the local `brand_spec.md`.

## Why one tool, not two (action-space design)

The spec names `brand.lint · claim.check`. Two tools that both scan the same draft against the same
spec is the **overlapping-semantics anti-pattern** — the model must reason about which to call and how
to sequence them, for no gain. Instead: **one verb, two check dimensions** surfaced as distinct
`kind`s in the output. One deterministic pass, one call, unambiguous.

- **Name:** `brand_lint` — stable, explicit, a verb (not a catch-all).
- **Granularity:** *medium* tool (read-only, cheap). `ToolDeclaration(risk="safe", tier_required=0,
  timeout_seconds=15.0)`. Micro-tools are reserved for high-risk effects (deploy/migrate/permissions);
  this only reads two files.

## Interfaces

### Input (schema-first, narrow)

```python
class BrandLintInput(BaseModel):
    doc: str = Field(min_length=1, description="the drafted content file to lint, e.g. 'content_draft.md'")
    spec: str = Field(default="brand_spec.md", description="the brand-voice spec (the local brand kit)")
```

No catch-all params. Both paths resolve against `ctx.working_dir`.

### Finding (deterministic element shape)

```python
class BrandFinding(BaseModel):
    kind: Literal["prohibited_phrase", "unsubstantiated_claim"]
    line: int          # 1-based line number in `doc`
    quote: str         # the offending text (phrase, or the sentence)
    rule: str          # which rule fired ("prohibited phrase 'game-changing'" / "metric stated as fact, unhedged & uncited")
    fix: str           # a concrete, actionable remedy
```

### Observation contract (the `ToolResult`)

`ToolResult.content` is a compact human/LLM-readable summary; `ToolResult.metadata` carries the typed
observation contract so the Brand-Critic can act on it:

```
status:       "success" (0 findings) | "warning" (>=1 finding) | (is_error path below)
summary:      "brand_lint: 2 prohibited phrases, 1 unsubstantiated claim — 3 findings"
findings:     [BrandFinding, ...]   # JSON-safe dicts, deterministically ordered by (line, kind)
next_actions: ["Fix each finding, then re-lint.", "Hedge or cite the flagged claim(s)."]
artifacts:    {"doc": <doc>, "spec": <spec>}
```

Deterministic: identical inputs → byte-identical `findings` (stable sort, no timestamps/randomness).

## Detection rules (deterministic)

### Prohibited phrases (`kind="prohibited_phrase"`)

1. Parse `spec` for a `## Prohibited Phrases` heading (case-insensitive); collect the bullet/CSV lines
   under it until the next `##` heading; split on commas → the phrase list.
2. Fallback list if the section is absent (keeps the tool useful on a thin spec):
   `revolutionary, game-changing, 10x, unlock, supercharge, best-in-class, cutting-edge, seamless, effortless`.
3. Scan `doc` line-by-line, case-insensitive, word-boundary match. Each hit → a finding with the line,
   the matched quote, `rule="prohibited phrase '<phrase>'"`, `fix="remove or replace '<phrase>' with a plain, specific description"`.

### Unsubstantiated claims (`kind="unsubstantiated_claim"`) — advisory heuristic

For each sentence in `doc`:
- `has_metric`   = regex `\d+%` | `\$\s?\d` | `\b\d+(\.\d+)?x\b` | `\b\d{2,}\b`
- `has_guarantee`= `\b(will|guarantees?|ensures?|eliminates?|never|always)\b` (outcome promise)
- `has_hedge`    = `we believe` | `early results suggest` | `designed to` | `aims to` | `can help` | `\b(may|could|might)\b`
- `has_citation` = `\[\d+\]` | an http(s) URL | `according to` | `\(source` | a bare domain (`\b\w+\.(com|io|org|ai)\b`)

Flag when `(has_metric or has_guarantee) and not has_hedge and not has_citation`. `rule="a metric/outcome
is stated as fact without a hedge or a source"`, `fix="hedge it ('we believe' / 'early results suggest')
or cite the source inline"`. This is deliberately *advisory* — the Brand-Critic adjudicates false
positives; the tool's job is to surface candidates the reasoning agent might miss.

## Recovery contract (error paths)

`doc` missing (nothing drafted yet):
- `root_cause="doc '<doc>' not found in the worktree"`
- `safe_retry="write the draft first, then lint it"`
- `stop_condition="nothing to lint until the draft exists"`

`spec` missing:
- `root_cause="brand spec '<spec>' not found"`
- `safe_retry="ensure brand_spec.md exists; or lint against the built-in default prohibited-phrase list"`
- `stop_condition="no brand kit — proceed on the Brand-Critic's judgment alone"`
- (Design choice: for a missing spec we still lint prohibited phrases against the fallback list and
  return `status="warning"` with a note, rather than hard-error — a missing spec should degrade, not
  blind the critic. A missing *doc* is a hard error: there is genuinely nothing to lint.)

Bad input (validation) → `is_error=True` with `root_cause` = the validation message, mirroring
`GoLiveTool._rejected`.

## Context budget

- Output is compact structured findings, never the draft echoed back.
- Rules come **by reference** (parsed from `brand_spec.md` on demand), never inlined into the prompt or
  the tool's own description.
- The Brand-Critic's standing brief already lives in its `description`; `brand_lint` adds a *verb*, not
  more prose — no system-prompt growth.

## Architecture pattern

Hybrid: the Brand-Critic is a **ReAct** reasoner; `brand_lint` is a **typed function-call** it invokes
to get deterministic ground truth, then reasons over the findings to issue PASS/FAIL. The tool itself
is pure function-calling (no internal reasoning, no model call).

## Module layout & wiring

- **Create** `src/chorus_tools/_brand_lint.py` — `BrandLintInput`, `BrandFinding`, `BrandLintTool(BaseTool)`,
  plus pure helpers `parse_prohibited_phrases(spec_text) -> tuple[str, ...]` and
  `lint_text(doc_text, phrases) -> list[BrandFinding]` (unit-testable with no ctx).
- **Export** from `src/chorus_tools/__init__.py` (`BrandLintTool`, ...).
- **Register** in `chorus_harness/_factory.py::_capability_tool` — `if name == "brand_lint": return BrandLintTool()`
  (no ledger needed; it's a pure file reader — unlike the ledger-bound tools).
- **Map** `"brand_lint": "brand_lint"` into `_CHORUS_TO_DREAM_TOOL` so `dream_tool_names` keeps it.
- **Scope — on the Brand-Critic subagent (§08 owner), via the identity-map (corrected RCA).** The
  earlier "dream blocks capability tools in subagents" RCA was **wrong**. The drop was purely in
  chorus's `_subagent_set` (`dream_tool_names(spec.tools)` strips a name absent from
  `_CHORUS_TO_DREAM_TOOL`). Identity-mapping `"brand_lint"` fixes it, and dream does NOT block it: the
  generator overlay writes no `tools` line, so its `manifest.tools is None` → `compute_minimum_toolset`
  returns **all registered tools** (incl. `brand_lint`), which is the subagent's parent-tool ceiling.
  Verified deterministically: with the map, `brand_lint` is registered in the role registry AND the
  projected `brand_critic` child carries `('read_file', 'working_memory_read', 'brand_lint')`.
- **The real fault in the first keyed run was the MARKETER BRIEF over-instructing the parent** to call
  `brand_lint` — that made the *parent* try `spawn_subagent(name="brand_lint")` (mis-firing), and
  polluted the run. Fix: the marketer brief says NOTHING about `brand_lint`; it is the Brand-Critic's
  owned primitive, driven by the critic's own description. The parent still lists `brand_lint` in its
  tools (the projection requires the parent to hold it) but is never told to use it. A keyed run
  confirmed the parent no longer mis-spawns it.
- **Runtime offering is proven, not assumed.** A deterministic test drives dream's *own*
  `compute_minimum_toolset` on the critic's `_build_subagent_manifest` (parent ceiling = all registered
  tools, since the generator manifest is `tools=None`) and asserts `brand_lint` is in the offered set —
  so dream genuinely surfaces it to the critic. In the last keyed run the (weak) critic *model* still
  claimed "brand_lint not available"; that was a hallucination — the same run also hallucinated
  read_file truncation and illegally tried `spawn_subagent` from inside a subagent. The wiring is
  correct; reliable in-beat use is a model-quality matter (a stronger critic model, or the DoD-gate
  design below).
- **Alternative still worth doing:** expose `brand_lint` as a **DoD gate** the kernel runs
  deterministically (CLI + Command DoD), removing the dependence on the model choosing to call it.
- **Brief:** one line in the Brand-Critic's `description` — "run `brand_lint` first for the mechanical
  prohibited-phrase/claim scan, then reason over its findings" — so the deterministic pass grounds the
  verdict rather than replacing it.

`BrandLintTool` takes **no constructor args** (pure file reader), so `_capability_tool` returns it even
when `self._ledger is None`. Confirm `_capability_tool` is reached on that path; if it's gated behind
`if self._ledger is not None`, hoist ledger-free tools out of that guard.

## Test plan (deterministic, keyless)

Unit (pure helpers, no ctx):
- `parse_prohibited_phrases`: extracts the CSV list under `## Prohibited Phrases`; falls back when absent.
- `lint_text`: a draft with "game-changing" → one `prohibited_phrase` finding at the right line; a
  clean draft → `[]`; `"cuts build time 40%"` (no hedge/cite) → one `unsubstantiated_claim`; the same
  hedged (`"we believe it cuts build time ~40%"`) or cited (`"cuts build time 40% [1]"`) → none.

Tool (`execute` with a fake `ToolExecutionContext` + tmp worktree):
- clean draft → `status="success"`, `findings=[]`.
- violating draft → `status="warning"`, findings include both kinds; `next_actions` present; artifacts set.
- missing `doc` → `is_error=True`, `root_cause`/`safe_retry`/`stop_condition` set.
- missing `spec` → `status="warning"` (degrades to the fallback list), note in summary.

Wiring:
- `dream_tool_names(("brand_lint",)) == ("brand_lint",)`.
- marketer manifest tools include `brand_lint`; `BRAND_CRITIC_SUBAGENT.tools` includes `brand_lint`;
  the projection keeps it on the child (subset of parent).

Gate: ruff + `mypy --strict src` + the new suites.

## Out of scope (deferred)

- Backing the prohibited list / ontology with the §07 brand MCP (`ref:brand_ro`) — swap the *source*
  later; the verb is unchanged.
- Semantic truth-checking of claims (that's `web_research`'s job); `brand_lint` only checks
  hedged-or-cited *structure*.

## Self-review

- **Spec coverage:** §08 `brand.lint` + `claim.check` → the two `kind`s of one tool; owner Brand-Critic →
  scoped to `BRAND_CRITIC_SUBAGENT.tools`; surface read → `risk="safe", tier_required=0`. ✓
- **Harness lenses:** action space (one narrow verb) · observation (status/summary/next_actions/
  artifacts) · recovery (root_cause/safe_retry/stop_condition, degrade-on-missing-spec) · context
  (findings not draft; rules by reference). ✓
- **Determinism:** no randomness/time; stable sort by (line, kind); pure helpers separated for testing. ✓
- **No external dep / no keys:** reads two local files only. ✓
