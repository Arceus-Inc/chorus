"""Ten hard Backend Engineer multi-beat tickets (stdlib-first, skill-shaped).

Each ticket targets Bex skills/tools/subagents: structuring-any-service,
verifying-any-stack, migration-roundtrip, property-testing, contract-testing,
mutation-testing, test_evidence, secret_scan, code_quality, spawn_subagent
(api_verifier / test_author / code_reviewer), todo_write / cross-beat resume.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HardTicket:
    id: str
    title: str
    skills: tuple[str, ...]
    seed_readme: str
    intent: str
    rubric: str
    ship_files: tuple[str, ...]
    ship_hints: tuple[tuple[str, str], ...]  # (path, substring that must appear)


def _rubric(body: str) -> str:
    return (
        "PASS only if ALL criteria hold. FAIL renamed-away or thinner APIs.\n"
        "Judge from the worktree (read + bash). Do not trust claims. "
        "Agent-authored green tests that skip the contract are FAIL.\n\n"
        + body
    )


TICKETS: tuple[HardTicket, ...] = (
    HardTicket(
        id="01-wal-kv",
        title="Crash-safe WAL key-value store + HTTP",
        skills=("structuring-any-service", "verifying-any-stack", "mutation-testing"),
        seed_readme="# wal-kv stub\n",
        intent=(
            "Build a dependency-free crash-safe KV service (stdlib only).\n"
            "Multi-sprint OK; keep TODO.md accurate.\n\n"
            "Modules:\n"
            "1. wal.py — WriteAheadLog(path): append(record: dict), replay() -> list[dict], "
            "truncate_after(n: int). Records are one JSON object per line.\n"
            "2. store.py — KVStore(data_path, wal_path): set(k,v), get(k)->v|None, delete(k)->bool, "
            "flush(). Every mutation appends to WAL then updates in-memory map; "
            "on init replay WAL then load snapshot if present. "
            "crash_recover() rebuilds state from WAL only (ignore corrupt snapshot).\n"
            "3. app.py — stdlib HTTP on PORT (8080): GET /health; PUT /kv/<key> body raw; "
            "GET /kv/<key>; DELETE /kv/<key>; POST /admin/flush; POST /admin/crash-recover.\n"
            "4. Tests: test_wal.py, test_store.py (incl. simulated crash: write WAL, "
            "new store without snapshot recovers), test_app_http.py live server.\n"
            "README with run instructions. pytest -q green."
        ),
        rubric=_rubric(
            "1. wal.py, store.py, app.py, test_wal.py, test_store.py, test_app_http.py exist.\n"
            "2. WAL is JSONL; replay reconstitutes append order; truncate_after works.\n"
            "3. KVStore recovers from WAL after crash without needing a snapshot.\n"
            "4. HTTP routes match intent; PUT/GET/DELETE round-trip.\n"
            "5. pytest -q exits 0; crash-recovery test is real (not a no-op).\n"
            "6. No secrets in code; README documents PORT."
        ),
        ship_files=(
            "wal.py",
            "store.py",
            "app.py",
            "test_wal.py",
            "test_store.py",
            "test_app_http.py",
        ),
        ship_hints=(
            ("wal.py", "WriteAheadLog"),
            ("store.py", "crash_recover"),
            ("store.py", "replay"),
        ),
    ),
    HardTicket(
        id="02-job-queue-migrate",
        title="SQLite job queue with migration round-trip",
        skills=("migration-roundtrip", "structuring-any-service", "verifying-any-stack"),
        seed_readme="# job-queue stub\n",
        intent=(
            "Stdlib + sqlite3 only. Job queue with schema migrations that round-trip.\n\n"
            "1. migrations/ — numbered SQL files 001_init.sql, 002_add_attempts.sql. "
            "migrate.py: upgrade(db), downgrade(db, to_version: int), current_version(db). "
            "MUST support apply → roll back → re-apply without data loss of completed jobs "
            "where the schema allows.\n"
            "2. queue.py — JobQueue(db_path): enqueue(payload: dict)->job_id, "
            "claim()->job|None, complete(job_id), fail(job_id, error) must persist the supplied "
            "error on the failed/dead job, "
            "list_pending() / list_dead(). Attempts column from migration 002.\n"
            "3. worker.py — process_one(queue, handler) claims and runs; on exception fail().\n"
            "4. app.py — HTTP: POST /jobs, GET /jobs/<id>, POST /jobs/<id>/claim (test helper), "
            "GET /health. The claim helper must claim that exact pending ID; a missing or "
            "ineligible ID returns 404 without claiming a different job.\n"
            "5. Tests: test_migrate_roundtrip.py (upgrade, downgrade, upgrade again), "
            "test_queue.py, test_worker.py, test_app_http.py. The HTTP test must exercise all four "
            "routes and prove exact-ID claim plus 404 behavior while another job remains pending.\n"
            "pytest -q green. README."
        ),
        rubric=_rubric(
            "1. migrations/001_init.sql and 002_add_attempts.sql exist; migrate.py has "
            "upgrade/downgrade/current_version.\n"
            "2. test_migrate_roundtrip.py proves apply→rollback→re-apply.\n"
            "3. JobQueue enqueue/claim/complete/fail + attempts behavior; fail persists its "
            "supplied error and tests assert it.\n"
            "4. worker.process_one handles success and failure.\n"
            "5. test_app_http.py exercises POST /jobs, GET /jobs/<id>, GET /health, exact-ID claim "
            "with another pending job, and the 404 path; pytest -q green."
        ),
        ship_files=(
            "migrate.py",
            "queue.py",
            "worker.py",
            "app.py",
            "migrations/001_init.sql",
            "migrations/002_add_attempts.sql",
            "test_migrate_roundtrip.py",
            "test_queue.py",
            "test_worker.py",
            "test_app_http.py",
        ),
        ship_hints=(
            ("migrate.py", "downgrade"),
            ("queue.py", "enqueue"),
            ("test_migrate_roundtrip.py", "downgrade"),
        ),
    ),
    HardTicket(
        id="03-hmac-token-rotate",
        title="HMAC token service with key rotation",
        skills=("structuring-any-service", "verifying-any-stack", "secret_scan"),
        seed_readme="# hmac-token stub\n",
        intent=(
            "Stdlib only. Signed bearer tokens with rotatable secrets — no hardcoded keys.\n\n"
            "1. keys.py — Keyring from env TOKEN_KEYS='kid1:secret1,kid2:secret2' and "
            "TOKEN_ACTIVE_KID. active_kid(), get(kid)->secret|None. Never log secrets.\n"
            "2. tokens.py — issue(subject, ttl_s=3600)->str compact token "
            "`kid.payload_b64.sig_b64` HMAC-SHA256; verify(token)->dict|None "
            "(subject, exp, kid). Sign `kid.payload_b64`; reject wrong sig / expired / unknown "
            "kid, including at the exact `now == exp` boundary.\n"
            "3. app.py — POST /token {subject,ttl_s?} with X-Admin-Key==ADMIN_KEY; "
            "GET /whoami Authorization: Bearer <token>; GET /health; "
            "POST /admin/rotate {kid,secret} updates the in-memory keyring and makes that kid active "
            "(test helper). Both admin POST routes require the admin header.\n"
            "4. Tests cover issue/verify, expiry, wrong key, rotation still verifies old kid "
            "until removed, then rejects it after removal. Generate test secret/admin values at "
            "runtime directly with `secrets` or `os.urandom`; joining, splitting, or encoding fixed "
            "literal fragments does not qualify. This applies to test_keys.py, test_tokens.py, and "
            "test_app_http.py: TOKEN_KEYS secret values and their assertions must use generated "
            "variables, not fixed sample strings. secret_scan must stay clean (secrets "
            "only via env).\n"
            "The token tests separately prove bad-signature or swapped-key rejection by actually "
            "mutating the signature or replacing the verification key; an expiry-only assertion "
            "does not prove the wrong-key case.\n"
            "5. test_app_http.py must drive a real stdlib HTTP server/callable over loopback, not "
            "call route-shaped methods directly. It covers health, missing/wrong admin auth on both "
            "POST routes, issue/whoami, rotation causing newly issued tokens to use the new kid, old "
            "token survival, and rejection after old-key removal.\n"
            "pytest -q. README."
        ),
        rubric=_rubric(
            "1. keys.py Keyring from env — no hardcoded production secrets in source.\n"
            "2. tokens issue/verify signs kid.payload; expiry at now >= exp + bad sig fail.\n"
            "3. Rotation: old tokens verify while the kid remains and fail after it is removed.\n"
            "4. A real loopback HTTP test covers health; missing/wrong admin auth on both POST routes; "
            "issue/whoami; new-active-kid rotation; old-token survival and post-removal rejection.\n"
            "5. FAIL if fixed token/admin credential values appear as string literals in .py "
            "files, including tests. Required env names TOKEN_KEYS/TOKEN_ACTIVE_KID/ADMIN_KEY, "
            "the JSON field name `secret`, and non-secret key IDs are allowed."
        ),
        ship_files=(
            "keys.py",
            "tokens.py",
            "app.py",
            "test_keys.py",
            "test_tokens.py",
            "test_app_http.py",
        ),
        ship_hints=(
            ("tokens.py", "hmac"),
            ("keys.py", "TOKEN_KEYS"),
            ("tokens.py", "verify"),
        ),
    ),
    HardTicket(
        id="04-webhook-outbox",
        title="Webhook outbox with exponential backoff",
        skills=("structuring-any-service", "verifying-any-stack", "testing-honeycomb-strategy"),
        seed_readme="# webhook-outbox stub\n",
        intent=(
            "Stdlib only. Durable outbox that delivers webhooks with backoff.\n\n"
            "1. outbox.py — Outbox(path jsonl or sqlite): enqueue(url, payload)->id; "
            "due(now)->list; mark_sent(id); mark_failed(id, error, next_attempt_at). "
            "Backoff: 1s, 2s, 4s, 8s capped 60s; max 5 attempts then dead.\n"
            "2. delivery.py — deliver_one(item, transport) must be callable with exactly those "
            "two arguments and POST JSON; transport injectable (tests use fake). On 2xx "
            "mark_sent; else mark_failed with backoff.\n"
            "3. app.py — POST /events {url,payload}; POST /tick runs due deliveries through "
            "a transport supplied when constructing the app (the production default may use "
            "stdlib HTTP, but must not be a hardcoded always-fail fake); "
            "GET /outbox?status=pending|dead; GET /health.\n"
            "4. Tests: backoff schedule math, fake transport success/fail, dead-letter after "
            "max attempts, HTTP tick path.\n"
            "pytest -q. README."
        ),
        rubric=_rubric(
            "1. outbox enqueue + due + sent/failed/dead with backoff schedule.\n"
            "2. deliver_one(item, transport) needs no third argument; 2xx vs failure paths tested.\n"
            "3. Max attempts → dead; an injected successful transport makes HTTP /tick send "
            "a due item and remove it from pending.\n"
            "4. pytest -q green; no network calls in unit tests."
        ),
        ship_files=(
            "outbox.py",
            "delivery.py",
            "app.py",
            "test_outbox.py",
            "test_delivery.py",
            "test_app_http.py",
        ),
        ship_hints=(
            ("outbox.py", "next_attempt"),
            ("delivery.py", "transport"),
            ("outbox.py", "dead"),
        ),
    ),
    HardTicket(
        id="05-feature-flags",
        title="Feature flags with sticky percentage rollout",
        skills=("structuring-any-service", "property-testing-schemathesis", "verifying-any-stack"),
        seed_readme="# feature-flags stub\n",
        intent=(
            "Stdlib only. Feature flag service with sticky bucketing.\n\n"
            "1. flags.py — FlagStore path flags.json: upsert(name, percent, salt:str), "
            "clamping percent below 0 to 0 and above 100 to 100 (do not reject it), "
            "enabled(name, subject:str)->bool using sha256(salt+subject) % 100 < percent. "
            "Same subject always sticky for fixed salt/percent.\n"
            "2. Property-style test: for a fixed flag, sampling 500 subjects yields "
            "enabled rate within ±8% of target percent (statistical, not flaky RNG — "
            "use deterministic subjects s0..s499).\n"
            "3. app.py — PUT /flags/{name} {percent,salt}; GET /flags/{name}/check?subject=; "
            "GET /health; admin list GET /flags.\n"
            "4. test_flags.py, test_flags_property.py, test_app_http.py.\n"
            "pytest -q. README."
        ),
        rubric=_rubric(
            "1. Sticky hashing: same subject ⇒ stable enabled bit.\n"
            "2. Property test with s0..s499 within ±8% of configured percent.\n"
            "3. HTTP upsert + check; out-of-range PUT succeeds and returns/persists the "
            "clamped 0..100 value.\n"
            "4. pytest -q green."
        ),
        ship_files=(
            "flags.py",
            "app.py",
            "test_flags.py",
            "test_flags_property.py",
            "test_app_http.py",
        ),
        ship_hints=(
            ("flags.py", "sha256"),
            ("test_flags_property.py", "500"),
            ("flags.py", "percent"),
        ),
    ),
    HardTicket(
        id="06-lww-sync",
        title="LWW register map with merge sync HTTP",
        skills=("structuring-any-service", "verifying-any-stack", "contract-testing-pact"),
        seed_readme="# lww-sync stub\n",
        intent=(
            "Stdlib only. Last-write-wins register map with peer sync.\n\n"
            "1. lww.py — LWWMap: set(key, value, ts: float), get(key), "
            "merge(other: dict[str, {value,ts}]) — higher ts wins; tie → lex larger value. "
            "export() -> dict.\n"
            "2. app.py — PUT /kv/{key} JSON {value,ts?}; GET /kv/{key}; "
            "POST /sync body peer export merges; GET /export; GET /health.\n"
            "3. contracts/lww_http.json — pact-like: interactions for PUT/GET/sync with "
            "request/response shapes. scripts/verify_contract.py loads contract and "
            "asserts live server matches (or in-process handler).\n"
            "4. test_lww.py merge conflicts, test_app_http.py, test_contract.py runs verifier.\n"
            "pytest -q. README."
        ),
        rubric=_rubric(
            "1. LWW merge rule correct (ts then value tie-break).\n"
            "2. HTTP sync merges peer state.\n"
            "3. contracts/lww_http.json + verify_contract.py exist and test_contract exercises them.\n"
            "4. pytest -q green."
        ),
        ship_files=(
            "lww.py",
            "app.py",
            "contracts/lww_http.json",
            "scripts/verify_contract.py",
            "test_lww.py",
            "test_app_http.py",
            "test_contract.py",
        ),
        ship_hints=(
            ("lww.py", "merge"),
            ("contracts/lww_http.json", "interactions"),
            ("scripts/verify_contract.py", "contract"),
        ),
    ),
    HardTicket(
        id="07-openapi-mini",
        title="OpenAPI-validated mini bank API",
        skills=("property-testing-schemathesis", "structuring-any-service", "verifying-any-stack"),
        seed_readme="# openapi-bank stub\n",
        intent=(
            "Stdlib only. Tiny bank API validated against an OpenAPI 3 YAML you author.\n\n"
            "1. openapi.yaml — paths /health, /accounts POST, /accounts/{id} GET, "
            "/accounts/{id}/transfer POST with schemas (balance >= 0, transfer amount > 0).\n"
            "2. Also ship openapi.json synchronized with openapi.yaml. validate.py must load "
            "that JSON with the stdlib (do not import yaml, even optionally), then implement "
            "validate_request(method, path, body)->errors list. Route and body rules must be "
            "derived from the loaded OpenAPI artifact, not duplicated while the spec is unused.\n"
            "3. bank.py — AccountStore create/get/transfer (insufficient funds error).\n"
            "4. app.py wires validation before handlers; 400 on schema fail.\n"
            "5. test_validate.py, test_bank.py, test_app_http.py; fuzz-ish test walks "
            "invalid payloads (including missing required fields, unexpected fields, and "
            "booleans where numbers are required) and expects 400. "
            "The HTTP test must cross a real loopback or in-process WSGI/HTTP handler boundary, "
            "and cover the insufficient-funds response.\n"
            "pytest -q. README."
        ),
        rubric=_rubric(
            "1. synchronized openapi.yaml and openapi.json document the routes/schemas.\n"
            "2. stdlib-json validate.py uses that spec, including required and "
            "additionalProperties rules, and app returns 400; no yaml import.\n"
            "3. a real HTTP/WSGI test proves schema 400 and insufficient-funds 409 or 400.\n"
            "4. Fuzz/invalid payload tests exist; pytest -q green."
        ),
        ship_files=(
            "openapi.yaml",
            "openapi.json",
            "bank.py",
            "validate.py",
            "app.py",
            "test_validate.py",
            "test_bank.py",
            "test_app_http.py",
        ),
        ship_hints=(
            ("validate.py", "validate"),
            ("bank.py", "transfer"),
            ("app.py", "400"),
        ),
    ),
    HardTicket(
        id="08-mutation-ledger",
        title="Ledger whose tests kill balance mutants",
        skills=("mutation-testing", "verifying-any-stack", "test_red"),
        seed_readme="# mutation-ledger stub\n",
        intent=(
            "Stdlib only. Double-entry style mini ledger — tests must be mutation-strong.\n\n"
            "1. ledger.py — Ledger: credit(account, amount), debit(account, amount), "
            "balance(account), transfer(src, dst, amount). Invariant: sum of all balances "
            "always 0 if you start from zero. Implement credit/debit as transfers against a "
            "documented SYSTEM account, so those public methods also preserve the invariant.\n"
            "2. scripts/mutate_balance.py — temporarily patches ledger.py to remove or "
            "break the balance check / allow negative without error, runs pytest, "
            "expects FAILURE, restores file. Exit 0 only if mutant was killed.\n"
            "3. test_ledger.py must kill that mutant; test_app_http.py optional thin HTTP "
            "GET /balance/{acct} POST /transfer.\n"
            "4. Document mutation gate in README. pytest -q green; "
            "`python scripts/mutate_balance.py` exits 0.\n"
        ),
        rubric=_rubric(
            "1. transfer, credit, and debit keep the sum including SYSTEM at zero under pytest.\n"
            "2. scripts/mutate_balance.py proves suite goes RED on a real mutant then restores.\n"
            "3. Mutant script is not a stub that always passes.\n"
            "4. pytest -q green on clean tree."
        ),
        ship_files=(
            "ledger.py",
            "scripts/mutate_balance.py",
            "test_ledger.py",
            "README.md",
        ),
        ship_hints=(
            ("ledger.py", "transfer"),
            ("scripts/mutate_balance.py", "pytest"),
            ("test_ledger.py", "balance"),
        ),
    ),
    HardTicket(
        id="09-token-bucket",
        title="Multi-tenant token-bucket + Prometheus text metrics",
        skills=("structuring-any-service", "verifying-any-stack", "reviewing-for-prod-failures"),
        seed_readme="# token-bucket stub\n",
        intent=(
            "Stdlib only. Per-tenant token bucket rate limiter with metrics.\n\n"
            "1. bucket.py — TokenBucket(rate_per_s, burst): allow(n=1)->bool; require positive "
            "rate/burst and a positive integer n (reject bool/nonpositive so invalid input cannot add tokens); "
            "TenantBuckets: allow(tenant, n=1) lazy-creates buckets from config.\n"
            "2. metrics.py — counters: requests_total{tenant,result=allow|deny}, "
            "render_prometheus() valid text exposition with backslash and quote escaping in tenant labels.\n"
            "3. app.py — POST /check {tenant,n?} → 200 allowed / 429; GET /metrics; "
            "GET /health. Config from env RATE=5 BURST=10.\n"
            "4. Tests freeze time (inject clock) to prove refill; metrics lines and label escaping; "
            "HTTP 429 plus malformed/missing tenant/nonpositive n returning 400.\n"
            "pytest -q. README."
        ),
        rubric=_rubric(
            "1. Token bucket refill math correct under injected clock.\n"
            "2. Per-tenant isolation; burst then deny.\n"
            "3. /metrics Prometheus text includes requests_total with valid escaped labels.\n"
            "4. HTTP 429 and invalid-request 400 paths tested; pytest -q green."
        ),
        ship_files=(
            "bucket.py",
            "metrics.py",
            "app.py",
            "test_bucket.py",
            "test_metrics.py",
            "test_app_http.py",
        ),
        ship_hints=(
            ("bucket.py", "burst"),
            ("metrics.py", "requests_total"),
            ("bucket.py", "allow"),
        ),
    ),
    HardTicket(
        id="10-saga-booking",
        title="Booking saga with compensate-on-fail",
        skills=("structuring-any-service", "verifying-any-stack", "testing-honeycomb-strategy"),
        seed_readme="# saga-booking stub\n",
        intent=(
            "Stdlib only. Travel booking saga: reserve flight → reserve hotel → charge card. "
            "Any step fail compensates prior steps.\n\n"
            "1. services.py — FlightService.reserve/cancel, HotelService.reserve/cancel, "
            "PaymentService.charge/refund — in-memory state keyed by trip_id (trips isolated); "
            "each can be set to fail_next=True.\n"
            "2. saga.py — book(trip_id, user) runs steps; on failure compensate only completed "
            "prior steps in reverse (do not compensate the step that failed); store and return "
            "{status: ok|compensated|failed, log: list}.\n"
            "3. app.py — a real stdlib HTTP/WSGI server exposing POST /book {trip_id,user}; "
            "POST /admin/fail-next {service}; GET /health; "
            "GET /trips/{id} returns the booking result plus current flight/hotel/payment state.\n"
            "4. Tests: happy path; fail hotel compensates flight; fail payment compensates "
            "hotel+flight; flight failure returns failed with no compensation; idempotent cancel "
            "and refund; two trips stay isolated. Assert actual per-trip service state, not only logs. "
            "HTTP tests must open real loopback requests (not call a dict/direct helper): drive "
            "/admin/fail-next for payment, then /book and /trips/{id} to prove compensation, "
            "and a second booking to prove fail_next was one-shot.\n"
            "pytest -q. README."
        ),
        rubric=_rubric(
            "1. saga compensates in reverse order on failure.\n"
            "2. fail_next switches covered by tests for hotel and payment failures.\n"
            "3. Per-trip state is isolated: happy state stays active while another compensated trip is inactive; "
            "a first-step flight failure is failed, not compensated.\n"
            "4. Real loopback HTTP /admin/fail-next → /book → /trips flow is tested; no dict/direct-call substitute; pytest -q green."
        ),
        ship_files=(
            "services.py",
            "saga.py",
            "app.py",
            "test_saga.py",
            "test_services.py",
            "test_app_http.py",
        ),
        ship_hints=(
            ("saga.py", "compensate"),
            ("services.py", "fail_next"),
            ("saga.py", "book"),
        ),
    ),
)
