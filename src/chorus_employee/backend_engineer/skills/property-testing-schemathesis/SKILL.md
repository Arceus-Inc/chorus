---
name: property-testing-schemathesis
description: How to prove a running API conforms to its own OpenAPI spec across thousands of generated inputs — Schemathesis-style property testing, so no edge case throws a 5xx or returns a response the schema doesn't allow.
when_to_use: Read when the api_verifier is probing a service that exposes an OpenAPI/Swagger spec (or one can be generated from the framework's routing). Use it in addition to hand-written HTTP checks — a handful of example requests only proves the happy path you thought of.
---

# Property-based API conformance — the spec is the oracle, not your examples

A handful of hand-picked `curl` checks only proves the requests you thought to write. Property-based
API testing flips that: generate requests FROM the API's own OpenAPI/JSON-Schema spec across the input
space (boundary values, wrong types, missing required fields, unicode, huge payloads) and assert the
live service never violates its own contract. Schemathesis is the canonical tool (spec §11); the
pattern generalizes to any spec-driven fuzzer.

## 1. Get (or make) the spec — the contract is the oracle

- If the service already serves `/openapi.json`, `/swagger.json`, or ships an OpenAPI YAML file, use
  it directly — it's the single source of truth for what "conforms" means.
- If the framework generates one at runtime (FastAPI, tRPC-to-OpenAPI, Go's `swaggo`, Spring's
  springdoc), boot the service and fetch it live — the served spec, not a stale checked-in copy, is
  what must be honoured.
- If there is genuinely no spec, this technique doesn't apply yet — write the OpenAPI doc for the new
  endpoint first (even a minimal one); a service with an undocumented contract can't be proven against
  one.

## 2. Run the fuzzer against the LIVE service, not the code

```bash
# install once (sandbox is UNRESTRICTED)
pip install schemathesis
# generate + run — start the service on a real port, then:
schemathesis run http://127.0.0.1:<port>/openapi.json --checks all
```

Point it at your booted service exactly like the api_verifier's other checks — a real socket, not an
in-process call. `--checks all` covers: no undocumented 5xx, response conforms to its declared schema,
and (if the spec declares them) no server errors on negative/boundary cases.

## 3. Two ways to fail — both are real findings

- **The service 500s or hangs on a generated input** — a real robustness bug: an unhandled edge case
  (empty string where a UUID was expected, an integer overflow, a null in an optional field) that
  hand-written happy-path tests never exercised.
- **The service returns 200 with a body the schema doesn't allow** — a contract-drift bug: the code
  changed but the spec didn't (or vice versa), which breaks every consumer that trusts the documented
  shape.

Both fail the check — passed=false, with the generated repro request recorded as the `detail` so it's
reproducible without re-running the fuzzer.

## 4. Record the proof

Capture the run's JUnit XML output (or the tool's own report) alongside the hand-written HTTP checks in
`api_verdict.json`'s evidence, and as its own `test_evidence` gate when the service ships an API. A
service can pass every example-based test and still 500 on a value nobody thought to try — the spec
generates the value a person wouldn't.

## Why this is a skill, not a tool

Which spec to fuzz, how to boot the service to reach it, and how to read a Schemathesis failure is
know-how, not a fixed command — bind it to the repo's actual spec source, don't assume one shape.
