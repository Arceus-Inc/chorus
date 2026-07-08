---
name: contract-testing-pact
description: How to prove cross-service compatibility without a full end-to-end environment — Pact-style consumer-driven contracts, so the provider satisfies exactly what each real consumer uses before a release ships.
when_to_use: Read when the service you're building is consumed by another service (or is itself a consumer of one) and you can't spin up the whole system to prove compatibility. Use it instead of a full e2e environment when the question is "will this break a known consumer," not "does the whole system work."
---

# Consumer-driven contracts — prove compatibility without booting the whole system

A full end-to-end environment (every service, every dependency, wired together) is expensive to build
and flaky to run — and it only proves the interactions someone thought to script. Consumer-driven
contract testing (Pact is the canonical tool, spec §11) proves something narrower and more useful: the
provider satisfies exactly what each REAL consumer actually uses, verified independently on each side.

## 1. The shape: two independent verifications, one shared contract

- **Consumer side** (a service that CALLS this API): write a Pact test against a mock provider — it
  records the exact requests the consumer makes and the responses it expects, and emits a `pact.json`
  contract file. This runs in the consumer's own test suite, with no real provider running.
- **Provider side** (the service you're building here): given the consumer's `pact.json`, replay each
  recorded interaction against your REAL running service (boot it like the api_verifier does) and
  assert every response matches what the contract promises. This is what you do as the Backend
  Engineer proving a provider.

## 2. Get the contract, then verify against the live service

```bash
pip install pact-python   # or the ecosystem's Pact provider-verifier
```

- If a Pact Broker is reachable, pull the latest contract(s) for this provider from it — the broker is
  the shared source of truth across consumer and provider repos.
- If there's no broker in this environment, look for a checked-in `pacts/*.json` in the repo (common in
  a monorepo or a repo that vendors its consumers' contracts for local verification).
- If neither exists, this technique doesn't apply yet — there's no known consumer contract to verify
  against; fall back to the OpenAPI/Schemathesis conformance check instead (a different, complementary
  proof).
- Boot your service on a real port (same pattern as any other api_verifier check), then run the
  provider verification against it — each recorded interaction replayed as a real HTTP request, each
  response diffed against the contract.

## 3. A failure here is a real cross-service break

A contract mismatch means: if this provider ships as-is, a real consumer's next call breaks — not a
hypothetical, a documented interaction that consumer already depends on. Treat it exactly like a red
integration test: passed=false, with the mismatched interaction (expected vs actual) as the `detail`.

## 4. `can-i-deploy` — the release gate, not just the test

Pact's `can-i-deploy` check (or the equivalent broker query) answers "is this version of the provider
compatible with every consumer version currently deployed?" — the true release gate for a service with
independently-deployed consumers. Record its answer as part of the proof when a broker is available;
when it isn't, the local provider-verification result against checked-in contracts is the fallback
signal.

## Why this is a skill, not a tool

Whether a Pact Broker exists, where the contracts live, and which interactions are even relevant is
repo- and org-specific know-how — not something to hardcode. This skill is how you decide whether the
technique applies and how to run it; when it doesn't apply, say so and lean on Schemathesis/Testcontainers
instead rather than skipping proof entirely.
