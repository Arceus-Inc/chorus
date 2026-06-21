# Hard tasks — stress goals for `--org` mode

A catalogue of meaty, real-library build goals to throw at the 3-level org (`run.py --org`). Each is in
the spirit of the original GRPO probe: **multiple modules that must agree on an interface, a genuine
algorithm that can't be stubbed past a good test, and a clear "done" bar.** That combination is what
surfaces the org's hard failure modes — split-brain/duplicate modules, `done`-but-not-landed (unmerged
branch), off-brief output passing a bypassed DoD, and integrate churn that ends the goal `blocked`.

## How to run

```bash
set -a; eval "$(grep -E '^AZURE_OPENAI_(API_KEY|BASE_URL|DEPLOYMENT)=' .env)"; set +a

uv run python standup-app/run.py --org --task "<paste a goal below>"
# add --timeout 300 for the heavier ones; the report (org chart + task tree) is written at the end
```

After a run, inspect the landed repo + `report.md` in the printed workspace, and check for the usual
flaws: a `done` task whose file is missing from `main` (unmerged branch), two competing copies of one
module, a passing test suite over a stub, and whether the top goal closed `done` vs `blocked`.

---

## The 10 goals

### 1. DPO fine-tuning — `dpo_tune`
> Build a small Python library `dpo_tune` that wraps preference fine-tuning with DPO (Direct Preference
> Optimization): a `Trainer` with `fit()`, a chosen/rejected pair dataset interface, a reference-model KL
> term, config dataclasses, and pytest tests. Pure-Python, CPU-only, mock the policy/reference models.

*Hard because:* a two-model objective plus the KL reference term is easy to fake — a good test must pin the math.

### 2. PPO rollout trainer — `ppo_lite`
> Build a library `ppo_lite` implementing PPO: a clipped surrogate objective, GAE(λ) advantage estimation,
> a rollout buffer, and a `train(env)` loop against a mockable environment. Config dataclasses + deterministic tests.

*Hard because:* GAE + clipping correctness; the advantage computation must be exact, not approximated.

### 3. Vector store with an ANN index — `tinyvec`
> Build a library `tinyvec`: an in-memory vector store with cosine/dot/L2 similarity, a navigable-small-world
> (HNSW-style) approximate index, disk persistence, and a `query(vec, k)` API. Tests assert recall vs brute-force.

*Hard because:* the index has to beat brute-force on speed while matching it on recall.

### 4. Typed tool-calling registry — `tooldeck`
> Build a library `tooldeck` that turns Python functions into LLM tools: derive a JSON Schema from type hints +
> docstring, register/dispatch by name, validate arguments, and retry-or-error on malformed calls. Tests cover
> schema generation and validation failures.

*Hard because:* type-hint → JSON-Schema reflection across nested/optional/union types.

### 5. Streaming LLM event parser — `streamparse`
> Build a library `streamparse` that folds a raw token/SSE stream into a typed async event stream: text deltas,
> tool-call deltas (assembled across chunks), usage accounting, and a terminal event. Tests feed canned chunk
> sequences and assert the reconstructed events.

*Hard because:* stateful incremental assembly of tool-calls split across chunk boundaries.

### 6. DAG task scheduler — `flowdag`
> Build a library `flowdag`: declare tasks with `depends_on`, run them in topological order with bounded
> parallelism, per-task retries with backoff, and result caching. Tests assert ordering, that a failed dep skips
> its dependents, and cache hits.

*Hard because:* topological order + concurrency + failure propagation at once (and it mirrors chorus itself).

### 7. Rate-limit / backoff middleware — `apiguard`
> Build a library `apiguard` for wrapping API clients: a token-bucket rate limiter, exponential backoff with
> jitter on 429/5xx, and a circuit breaker that opens after N failures and half-opens after a cooldown.
> Deterministic tests with a fake injected clock.

*Hard because:* time-based logic that must be testable without real sleeps (clock injection).

### 8. Semantic text chunker — `chunker`
> Build a library `chunker` for RAG: a recursive splitter that is sentence- and token-aware, honors a max-token
> budget with configurable overlap, and attaches start/end offsets + metadata to each chunk. Tests assert no
> chunk exceeds the budget and the offsets reconstruct the original text.

*Hard because:* the overlap + offset bookkeeping must be lossless and exact.

### 9. Preference-ranking eval harness — `prefrank`
> Build a library `prefrank`: ingest pairwise preference judgments, fit a Bradley-Terry / Elo ranking, compute
> inter-judge agreement (Cohen's κ), and emit a CLI Markdown report. Tests assert the ranking recovers a known
> order and κ on synthetic data.

*Hard because:* the statistical ranking must actually recover a planted ground-truth order.

### 10. Unified-diff patch engine — `patchkit`
> Build a library `patchkit` that parses unified diffs and applies them to files with fuzz matching, hunk-offset
> search, and structured conflict reporting (no silent corruption). Tests cover clean apply, fuzzy apply, and a
> rejected conflicting hunk.

*Hard because:* real diff parsing + fuzzy hunk relocation is fiddly and easy to get subtly wrong.

---

## Reading a run for flaws

| Signal to check | Flaw it reveals |
|---|---|
| A `done` leaf whose file is **absent from `main`** (no `merge chorus/<eid>`) | BUG-005 — `done` ≠ landed (unmerged author branch) |
| **Two copies** of one module (e.g. root vs package), `__init__` exporting neither | No cross-child file ownership / content reconciliation |
| Green test suite over a **stub** that ignores the brief | Command-DoD bypass (`evaluator_enabled` decided by the planner) |
| Top goal ends **`blocked`**, not `done` | BUG-007 — top-of-tree integrate churn |
| A code child assigned to **`pm`/`analyst`** → `rejected` | BUG-006 — deliverables to non-engineer roles |
| `docs/exec-plans/*.json`, `docs/evals/*.json` committed | harness artifacts leak into the deliverable repo |

See [`../post-dev-wiring.md`](../post-dev-wiring.md) for the full bug/finding catalogue.
