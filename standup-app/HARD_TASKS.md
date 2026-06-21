# Hard tasks — stress goals for `--org` mode

A catalogue of meaty, real build goals to throw at the 3-level org (`run.py --org`). Each is in
the spirit of the original GRPO probe: **multiple modules that must agree on an interface, a genuine
algorithm that can't be stubbed past a good test, and a clear "done" bar.** That combination is what
surfaces the org's hard failure modes — split-brain/duplicate modules, `done`-but-not-landed (unmerged
branch), off-brief output passing a bypassed DoD, and integrate churn that ends the goal `blocked`.

Two families:
- **10 library goals** — meaty single-package libraries, the original probe shape. **7 are Python; 3 are
  non-Python** (Rust #3, TypeScript #5, Go #6). For the non-Python ones the "done" bar becomes a real
  `cargo build` / `tsc` / `go test` + a manifest (`Cargo.toml` / `package.json` / `go.mod`), which surfaces
  the *no-packaging / empty-exports* flaw the moment a stub tries to pass.
- **Full-stack web app goals (5)** — frontend + backend + a *shared* contract. The shared schema is the
  #1 place a multi-agent org produces a split-brain interface, so these stress cross-child agreement hardest.

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

## The 10 library goals (7 Python · 3 non-Python)

### 1. DPO fine-tuning — `dpo_tune`
> Build a small Python library `dpo_tune` that wraps preference fine-tuning with DPO (Direct Preference
> Optimization): a `Trainer` with `fit()`, a chosen/rejected pair dataset interface, a reference-model KL
> term, config dataclasses, and pytest tests. Pure-Python, CPU-only, mock the policy/reference models.

*Hard because:* a two-model objective plus the KL reference term is easy to fake — a good test must pin the math.

### 2. PPO rollout trainer — `ppo_lite`
> Build a library `ppo_lite` implementing PPO: a clipped surrogate objective, GAE(λ) advantage estimation,
> a rollout buffer, and a `train(env)` loop against a mockable environment. Config dataclasses + deterministic tests.

*Hard because:* GAE + clipping correctness; the advantage computation must be exact, not approximated.

### 3. Vector store with an ANN index — `tinyvec` · **Rust** 🦀
> Build a Rust crate `tinyvec`: an in-memory vector store with cosine/dot/L2 similarity, a navigable-small-world
> (HNSW-style) approximate index, `bincode` disk persistence, and a `query(&[f32], k)` API. Ship a real
> `Cargo.toml` and a clean `lib.rs` public surface. `cargo test` asserts recall vs brute-force; the crate must
> build under `cargo build --release`.

*Hard because:* the index has to beat brute-force on speed while matching it on recall — now with ownership/
borrowing across a graph index, and a `cargo build` + `Cargo.toml` "done" bar that a stub-without-packaging fails outright.

### 4. Typed tool-calling registry — `tooldeck`
> Build a library `tooldeck` that turns Python functions into LLM tools: derive a JSON Schema from type hints +
> docstring, register/dispatch by name, validate arguments, and retry-or-error on malformed calls. Tests cover
> schema generation and validation failures.

*Hard because:* type-hint → JSON-Schema reflection across nested/optional/union types.

### 5. Streaming LLM event parser — `streamparse` · **TypeScript** 🟦
> Build an npm package `streamparse` that folds a raw SSE/token `ReadableStream` into a typed
> `AsyncIterable<StreamEvent>`: text deltas, tool-call deltas (assembled across chunks), usage accounting, and a
> terminal event. Ship a real `package.json` + `tsconfig.json`, build with `tsc` to `dist/`, and export the
> public types. `vitest` (or `node:test`) feeds canned chunk sequences and asserts the reconstructed events.

*Hard because:* stateful incremental assembly of tool-calls split across chunk boundaries — over Web Streams +
async iterables — with a `tsc` build + `package.json` exports as the "done" bar, exactly the packaging-and-exports flaw the GRPO run hit.

### 6. DAG task scheduler — `flowdag` · **Go** 🐹
> Build a Go module `flowdag`: declare tasks with `DependsOn`, run them in topological order over a worker pool
> (bounded by a semaphore / `GOMAXPROCS`), per-task retries with backoff, and result caching via a typed map.
> Ship `go.mod` and an exported API in `flowdag.go`. `go test ./...` asserts ordering, that a failed dep skips its
> dependents, and cache hits; `go vet` is clean.

*Hard because:* topological order + goroutine concurrency + failure propagation at once (it mirrors chorus itself),
and the shared result cache races easily — `go test -race` must be clean, a bar a stub can't sneak past.

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

## Full-stack web app goals (5)

Each is **frontend + backend + a shared contract**. Default stack: a TypeScript/Node backend (Express or
Fastify), a typed shared schema package, and a React frontend — single language end-to-end so the *contract*
is the only seam (Python/FastAPI is acceptable if the org prefers it). These stress the org's weakest spot:
three children must agree on one interface, and the place they diverge is invisible until the app is wired up.

### 11. Real-time collaborative board — `boardsync`
> Build a full-stack `boardsync`: a backend with a WebSocket channel, a typed shared event schema package, and a
> React frontend. Cards move between columns; every connected client sees a move within one round-trip; moves are
> persisted and replayed to a client that reconnects. Optimistic UI with server reconciliation. Tests: a headless
> client asserts a move broadcasts to a second client, and a reconnecting client rebuilds state from the log.

*Hard because:* frontend, backend, and the shared event schema must agree exactly — the #1 place a multi-agent
org produces a split-brain contract. Optimistic update + server reconciliation is genuine logic no stub fakes.

### 12. URL shortener + analytics — `shortlink`
> Build a full-stack `shortlink`: a REST backend that mints collision-safe base62 codes, 301-redirects, and
> records click events (ts, referrer, UA); a SQL schema with migrations; and a dashboard frontend charting
> clicks-over-time and top referrers. Tests assert code uniqueness under concurrency, redirect correctness, and
> that the analytics aggregation matches a known event fixture.

*Hard because:* the code generator must stay collision-safe under concurrency and the time-bucketed aggregation
must match exactly — both easy to fake past a happy-path test, and split across backend + DB + frontend.

### 13. Multi-tenant auth + RBAC notes — `tenantnotes`
> Build a full-stack `tenantnotes`: signup/login with hashed passwords + JWT sessions, tenant isolation (a user
> never sees another tenant's notes), role-based permissions (owner/editor/viewer), and a frontend with protected
> routes. Tests assert cross-tenant reads are denied, a viewer can't mutate, and an expired token is rejected.

*Hard because:* tenant isolation and RBAC are security-critical invariants that must hold across the API and the
data layer at once — a single missed check is a silent breach a happy-path test never catches.

### 14. Checkout / order state machine — `checkout`
> Build a full-stack `checkout`: a cart service, an inventory service with reservation (no overselling), an order
> state machine (pending → paid → fulfilled / cancelled), and an idempotent payment-webhook handler. Frontend cart
> + checkout flow. Tests assert no oversell under concurrent reserves, the state machine rejects illegal
> transitions, and a duplicated webhook is processed exactly once.

*Hard because:* reservation-under-concurrency + idempotent webhooks + a strict state machine are three real
correctness problems that must compose — the classic place stubs pass green while the system oversells.

### 15. Presence chat — `chatroom`
> Build a full-stack `chatroom`: WebSocket messaging with rooms, message persistence + history pagination,
> presence (who's online), and typing indicators, with a React frontend. Tests assert a message persists and
> paginates, presence updates when a socket drops, and typing events are debounced and broadcast.

*Hard because:* presence requires correct connection-lifecycle bookkeeping (joins, drops, heartbeats) shared
between server state and every client — drift is invisible until a socket dies mid-session.

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
| No `Cargo.toml` / `package.json` / `go.mod`, or it doesn't build (`cargo build` / `tsc` / `go build`) | no-packaging flaw — the non-Python deliverable isn't a real artifact |
| Frontend + backend disagree on the shared schema (a field the client sends the server never reads) | split-brain **contract** — the full-stack version of duplicate modules |

See [`../post-dev-wiring.md`](../post-dev-wiring.md) for the full bug/finding catalogue.
