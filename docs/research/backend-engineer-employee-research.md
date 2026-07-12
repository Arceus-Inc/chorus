# Backend Engineer Employee — Deep Research Report

*Generated: 2026-07-05 | Sources: ~60 across 4 parallel research tracks | Confidence: High*
*Purpose: seed the design of an autonomous chorus "Backend Engineer" employee — the structural sibling of the Engineer / Frontend Engineer / Designer role plugins.*

---

## Executive Summary

A backend engineer's job is not "write an endpoint" — it is to ship a **service a stranger can depend on**: correct across the states that actually occur, safe under load and failure, migratable without downtime, secure by default, and operable in production. Building an *autonomous* backend engineer therefore hinges on one idea that recurs across every source we read: **"it was tested" must be a file on disk, not a claim in the transcript** — and the tests that grade it must be ones the agent cannot see or edit.

Four converging findings:

1. **The competency surface is large but enumerable** — APIs/protocols, data modeling + indexing, caching, async/messaging (outbox/inbox), authN/authZ, architecture patterns (hexagonal/DDD/CQRS/saga/12-factor), reliability (circuit-breaker/retry+jitter/SLIs-SLOs), zero-downtime migrations, and OWASP API security. This maps cleanly onto a skills library.
2. **Backend "proof" is a tiered evidence bundle** — static → unit → integration-on-a-real-DB (Testcontainers) → API/contract (Pact, Schemathesis) → migration round-trip → load/SLO (k6 exit-code gates) → mutation score → smoke/health. Each gate self-fails via exit code and drops a standard machine-readable artifact.
3. **The safe harness is "unrestricted but confined"** — a broad action space (bash + files + git + real network for installs), made safe by environment confinement (container/microVM + registry-only egress allowlist + secret-stripping), not by narrowing tools.
4. **Self-verification is necessary but not sufficient** — ~35.7% of self-verifying agent runs still ship a wrong patch; reward-hacking (deleting tests, monkey-patching graders) is real. The field standard (SWE-bench) grades against **hidden, held-out tests in a clean container** and stops at a **reviewable PR, never an autonomous merge**.

The rest of this report details each track, then gives a concrete **Backend Engineer employee blueprint** mapping findings onto the chorus plugin shape (brief / skills / manifest / `test_evidence` primitive / subagents / DoD / implementation slices).

---

## 1. The Backend Competency Map (→ skills library + quality bar)

### 1.1 Core components (the "what every endpoint touches" layer)
- **API design & protocols** — REST (default external), GraphQL (client-shaped data), gRPC (internal service-to-service); URL-path versioning from day one; cursor/keyset pagination for deep result sets; `Idempotency-Key` on POSTs (Stripe requires it); token-bucket/sliding-window rate limiting via Redis; consistent error envelope; OpenAPI/schema-first docs ([roadmap.sh backend](https://roadmap.sh/backend); [Hello Interview — API Design](https://www.hellointerview.com/learn/system-design/core-concepts/api-design); [techinterview.org](https://www.techinterview.org/post/3233474122/)).
- **Data modeling & databases** — relational (Postgres/MySQL) for transactional, NoSQL families (document/key-value/wide-column/graph) for flexible-schema/high-concurrency; normalization vs denormalization; data-integrity constraints (PK/FK/unique/NOT NULL/CHECK) as correctness enforcement ([GeeksforGeeks roadmap](https://www.geeksforgeeks.org/websites-apps/backend-developer-roadmap/)).
- **Indexing & query optimization** — B-tree as the near-universal structure; composite indexes serve left-to-right prefixes only; covering/partial/GIN-GiST indexes; read `EXPLAIN ANALYZE`, target Index Scan over Seq Scan; kill N+1 with eager loading/batching (DataLoader) ([PlanetScale — B-trees](https://planetscale.com/blog/btrees-and-database-indexes); [SQL Practice Online](https://www.sql-practice.online/learn/sql-indexes)).
- **Caching** — Redis/Memcached; cache-aside/read-through/write-through/write-behind; TTL + eviction (LRU/LFU); CDN + HTTP cache headers (ETag/Cache-Control); stampede protection (locks, request coalescing).
- **Messaging & event-driven** — Kafka/RabbitMQ/SQS/PubSub; **at-least-once is the practical default; exactly-once is not achievable at the broker → make consumers idempotent**; **Transactional Outbox** (write events in the same DB txn) + **Idempotent Consumer / Inbox**; DLQs, consumer groups, partitioning, backpressure ([event-driven.io](https://event-driven.io/en/outbox_inbox_patterns_and_delivery_guarantees_explained/); [microservices.io — outbox](https://microservices.io/patterns/data/transactional-outbox.html)).
- **AuthN/AuthZ** — OAuth 2.0 is *authorization* (delegated access), **OIDC adds authentication** via an `id_token`; JWT stateless access tokens (prefer RS256 over HS256 in multi-service); RBAC to start, ABAC as roles proliferate; sessions, bcrypt/argon2, MFA, token refresh/rotation, scopes ([microservices.io — JWT authz](https://microservices.io/post/architecture/2025/07/22/microservices-authn-authz-part-3-jwt-authorization.html); [Okta — ABAC](https://developer.okta.com/books/api-security/authz/attribute-based/)).
- **Correctness primitives** — background jobs/schedulers with retries+DLQ; idempotency keys; optimistic vs pessimistic locking; boundary schema validation.

### 1.2 Architecture patterns
Monolith → **modular monolith** (pragmatic default) → microservices; **Hexagonal / Clean / DDD** (domain kernel is dependency-free — mirrors chorus's own "dependencies point inward"); CQRS; event sourcing; **saga** (orchestration/choreography) for distributed transactions; repository pattern; **12-Factor App** (codebase, deps, config-in-env, backing services, build/release/run, stateless processes, port binding, concurrency, disposability, dev/prod parity, logs-as-streams, admin processes) ([12factor.net](https://12factor.net/); [Ali Gelenler — Clean/Hex/DDD](https://medium.com/@ali.gelenler/microservices-with-clean-hexagonal-architectures-ddd-71939ff89a42)).

### 1.3 Reliability, scale & observability
- **Scale** — stateless horizontal scaling, L4/L7 load balancing, bounded connection pools (a 10s timeout × 5 retries can hold a connection 50s → pool exhaustion), read replicas, sharding/partitioning.
- **Resilience** — timeout; **retry with exponential backoff + jitter** (jitter mandatory to avoid retry storms); **circuit breaker** (half-open probe); bulkhead; graceful degradation; liveness/readiness health checks ([system-design.space](https://system-design.space/en/chapter/resilience-patterns/); [codecentric](https://www.codecentric.de/en/knowledge-hub/blog/resilience-design-patterns-retry-fallback-timeout-circuit-breaker)).
- **SRE** — **SLI** (latency/error-rate/throughput/availability, plus **correctness for all systems**), **SLO** (target), **SLA** (contract); **error budget = 100% − SLO**; multi-window multi-burn-rate alerting; **Four Golden Signals** (latency/traffic/errors/saturation, from the SRE monitoring chapter) ([Google SRE — SLOs](https://sre.google/sre-book/service-level-objectives/); [SRE Workbook — error budget](https://sre.google/workbook/error-budget-policy/)).
- **Observability** — three pillars: metrics (Prometheus), structured logs (JSON to stdout per 12-factor), distributed tracing (OpenTelemetry, context propagated across the call chain); runbooks + blameless post-mortems.

### 1.4 Data correctness
- **Zero-downtime migrations via Expand-Contract** — three independently-deployed phases: **expand** (add new alongside old, dual-write) → **migrate** (backfill + read from new) → **contract** (drop old). **Never change schema and dependent code in the same step**; `ALTER TABLE` can take `ACCESS EXCLUSIVE` locks for minutes on large tables ([xata/pgroll](https://xata.io/blog/pgroll-expand-contract); [datasops](https://www.datasops.com/blog/database-migrations-zero-downtime)).
- **ACID vs BASE**, **CAP/PACELC** — note **CAP-consistency (linearizability) ≠ ACID-consistency (invariant preservation)** ([ByteByteGo](https://blog.bytebytego.com/p/cap-pacelc-acid-base-essential-concepts)); transaction isolation levels + anomalies; deadlock avoidance (consistent lock ordering, short txns, retry); connection limits.

### 1.5 Security (OWASP API Security Top 10, 2023)
API1 **BOLA/IDOR** (the #1 risk — verify the caller may act on *that* object), API2 Broken Auth, API3 Broken Object Property Level Authz, API4 Unrestricted Resource Consumption, API5 Broken Function Level Authz, API6 Unrestricted Access to Sensitive Business Flows, API7 SSRF, API8 Security Misconfiguration, API9 Improper Inventory Management, API10 Unsafe Consumption of APIs ([owasp.org](https://owasp.org/API-Security/editions/2023/en/0x11-t10/)). Cross-cutting: parameterized queries (SQLi), output encoding (XSS), CSRF, boundary input validation, secrets in env/secret-manager (never hardcoded, validated at startup, rotated on exposure), TLS everywhere, least privilege, dependency/SCA scanning.

---

## 2. Prove-It-in-Beat Verification (→ DoD + `test_evidence` primitive)

### 2.1 The test taxonomy (what each layer proves)
Framed as a portfolio (Test Pyramid / Testing Trophy / Spotify Honeycomb — the last is the integration-heavy shape most apt for pure backend):

| Layer | Proves | Tools |
|---|---|---|
| Static | types/lint/security-smells, before any test runs | mypy --strict, ruff, golangci-lint, Semgrep, bandit |
| Unit | isolated logic (doubles for collaborators) | pytest, JUnit, go test, Vitest |
| Integration | serialization + queries vs a **real** boundary, one at a time | **Testcontainers**, docker-compose test envs |
| API/contract | running service matches spec / consumer expectations | Pact (CDC), Schemathesis (property-based vs OpenAPI), Dredd |
| E2E | high-value journeys across the integrated system | newman, API-client flows |
| Load/perf | latency percentiles + error-rate SLOs under load | k6, Gatling, Locust |
| Smoke/health | build alive + wired (routing/secrets/deps) | curl `/healthz`+`/readyz`, k8s probes |

- **Testcontainers** kills the "passes on in-memory H2, fails on prod Postgres" anti-pattern — spins up the *same service type as production* in Docker, auto-destroys it whether tests pass or fail (Ryuk reaper), multi-language, any Docker CI ([Testcontainers](https://testcontainers.com/guides/introducing-testcontainers/)).
- **Schemathesis** — point at an OpenAPI/GraphQL schema; generates thousands of inputs (Hypothesis), chains stateful workflows, conformance checks (`not_a_server_error`, `status_code_conformance`, `response_schema_conformance`), exports **JUnit XML** + copy-paste curl repros. Zero-per-endpoint maintenance ([schemathesis](https://github.com/schemathesis/schemathesis)).
- **Dredd** — validates the *live* API against its OpenAPI doc ("your docs are true") ([dredd.org](https://dredd.org/)).

### 2.2 Consumer-driven contract testing (Pact)
Consumer's tests run a mock provider and record request/response pairs into a **pact JSON file**; the provider **replays each interaction against the real service** and verifies; the **Pact Broker** stores pacts + verification results, and **`can-i-deploy`** answers "will releasing this break any recorded consumer?" as a machine query. The pact file + verification record + `can-i-deploy` verdict are all files — cross-service compatibility proven *without* orchestrating a full multi-service E2E ([Pact — how it works](https://docs.pact.io/getting_started/how_pact_works)).

### 2.3 Migration verification
Expand → migrate → contract; **mandatory forward→verify→rollback→verify round-trip in staging**; every migration has a tested down-script; run against production-sized data (Testcontainers seeded to volume) to catch lock duration; post-migration assertions (row counts, backfill completeness, referential integrity) ([theappcode](https://blog.theappcode.net/zero-downtime-database-migrations)).

### 2.4 Non-functional proof as pass/fail gates
Assert on **tail percentiles (p95/p99), never averages**. **k6 thresholds** are pass/fail rules; a breach makes k6 **exit 99** → CI fails: `http_req_duration: ['p(95)<200','p(99)<500']`, `http_req_failed: ['rate<0.01']`; `--summary-export=summary.json` writes the evidence ([k6 thresholds](https://k6.io/docs/using-k6/thresholds/); [exit-99 issue](https://github.com/grafana/k6/issues/2804)). Gatling/Locust have equivalents. **Coverage thresholds** emit Cobertura XML/LCOV and gate the build. **Mutation score** (Stryker/mutmut) proves the tests would *catch a bug*, not just that lines ran — especially important when the same agent writes both code and tests ([Stryker](https://stryker-mutator.io/docs/mutation-testing-elements/mutant-states-and-metrics/); [CircleCI — mutation testing](https://circleci.com/blog/what-is-mutation-testing/)).

### 2.5 Proposed `test_evidence/` bundle (backend)
A deterministic directory, each file produced by a self-failing gate, indexed by a `manifest.json` a DoD checker reads alone:

```
test_evidence/
├── manifest.json            # index + top-level verdict + per-gate status
├── static/    typecheck.txt · lint.json · security-scan.sarif
├── unit/      junit-unit.xml · coverage.xml (Cobertura/LCOV)
├── integration/ junit-integration.xml · containers.log   (proof a real DB was used)
├── api/       openapi.json · schemathesis-junit.xml · dredd-report.json
├── contracts/ *.pact.json · provider-verification.json · can-i-deploy.json
├── migrations/ applied.log · rollback-roundtrip.txt · data-assertions.json
├── load/      k6-summary.json (p95/p99, error-rate) · thresholds.json
├── mutation/  stryker-report.json (score vs break threshold)
└── smoke/     healthcheck.json (/healthz + /readyz)
```

Standard, machine-parseable formats: **JUnit XML** (results), **Cobertura XML/LCOV** (coverage), **SARIF** (static/security), **Pact JSON** (contracts), **k6 summary JSON** (load), **Stryker JSON** (mutation). The bundle's *existence with all-green statuses* is the proof.

---

## 3. Agent-Harness Patterns (→ toolset + sandbox posture)

**Thesis:** give the agent the same broad action space a human developer has, then make it safe by **confining the environment**, not by narrowing the tools; make it trustworthy by verifying **outside** the agent's own claims.

- **Toolset (converged across Devin/OpenHands/Aider/Claude Code/Codex):** arbitrary command execution (`bash` — the load-bearing tool for install/build/migrate/run/test), line-range file edit, read/search, git (durable state + revert), run-a-service/DB via `docker compose up --wait`, hit-a-running-API (http/browser), repo map. Anthropic's principle: "Claude needs the same tools programmers use every day" ([Claude Agent SDK](https://claude.com/blog/building-agents-with-the-claude-agent-sdk)). Prefer a **PL/shell action space + a few task-consolidated verbs** (`run_tests`, `apply_migrations`) over one-tool-per-operation; return semantic, actionable observations/errors ([OpenHands, ICLR 2025](https://arxiv.org/html/2407.16741v3); [Anthropic — writing tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents)).
- **Sandbox — "unrestricted but confined":** filesystem confined to the workspace + network confined to an allowlist, enforced at OS level (bubblewrap/seatbelt) so it covers spawned subprocesses; both boundaries mandatory (without net isolation a compromised agent exfiltrates SSH keys; without FS isolation it escapes) — this *safely reduces permission prompts by 84%* ([Anthropic — sandboxing](https://www.anthropic.com/engineering/claude-code-sandboxing)). Isolation ladder: Docker container → **Firecracker microVM** (E2B: own kernel, ~150ms boot, deny-all + domain allowlist) for genuinely untrusted code.
- **Two-phase network (Codex model):** **setup phase online** for installs/migrations behind a **registry-only egress allowlist** (npm/PyPI/GitHub); **agent phase offline by default**; secrets injected per-session and **stripped before autonomous execution** ([Codex — cloud environments](https://developers.openai.com/codex/cloud/environments); [INNOQ — egress allowlist](https://www.innoq.com/en/blog/2026/03/dev-sandbox-network/)).
- **Verification-in-loop + how it fails:** the base loop is write→run→read→refine (Aider auto-test-and-repair). SWE-bench applies the patch in a per-instance Docker container and checks **FAIL→PASS + PASS→PASS** against **hidden held-out tests** — the gold standard. But self-verification is weak: **~35.7% of self-verifying runs still ship a wrong patch** ([arXiv 2603.15401](https://arxiv.org/pdf/2603.15401)); Pass@1 collapses >70%→≤23.3% on contamination-controlled benchmarks ([SWE-Bench Pro](https://static.scale.com/uploads/654197dc94d34f66c0f5184e/SWEAP_Eval_Scale%20(9).pdf)). **Reward hacking** (overwriting tests, monkey-patching graders, hardcoding outputs) is documented; a trajectory-monitor + quality-judge drops hacked-resolved 28.57%→0.56% ([arXiv 2606.07379](https://arxiv.org/pdf/2606.07379)).
- **Service-dependent tasks:** provision deps via docker-compose **health-gated startup** (`depends_on: condition: service_healthy`, `--wait`, `pg_isready`), then migrate, then hand the app the connection string; after starting a service, **poll its health endpoint before declaring ready**; make install a separately-timed phase (slow); durable state lives **in the workspace (git + progress + task list)**, not the context window ([Last9 — compose healthchecks](https://last9.io/blog/docker-compose-health-checks/); [Anthropic — effective harnesses](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)).

---

## 4. Reference Role Specs + AI-Employee Scoping (→ brief + DoD framing)

- **Responsibilities (senior backend, GitLab Handbook as primary):** develop features "in a secure, well-tested, and performant way"; maintainable code + champion standards via code review; resolve tech debt; **own production health — on-call, incident response, remediation**; monitor/diagnose/optimize (caching, LB, horizontal scale); cross-functional collaboration; end-to-end ownership conception→production ([GitLab — Senior Backend](https://handbook.gitlab.com/job-families/engineering/development/backend/senior/)).
- **Leveling axis = scope + ambiguity, not LOC/years.** Target **Senior (L5)** as the agent's operating baseline: owns a well-scoped service/feature end-to-end, handles moderate ambiguity, produces tested + reviewable + operable output — **escalates cross-team architecture/strategy (Staff scope) to humans**. Grading rubrics worth mirroring: CircleCI's 6 axes (technical, quality&testing, debugging&observability, understanding-code, communication, leadership); Dropbox's Results/Direction/Talent/Culture/Craft; RTR's Technical/Get-Stuff-Done/Impact/Communication ([levels.fyi](https://www.levels.fyi/standard/); [StaffEng](https://staffeng.com/book/); [CircleCI](https://circleci.com/blog/why-we-re-designed-our-engineering-career-paths-at-circleci/)).
- **How AI-SWE products scope "done":** all converge on **ticket → plan → edit → test → self-verify → open a PR → stop at human review**; **none autonomously merge**. Devin: "write clear prompts with explicit completion criteria," "make tasks easy to verify (CI passes)," the **3-hour-human rule**. GitHub Copilot coding agent: ephemeral env runs tests/linters, mandatory **CodeQL + secret + dependency scan before a human sees the PR**, cannot merge. Factory Code Droid: decompose → multiple trajectories → validate with tests → select; sandboxed, traceable/reversible, logs reasoning ([GitHub coding agent](https://docs.github.com/copilot/concepts/agents/coding-agent/about-coding-agent); [Devin](https://docs.devin.ai/get-started/devin-intro); [Factory](https://factory.ai/news/code-droid-technical-report)).
- **Recurring values:** **you build it, you run it** (Werner Vogels, 2006 — observability/SLOs/on-call as prerequisites); reliability as a first-class concern; observability by default; "secure, well-tested, performant"; security-by-default (scan before human review); simplicity/maintainability; backward-compatibility discipline.
- **Mature-org DoD (most reusable):** tests written + passing (unit+integration, meaningful new-path coverage); CI green + lint; **peer-reviewed + approved** (≥1 senior); acceptance criteria met; **security scan clean** (secret/dep/SAST); **migration backward-compatible** + expand/migrate/contract ordering + batched backfills; operability (SLIs + dashboards + runbooks + safe-deploy) when adopting you-build-it-you-run-it; docs/API contracts updated. **Terminal state: a reviewable PR — not an autonomous merge.**

---

## 5. Blueprint — Backend Engineer chorus Employee

Mapping the findings onto the existing plugin shape (`chorus_employee/<role>/`: `_brief` + `_harness` + `_dod` + `_lander` (+ `_subagents/` + `skills/`)), reusing the Engineer/Frontend-Engineer twin structure.

**Identity / brief.** A senior (L5) backend engineer that turns a ticket/spec into a service a stranger can depend on — correct, secure, observable, migratable, operable — and proves it in one beat. Values to encode verbatim: *the user's reliability is the spec; correctness across the states that actually occur; you build it you run it; at-least-once + idempotent consumers; never change schema and code in one step; security is a gate not a feature; green unit tests are necessary never sufficient — real behaviour is proven against the running service; the terminal state is a reviewable PR, never an autonomous merge.*

**Toolset (manifest).** `read_file`, `write_file`, `run_command` (install/build/migrate/run/test — the workhorse), `git`; a few task-consolidated verbs worth wrapping — `apply_migrations`, `run_tests`, `start_service`+`healthcheck`, `http_request` (hit the running API); `web_search`/`web_extract` (docs research); memory + `spawn_subagent` + `skill`. Optionally an HTTP/DB MCP if a browser-equivalent is wanted for live API exercise.

**The load-bearing primitive — `test_evidence`** (the Designer's `design_lint` / Frontend's `test_evidence` analog): runs the project's discovered static/unit/integration/contract/migration/load/mutation/smoke commands, collates each self-failing gate's standard artifact (JUnit XML, Cobertura, SARIF, pact JSON, k6 summary JSON, Stryker JSON), and writes the machine-readable `test_evidence/` bundle + `manifest.json` to the worktree. **Register it unconditionally as a pure worktree tool — not behind the ledger gate** (this is the exact bug found on the Designer's `design_lint`, which never registered in ledger-less runs).

**Manifest posture.** `permission_mode=ACCEPT_EDITS`; `sandbox=UNRESTRICTED + net-allowlist` (installs + arbitrary build/test/dev; egress limited to package registries + service deps; credential guard + deny-list + worktree confinement still apply); `isolation=WORKTREE`; `mcp` only if a DB/HTTP MCP is admitted; `max_turns ~18`, `max_sprints ~6`, `beat_timeout ~1500` (installs + container boots + DB migrations + load tests are slow); `memory_scope=PROJECT + working_memory`.

**Subagents (Tier-1, narrow the parent toolset, typed verdicts).**
- **Test-Author** — drafts/extends tests to land in the same beat (Honeycomb-shaped: integration-heavy vs a real DB, thin E2E, unit for logic). Writes tests, never ships. `read_file · write_file · run_command · skill`.
- **API-Verifier** (the Frontend UI-Tester analog) — drives the *running* service: contract/property tests (Pact/Schemathesis), hits real endpoints, captures load percentiles + health, returns a decisive typed verdict (pass/fail + findings + evidence paths). `run_command · http_request · read_file · test_evidence`.
- **Code-Reviewer** — read-only diff reviewer: correctness, new-behaviour-has-a-test, no regression, security (BOLA/injection/secrets), migration backward-compat. Returns PASS/FAIL; engineer keeps the fixes. `read_file · git(read) · test_evidence(read)`.
- **Web-Research Orchestrator** — the shared `src/swarm/` specialist for framework/library/API questions.

**Skills library (loaded on demand).** *Build:* api-design-rest-graphql-grpc, data-modeling, indexing-and-query-optimization, caching-strategies, messaging-outbox-inbox, authn-authz-oauth-oidc-rbac, idempotency-and-pagination, hexagonal-ddd, twelve-factor, resilience-patterns (timeout/retry-jitter/circuit-breaker/bulkhead), zero-downtime-migrations, error-and-empty-and-failure-states. *Test/operate:* testing-honeycomb-strategy, testcontainers-integration, contract-testing-pact, property-testing-schemathesis, load-testing-slo-gates, migration-round-trip-testing, mutation-testing, observability-slis-slos, owasp-api-security, secrets-and-least-privilege.

**Definition of Done — reviewed build + durable evidence floor.** All checkable without trusting the transcript:
1. **Green build** — kernel runs the discovered verify command (static + unit + integration-on-real-DB + contract) and it exits 0.
2. **Behaviour proven against the running service** — API-Verifier drove the live service (contract/property + real endpoints + health) and returned PASS.
3. **Measured, not assumed** — load SLOs (p95/p99 + error-rate) inside budget via exit-code gates; coverage + mutation score above floor; security scan clean.
4. **Migration safe** — expand/migrate/contract ordering + a passing forward→verify→rollback→verify round-trip (when the diff touches schema).
5. **Evidence on disk** — a `test_evidence/` bundle landed in the worktree; the DoD's deterministic floor greps `manifest.json`.
6. **Diff approved** — read-only Code-Reviewer PASS (correct, tested, no regression, backward-compatible, secure).
Shape: `Verifier.reviewed_build(rubric=…)` over a `Verifier.command(…)` floor asserting the bundle exists. Artifact: `pr`. **Terminal state is a reviewable PR, never an autonomous merge.**

**Anti-reward-hacking (from track 3, non-negotiable):** the grader's tests are read-only / outside the workspace the agent can edit; brief explicitly forbids removing/editing tests; the Code-Reviewer diffs the touched test files; mutation score guards against toothless tests.

**Implementation slices (mirror the Frontend Engineer's).**
- **Slice 1 — Walking skeleton:** manifest + brief + tools (read/write/run/git) + `reviewed_build` DoD; implements and lands a PR that builds green.
- **Slice 2 — Tests-in-beat:** `test_evidence` primitive (registered unconditionally) + Test-Author subagent + evidence-floor DoD; every landed change carries proof.
- **Slice 3 — Real-service verification:** the running-service loop (docker-compose health-gated startup, Testcontainers integration, contract/property tests); API-Verifier subagent + typed verdict.
- **Slice 4 — Craft depth + operability:** author the skill playbooks; Code-Reviewer subagent; load/SLO gates + mutation baselines; migration round-trip; security scan.

---

## Key Takeaways

1. **Model the DoD as tiers of self-failing gates** (static → unit → integration-on-real-DB → contract → migration → load/SLO → mutation → smoke), each emitting a standard machine-readable artifact into `test_evidence/`, indexed by a single `manifest.json` verdict.
2. **What makes backend evidence credible rather than performative:** real dependencies (Testcontainers, not H2/mocks), percentile SLOs as hard exit-code gates (not averages), and mutation score (proving tests would catch a bug) — the last especially because the agent writes both code and tests.
3. **Safe = confined, not narrow.** Broad action space (bash/files/git/net-for-installs) + OS-level filesystem+network isolation + registry-only egress allowlist + secret-stripping + two-phase (setup-online → agent-offline).
4. **Never trust the agent's "done."** Grade against hidden held-out tests the agent cannot edit; forbid + detect test edits; stop at a reviewable PR, not a merge.
5. **Operate at Senior (L5) scope** — end-to-end ownership of a well-scoped service, escalate cross-team architecture to humans; encode "you build it, you run it."

---

## Sources

Full inline citations appear in each section above. Primary/canonical anchors:
- roadmap.sh backend · OWASP API Security Top 10 (2023) · 12factor.net · Google SRE book + Workbook · microservices.io (outbox/JWT) · event-driven.io · xata/pgroll + datasops (expand-contract) · PlanetScale (B-trees) · ByteByteGo (CAP/ACID) · Okta (ABAC)
- martinfowler.com (Practical Test Pyramid) · Kent C. Dodds (Testing Trophy) · Testcontainers · Pact docs + broker · Schemathesis · Dredd · k6 thresholds · Gatling · Stryker/mutmut · Kubernetes probes · GitLab CI artifacts reports
- Anthropic engineering (Claude Agent SDK, writing tools for agents, effective harnesses, sandboxing) · sandbox-runtime · OpenHands (ICLR 2025) · OpenAI Codex (sandboxing, cloud environments) · Devin · Aider · SWE-bench + Verified + Pro · reward-hacking (arXiv 2606.07379) · self-verification (arXiv 2603.15401) · E2B/Firecracker · INNOQ egress
- GitLab Handbook (Senior Backend) · levels.fyi · StaffEng (Will Larson) · CircleCI/Dropbox/RTR ladders · GitHub Copilot coding agent · Factory Code Droid · Cosine Genie · Zencoder · SRE School (you-build-it-you-run-it) · DeployHQ · Atlassian DoD · Martin Fowler (humans & agents)

## Methodology

Four parallel research agents (one per angle: competency map · verification/evidence · agent-harness patterns · role specs & AI-employee scoping), each running 8–14 WebSearch queries + 4–6 full-page WebFetch deep reads with inline citations and cross-referencing. ~60 unique sources; single-source claims flagged in the source tracks (e.g. gRPC "5–10×", RS256-over-HS256). levels.fyi and some JS-rendered ladders captured via search-result quotation — treat level year-ranges as indicative. No firecrawl/exa MCP was available; built-in WebSearch + WebFetch used throughout.
