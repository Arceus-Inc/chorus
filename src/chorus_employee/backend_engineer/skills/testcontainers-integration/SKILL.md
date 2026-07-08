---
name: testcontainers-integration
description: How to prove a service against the SAME datastore type as production — health-gated container startup, Testcontainers-style, so serialization and queries are proven against a real Postgres/Mongo/Redis, not an in-memory fake.
when_to_use: Read before you write the integration gate for any service that touches a real datastore or downstream dependency. Use it whenever the api_verifier needs to prove durability, or when the unit suite mocks the datastore and you need a real-DB layer underneath it.
---

# Real-DB integration — prove it against the same service type as production

A unit suite that mocks the repository proves the mock's contract, not the database's. The Test
Honeycomb's integration core (spec §11) closes that gap the same way Testcontainers does: boot the
**real** datastore type as a disposable container, run the actual driver/ORM against it, and tear it
down. Stack-agnostic — this is the *pattern*, not a hardcoded tool; bind to whatever container runtime
the repo already has (`docker`, `docker-compose`, `podman`).

## 1. Discover the datastore, then run its real image — never a fake

- Read the repo's own dependency manifest / `docker-compose.yml` / `.env.example` for the datastore
  and version already in use (Postgres 16, Redis 7, MongoDB 7, …). Bind to what's declared; don't
  guess a different version.
- If the ecosystem has a native library (`testcontainers-python`, `testcontainers-go`,
  `testcontainers-node`, Testcontainers for Java), install and use it — it wires container start/stop
  and port-mapping into the test lifecycle for you.
- If there's no native library or installing one is impractical in the sandbox, do the same thing by
  hand with `docker run`/`docker-compose up` in a probe script: start the real image on a free port,
  poll it healthy, run the real integration tests against it, then tear it down in a `finally`. The
  proof is the same either way — a real engine of the same type production runs, not a mock.
- **Never substitute SQLite for Postgres, `mongomock` for Mongo, or `fakeredis` for Redis** as the
  *integration* layer — those prove the ORM's own abstraction, not the query behaviour, index usage,
  or serialization quirks of the real engine. In-memory fakes are fine for fast unit tests; they are
  not integration proof.

## 2. Health-gate the startup — never race a container that isn't ready

A container that's *running* is not the same as a container that's *accepting connections*. Poll
before you touch it:

```
for attempt in range(N):
    if can_connect(host, port):  # a real ping/SELECT 1/PING, not just "process alive"
        break
    sleep(short_backoff)
else:
    fail("container never became healthy")
```

A test suite that starts probing before the engine is ready produces flaky, not proof.

## 3. Prove the behaviours a mock would hide

Run the real integration core against the live container:
- **Serialization** — round-trip a value through the actual driver (types, encoding, timezone
  handling) and read it back.
- **Queries** — the actual query/index the code relies on executes correctly against the real engine
  (a query that "works" against SQLite can violate Postgres's stricter typing, or miss an index the
  real planner needs).
- **Persistence across a restart** — if the service is stateful, write a record, restart the service
  process (not the container) against the same running datastore, and read the record back. Data that
  survives was written through; data that vanished was an in-memory fake wearing a database's name.

## 4. Record the proof as its own gate

Hand the integration run to `test_evidence` as its own named gate (e.g. `{"name": "integration",
"command": "..."}`) alongside lint/types/unit — a green `test_evidence/manifest.json` is only real
proof if the integration gate it reports actually ran against a live container, not a mock swapped in
to make the gate pass faster.

## Why this is a skill, not a tool

Which container image, which driver, which real query to exercise is know-how that changes per stack
and per repo — the exact kind of knowledge that must be discovered, not hardcoded into a tool (§03).
`test_evidence` stays a stack-blind executor; this skill is how you decide what integration gate to
hand it.
