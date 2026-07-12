# Backend Engineer — the 28-skill craft library: authoring map

*Generated 2026-07-06 · 6 parallel research agents · ~28 canonical sources · Confidence: High.*

The source material for authoring the §08 skill playbooks (`chorus_employee/backend_engineer/skills/`).
For each skill: **canonical source(s)** to fork-not-invent from, the **core rules** to encode, and the
**machine-checkable output** (a `code_quality`/`test_evidence`-style gate) vs. **judgment** (needs the
Code-Reviewer's eye). Two adjacent skills already exist: `verifying-any-stack`, `structuring-any-service`.

The comprehensive **28** = the spec's **25** + **3 additions** (rate-limiting, transactional-outbox,
backpressure — the gaps every agent flagged; justified at the bottom).

---

## A · API & data

### api-design-rest-graphql-grpc
- Sources: [Google Cloud API Design Guide](https://docs.cloud.google.com/apis/design) · [Zalando RESTful Guidelines](https://opensource.zalando.com/restful-api-guidelines/) · [grpc.io intro](https://grpc.io/docs/what-is-grpc/introduction/)
- Rules: plural-noun collections, no verbs in paths, 5 standard methods (custom `:action` only when nothing fits); only correct HTTP codes (201/204/400/401/403/404/409/422/429+Retry-After/5xx), never 200-with-error-body; cursor pagination default over offset; version by backward-compatible extension first, media-type versioning not `/v1/` for breaks; errors as RFC 9457/7807 Problem JSON one-envelope, no stack traces; pick by consumer (REST public, GraphQL diverse clients, gRPC internal svc-to-svc).
- Gate: REST → OpenAPI + **Spectral** ruleset; gRPC → **buf lint** + **buf breaking**; GraphQL → **graphql-schema-linter**. Protocol choice = judgment.

### data-modeling
- Sources: [PostgreSQL Constraints](https://www.postgresql.org/docs/current/ddl-constraints.html) · [MongoDB Data Modeling](https://www.mongodb.com/docs/manual/data-modeling/) · [Wlaschin — Making Illegal States Unrepresentable](https://fsharpforfunandprofit.com/posts/designing-with-types-making-illegal-states-unrepresentable/)
- Rules: normalize by default, denormalize only under a measured read pattern; push every invariant to a DB constraint (NOT NULL/FK+ON DELETE/CHECK/UNIQUE) not app code; model either-or as a union/sum type not nullable-validated-at-runtime; relational for joins/integrity vs document for access-together/polymorphic; embed 1:1 + bounded 1:many, reference many:many/unbounded/churning; named deletion semantics over orphan cleanup in app.
- Gate: constraints self-enforce at write; migration lint `sqlfluff`/`squawk`/`atlas`; type-level illegality → `mypy --strict`. Normalization degree = judgment.

### indexing-and-query-optimization
- Sources: [Use The Index, Luke! — WHERE clause + covering index](https://use-the-index-luke.com/sql/where-clause) · [PostgreSQL EXPLAIN](https://www.postgresql.org/docs/current/using-explain.html) · [MySQL index usage](https://dev.mysql.com/doc/refman/8.0/en/mysql-indexes.html)
- Rules: index WHERE/JOIN/ORDER BY/GROUP BY columns; composite obeys leftmost-prefix, equality/most-selective first; read EXPLAIN, hunt Seq Scan on selective hot queries; covering index for index-only scan (mind write cost); keep predicates sargable (no `fn(col)` in WHERE); kill N+1 with eager/batched IN, assert bounded query count.
- Gate: `EXPLAIN (ANALYZE, BUFFERS)` assert no Seq Scan on hot table / cost under threshold; query-count assertion (`assertNumQueries`) catches N+1; `pg_stat_statements` in prod. Which columns = judgment.

### idempotency-and-pagination
- Sources: [Stripe idempotent requests](https://docs.stripe.com/api/idempotent_requests) · [Brandur — idempotency](https://stripe.com/blog/idempotency) · [Shopify GraphQL pagination](https://shopify.dev/docs/api/usage/pagination-graphql)
- Rules: client-generated key (UUIDv4, ≤255 chars, no PII) on mutating POSTs only; server stores key→status+body, replay cached result incl. 500s, persist only after execution begins; compare params vs original, reject mismatch; TTL-expire keys (≥24h); don't key already-idempotent GET/PUT/DELETE; cursor/keyset pagination for deep data (opaque `after`=endCursor + stable sort + hasNextPage).
- Gate: fire same POST twice w/ one key → identical status+body AND exactly one row; walk all pages via cursor → no dup/skip vs full set, incl. under mid-walk insert/delete.

## B · Scale & async

### caching-strategies
- Sources: [AWS ElastiCache strategies](https://docs.aws.amazon.com/AmazonElastiCache/latest/mem-ug/Strategies.html) · [AWS caching best practices](https://aws.amazon.com/caching/best-practices/) · [antirez — cache stampede](https://redis.antirez.com/fundamental/cache-stampede-prevention.html)
- Rules: default cache-aside/lazy (miss→query→populate, fails to slower not broken); always a TTL; write-through only for hot must-be-fresh, pair w/ lazy+TTL; invalidate by delete-and-repopulate not in-place; stampede defense — jitter TTLs + mutex (`SET NX PX`)/probabilistic early recompute/coalescing; structured keys, negative-cache misses (null sentinel short TTL).
- Gate: test write path invalidates key (read-after-write fresh); cache hit-ratio metric with floor. TTL/key/stampede-choice = judgment.

### messaging-outbox-inbox
- Sources: [microservices.io — transactional outbox](https://microservices.io/patterns/data/transactional-outbox.html) · [microservices.io — idempotent consumer](https://microservices.io/patterns/communication-style/idempotent-consumer.html) · [Confluent — exactly-once in Kafka](https://www.confluent.io/blog/exactly-once-semantics-are-possible-heres-how-apache-kafka-does-it/)
- Rules: write domain change + outbox row in ONE local tx (send iff commit); separate relay (CDC/log-tail or polling) publishes; assume at-least-once → consumers MUST be idempotent; dedup on message id in PROCESSED_MESSAGES `(subscriberId, messageID)` PK; exactly-once *delivery* impossible → exactly-once *processing* via dedup + producer sequence; emit stable unique id at outbox-write.
- Gate: domain+outbox commit atomically (roll back tx → neither persists); re-deliver same id → no-op (side effect once).

### resilience-patterns
- Sources: [AWS Builders' Library — timeouts/retries/backoff+jitter](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/) · [AWS — exponential backoff and jitter](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/) · [Fowler — CircuitBreaker](https://martinfowler.com/bliki/CircuitBreaker.html)
- Rules: explicit timeout on EVERY remote call; retry only idempotent ops, cap attempts + retry budget/token-bucket; backoff exponential w/ FULL jitter `random(0, min(cap, base·2^n))`; circuit breaker closed→open→half-open, fail fast past threshold; degrade gracefully when open (cached/default/queued); bulkhead isolate pools per dependency.
- Gate: grep every outbound call sets a timeout (no bare `requests.get(`/zero-timeout client); retry sites use jittered-backoff helper + cap; fault-injection test → breaker opens, caller returns fallback not hang. Degradation acceptability/bulkhead sizing = judgment.

### connection-pool-discipline
- Sources: [HikariCP — pool sizing](https://github.com/brettwooldridge/HikariCP/wiki/About-Pool-Sizing) · [brandur — managing Postgres connections](https://brandur.org/postgres-connections) · [PostgreSQL connection settings](https://www.postgresql.org/docs/current/runtime-config-connection.html)
- Rules: size pools SMALL `((cores*2)+spindles)` (saturated small beats large); acquire-use-release in tightest scope; never hold a connection across a slow call/user-wait; front PG with PgBouncer (txn mode) at many clients; cap total app pool below PG `max_connections` summed across instances; pool-locking size `Tn×(Cm−1)+1`.
- Gate: HikariCP `leakDetectionThreshold` + pool active/idle/pending metric; test active-connection count returns to baseline after a request. Sizing = judgment.

## C · Architecture

### hexagonal-ddd
- Sources: [Cockburn — Hexagonal Architecture](https://alistair.cockburn.us/hexagonal-architecture/) · [Fowler — AnemicDomainModel](https://martinfowler.com/bliki/AnemicDomainModel.html) · [cosmicpython Ch2/4](https://www.cosmicpython.com/book/chapter_02_repository.html)
- Rules: dependencies point INWARD (domain depends on nothing); ports = domain-owned interfaces, adapters implement (injected not constructed); RICH domain (invariants ON entities), thin service = orchestration; aggregate = consistency boundary (one root/tx, external refs by root ID); value objects immutable equality-by-value; bounded context = one ubiquitous language, integrate via anti-corruption layer.
- Gate: **import-linter**/dependency-cruiser — domain imports nothing from adapters/infra (CI fail on violation). Aggregate-per-tx = judgment.

### twelve-factor
- Sources: [12factor.net](https://12factor.net/) · [Config](https://12factor.net/config) · [Backing Services](https://12factor.net/backing-services)
- Rules: config in env (repo open-sourceable); backing services = attached resources by URL; processes stateless share-nothing (no sticky/local disk); dev/prod parity; logs = event streams to stdout; explicit isolated deps (lockfile), admin as one-off in same env.
- Gate: secret/config-literal scan (ties to `secret_scan`); assert boots from env only; assert logs→stdout.

### cqrs-and-saga
- Sources: [Fowler — CQRS](https://martinfowler.com/bliki/CQRS.html) · [microservices.io — Saga](https://microservices.io/patterns/data/saga.html) · [microservices.io — CQRS](https://microservices.io/patterns/data/cqrs.html)
- Rules: CQRS is a LOCAL optimization not default (try read-replica first; misapplied = complexity); saga = local txns + compensations (no auto rollback); choreography simple / orchestration complex; atomic update-DB-and-emit via outbox (NEVER dual write); sagas lack Isolation (ACD) → countermeasures; compensations idempotent+retryable, pivot txn = point of no return.
- Gate: inject mid-saga failure → assert fully compensated; assert outbox row same tx. CQRS-justified = judgment.

### repository-pattern
- Sources: [cosmicpython Ch2 Repository](https://www.cosmicpython.com/book/chapter_02_repository.html) · [cosmicpython Ch6 UoW](https://www.cosmicpython.com/book/chapter_06_uow.html) · [Fowler — Repository (PoEAA)](https://martinfowler.com/eaaCatalog/repository.html)
- Rules: repo = collection-like abstraction (domain talks to ABC/Protocol, not ORM/SQL); UoW owns tx boundary via `with uow:` (matches `SqliteLedger.transaction()`); test with FAKES not mocks (in-memory repo, assert end state); fake honors same Protocol; one repo per aggregate root; DIP — inject repo/UoW via `__init__`.
- Gate: shared contract test parametrized over `[FakeRepo, SqlRepo]` both pass; import-linter domain-no-ORM.

## D · Data correctness

### zero-downtime-migrations
- Sources: [PlanetScale — backward-compatible changes](https://planetscale.com/blog/backward-compatible-databases-changes) · [PlanetScale — safely making changes](https://planetscale.com/blog/safely-making-database-schema-changes) · [GitHub — gh-ost](https://github.blog/2016-08-01-gh-ost-github-online-migration-tool-for-mysql/)
- Rules: decouple schema change from code deploy; expand→contract order (add nullable/default → dual-write → batched backfill → switch reads → stop old write → drop old); every step backward-compatible; backfill bounded batches w/ pauses; destructive ops (drop/rename/narrow/add-NOT-NULL) breaking → split; new column nullable then NOT NULL post-backfill+verify.
- Gate: migration linter (**squawk**/planetscale/django-migration-linter) fails CI on unsafe ops; assert version N & N-1 both green vs intermediate schema.

### acid-isolation-and-deadlocks
- Sources: [PostgreSQL — Transaction Isolation](https://www.postgresql.org/docs/current/transaction-iso.html) · [PostgreSQL — Explicit Locking](https://www.postgresql.org/docs/current/explicit-locking.html) · Berenson et al., *Critique of ANSI SQL Isolation Levels*
- Rules: pick level for the anomaly to exclude (RC→RR→Serializable); RR/Serializable can fail SQLSTATE 40001 → app MUST catch+abort+retry whole txn w/ backoff; SSI = predicate locks (budget retry %); prevent deadlock via consistent lock ordering (victim 40P01 → retry); short/narrow txns, no locks across network/user-wait; enforce invariants via DB constraint/unique index + `INSERT...ON CONFLICT` (EAFP), not check-then-act.
- Gate: retry wrapper on 40001/40P01 bounded attempts (test forces serialization failure); test unique constraint blocks concurrent double-insert.

### migration-round-trip-testing
- Sources: [pgroll — rollback strategy levels](https://pgroll.com/blog/levels-of-a-database-rollback-strategy) · [Redgate/Flyway — roll back or fix forward](https://www.red-gate.com/hub/product-learning/flyway/failed-flyway-database-deployments-roll-back-or-fix-forward/) · [PlanetScale — test on clone](https://planetscale.com/blog/safely-making-database-schema-changes)
- Rules: forward→verify→rollback→verify as one CI gate (untested down = hope); run vs production-VOLUME clone; rollback preserves DATA not just DDL (assert row counts/checksums); prefer fix-forward for applied destructive; assert schema parity (byte-match declared schema, the `test_schema_parity.py` discipline); migrations idempotent/re-runnable.
- Gate: CI migrate up → schema+data asserts → migrate down → assert baseline restored; schema-parity test; large fixture measures lock/backfill under volume.

## E · Testing & proof

### testing-honeycomb-strategy
- Sources: [Spotify — Testing of Microservices](https://engineering.atspotify.com/2018/01/testing-of-microservices) · [Fowler — Diverse Shapes of Testing](https://martinfowler.com/articles/2021-test-shapes.html) · [Fowler — TestPyramid](https://martinfowler.com/bliki/TestPyramid.html)
- Rules: service/API boundary IS the unit; integration = fat middle (real contracts+own DB, no peer system); minimize impl-detail unit tests; avoid "integrated tests" (pass/fail depends on another live system → aim zero); reuse shared contract fixtures; bar is fast/reliable/isolated/clear-cause not exact ratio.
- Gate: judgment for shape. Proxies: integration tier hits a real container (see testcontainers); grep suite for staging/peer hostnames (= forbidden integrated test); suite wall-clock + flake low.

### testcontainers-integration
- Sources: [Testcontainers — startup & waits](https://java.testcontainers.org/features/startup_and_waits/) · [testcontainers.com getting started](https://testcontainers.com/getting-started/) · [testcontainers-python](https://testcontainers-python.readthedocs.io/en/latest/)
- Rules: run real dep in throwaway container, pinned tag (never latest); scope lifecycle to test via context manager (auto-destroy); never hardcode ports — read mapped host+port back; explicit wait strategy — log/healthcheck readiness NOT port-open (port-open lies for stateful stores); prove real DB via container logs ready-banner.
- Gate: **container logs** — daemon pulls pinned image + logs contain server ready-banner (Postgres "ready to accept connections", Kafka "started", Redis "Ready to accept connections"). Assert on banner = proof a real datastore ran.

### contract-testing-pact
- Sources: [docs.pact.io](https://docs.pact.io/) · [Pact — can-i-deploy](https://docs.pact.io/pact_broker/can_i_deploy)
- Rules: consumer-driven code-first (consumer test vs mock provider GENERATES the pact, never hand-author); provider verifies by replaying interactions; scope = exactly what consumer uses; publish pacts+verification to Broker (Matrix); gate deploy with can-i-deploy vs target env, record-deployment after; version pacticipants by git SHA.
- Gate: `pact-broker can-i-deploy --pacticipant N --version V --to-environment ENV` exits 0 iff all required verifications passed → CI gate.

### property-testing-schemathesis
- Sources: [Schemathesis docs](https://schemathesis.readthedocs.io/en/stable/) · [checks reference](https://schemathesis.readthedocs.io/en/stable/reference/checks/) · [CLI reference](https://schemathesis.readthedocs.io/en/stable/reference/cli/)
- Rules: derive tests from the schema (OpenAPI/GraphQL), Hypothesis auto-generates + threads server values; keep all checks on (not_a_server_error, response_schema_conformance, status/content-type/headers conformance); negative testing (negative_data_rejection + positive_data_acceptance); run in CI vs live instance, each finding ships a curl repro.
- Gate: `schemathesis run <schema>` exits non-zero on any check failure (5xx or non-conformance) → CI gate.

### load-testing-slo-gates
- Sources: [k6 Thresholds](https://grafana.com/docs/k6/latest/using-k6/thresholds/) · [k6 — when thresholds fail](https://grafana.com/docs/learning-hub/k6-performance-testing/03-establishing-a-baseline/19b-when-thresholds-fail/) · [Gatling assertions](https://docs.gatling.io/concepts/assertions/)
- Rules: derive thresholds from SLO not guess; k6 `<agg> <op> <value>` form — `http_req_duration ['p(95)<200','p(99)<300']`, `http_req_failed ['rate<0.01']`; breach = build failure (non-zero exit, never parse graphs); `abortOnFail:true`; match load type (smoke/avg/stress/spike/soak); Gatling equiv `global().responseTime().percentile(95).lt(200)`.
- Gate: `k6 run` exits 99 on breach (0=pass) → CI gate. Values p95<200ms, p99<300ms, err<1%.

### mutation-testing
- Sources: [Stryker — mutant states & metrics](https://stryker-mutator.io/docs/mutation-testing-elements/mutant-states-and-metrics/) · [Stryker — configuration](https://stryker-mutator.io/docs/stryker-net/configuration/) · [mutmut docs](https://mutmut.readthedocs.io/en/latest/index.html)
- Rules: measures test *effectiveness* (strong suite KILLS injected faults) not execution; prefer mutation score over coverage (mutant survives in covered-but-unasserted code); read states killed/survived/no-coverage/timeout, act on survivors+no-coverage; gate on break threshold; scope to changed files (expensive); tool per stack (Stryker JS/.NET, mutmut/cosmic-ray Py, PIT Java).
- Gate: Stryker `thresholds.break: N` exits non-zero when score<N% (score = detected/valid×100). mutmut/PIT `mutationThreshold` equivalent.

## F · Security & operability

### owasp-api-security
- Sources: [OWASP API Security Top 10 2023](https://owasp.org/API-Security/editions/2023/en/0x11-t10/) · [API1 BOLA](https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/) · [project home](https://owasp.org/www-project-api-security/)
- The 2023 list: API1 BOLA · API2 Broken Auth · API3 BOPLA · API4 Unrestricted Resource Consumption · API5 BFLA · API6 Sensitive Business Flows · API7 SSRF · API8 Security Misconfig · API9 Improper Inventory · API10 Unsafe Consumption of APIs.
- Rules: authorize EVERY object access server-side (never infer from ID) — BOLA; property-level authz + whitelist writable fields (no bind body→model) — BOPLA; deny-by-default function authz — BFLA; bound every resource (rate/size/pagination/timeout/spend) + anti-automation on sensitive flows; validate+allowlist user URIs before fetch, block internal ranges — SSRF; inventory+version+harden (CORS/headers/no verbose errors, validate upstream).
- Gate: MOSTLY judgment — BOLA/BFLA NOT scanner-detectable → require cross-tenant authz test (hit object with a 2nd user's token, assert 403). Mechanical: OWASP ZAP baseline vs OpenAPI; OpenAPI-vs-live diff (shadow endpoints); rate-limit/payload assertions. Gate = ZAP clean + cross-tenant authz green + live-vs-spec diff empty.

### authn-authz-oauth-oidc-rbac
- Sources: [OAuth 2.1 draft](https://oauth.net/2.1/) · [PKCE RFC 7636](https://oauth.net/2/pkce/) · [RFC 8725 JWT BCP](https://www.rfc-editor.org/rfc/rfc8725)
- Rules: default = Authorization Code + PKCE for ALL clients (keep secret too for confidential); client_credentials for M2M; NO implicit/ROPC; exact-match redirect URIs, rotate/one-time refresh for public; validate JWT fully — pin allowed `alg` (never alg=none, reject RS256→HS256 switch), validate iss/aud/exp/nbf, treat kid/jku as untrusted; authorize on validated claims tied to object — RBAC coarse, ABAC per-object owner/tenant (valid token = authN not authZ).
- Gate: JWT config asserts (alg=none rejected, HS256-with-pubkey rejected, wrong-aud/expired rejected; verify passes explicit `algorithms` allowlist); redirect exact-match + implicit/ROPC disabled + PKCE required. Object-owner check = cross-user integration test (judgment).

### secrets-and-least-privilege
- Sources: [OWASP Secrets Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html) · [12factor Config](https://12factor.net/config) · [Gitleaks](https://github.com/gitleaks/gitleaks)
- Rules: never hardcode secrets → external manager (Vault/AWS/Azure/GCP); config in env; least privilege per role+secret; rotate + automate, prefer dynamic/short-lived; shift-left detection pre-commit+CI; strip secrets before autonomous agent runs (scan gates agent START).
- Gate: `gitleaks detect` exits 1 on finding / 0 clean → pre-commit + CI + agent-start gate (ties to existing `secret_scan`). Rotation/least-priv = policy judgment.

### observability-slis-slos
- Sources: [Google SRE — SLOs](https://sre.google/sre-book/service-level-objectives/) · [Google SRE — Monitoring / golden signals](https://sre.google/sre-book/monitoring-distributed-systems/) · [K8s probes](https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/) · [OpenTelemetry signals](https://opentelemetry.io/docs/concepts/signals/)
- Rules: SLIs→SLOs→error budget (gates releases, never 100%); four golden signals (latency split success/fail, traffic, errors, saturation); percentiles not averages; alert on symptoms via burn-rate (fast 2%/1h+5%/6h page, slow 10%/3d ticket); separate liveness (restart) from readiness (gate traffic); structured correlated telemetry via OTel.
- Gate: readiness 200→admit traffic; burn-rate alert on recorded budget; four-signal metrics + OTel export present. Which SLIs/targets = judgment.

---

## The 3 additions → a comprehensive 28

Every research agent independently flagged the same gaps: the current 25 cover the *caller* side and the
*build* side, but not protecting *your own* service under abuse/overload, nor the concrete testable
pattern behind saga/CQRS.

- **rate-limiting-and-throttling** (Scale & async) — token-bucket (bursts) vs sliding-window (smooth);
  return 429 + Retry-After + X-RateLimit-*; distributed counters in Redis. *Why: without it a single
  client exhausts the very pools/caches skills caching + connection-pool try to protect.*
  ([HTTP 429](https://howhttpworks.com/status-codes/429), [Redis rate-limiting](https://redis.io/tutorials/howtos/ratelimiting/))
- **transactional-outbox** (Data correctness) — its own playbook, not a sub-rule of cqrs-and-saga; the
  testable answer to "atomically change state and publish an event," preventing the dual-write bug behind
  every saga. ([microservices.io](https://microservices.io/patterns/data/transactional-outbox.html))
- **backpressure-and-load-shedding** (Scale & async) — the *callee* side of resilience: bounded queues
  (unbounded don't fix overload — Little's Law), concurrency-limit caps, priority load-shedding. *Why:
  retries + breakers assume downstream fails cleanly; without shedding, your service melts on a spike.*
  ([Google SRE — Cascading Failures](https://sre.google/sre-book/addressing-cascading-failures/), [Handling Overload](https://sre.google/sre-book/handling-overload/))

Runner-up (defer): `database-per-service`, `api-versioning-and-deprecation`, `idempotency-keys` (overlaps
the existing idempotency-and-pagination).

---

## Machine-checkable vs judgment — the authoring signal

The strongest skills carry a **hard gate** that could become a `test_evidence`/`code_quality`-style check.
The rest are Code-Reviewer-eye judgment. This splits the authoring value:

**Hard-gated (13)** — contract-testing-pact (can-i-deploy exit), property-testing-schemathesis (run exit),
load-testing-slo-gates (k6 exit 99), mutation-testing (break threshold), testcontainers (log banner),
secrets (gitleaks exit), zero-downtime-migrations (squawk), migration-round-trip (up/down CI), acid
(40001 retry test), idempotency (double-POST test), messaging-outbox (atomic-commit test), hexagonal-ddd
(import-linter), repository-pattern (contract test).

**Judgment-led (12)** — api-design (Spectral helps but choice is judgment), data-modeling, indexing,
caching, resilience, connection-pool, twelve-factor, cqrs-and-saga, testing-honeycomb, owasp-api-security
(BOLA needs cross-tenant test, not a scanner), authn-authz, observability.

## Recommended authoring plan (ponytail: don't write 28 essays)

1. **Format:** each SKILL.md is ~40-60 lines — frontmatter + 4-6 rules + the one gate — like
   `verifying-any-stack`, not a textbook. Fork-not-invent: cite the canonical source, don't reproduce it.
2. **Tier 1 (author first, 5):** the ones that back a mechanical gate the DoD already wants — owasp-api-security
   (the spec's #1 failure mode: BOLA), testcontainers-integration, load-testing-slo-gates, zero-downtime-migrations,
   idempotency-and-pagination. These convert directly into `test_evidence` gates.
3. **Tier 2 (10):** the rest of the hard-gated set + hexagonal-ddd + repository-pattern (structure payoff).
4. **Tier 3 (judgment-led + 3 additions):** author last; they inform the Code-Reviewer subagent's rubric
   more than a gate.
5. Wire each into `_harness.py` `skills=(...)` as authored; they load on demand via the `skill` tool.
