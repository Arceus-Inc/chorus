---
name: reviewing-for-prod-failures
description: How to red-team a diff for the failure classes that pass their own tests and fail in production — missing authorization, N+1 queries, injection, unbounded queries, missing rate limits, secrets in code. The hunt the Code-Reviewer forks instead of eyeballing the diff.
when_to_use: Read before reviewing a change (the Code-Reviewer's first move). Use it to trace every handler's authorization path and every database access, and to classify what you find. A green test suite does not clear a diff — this hunt does.
---

# Reviewing for production failures — hunt what the tests didn't

A green suite proves the paths the author thought to test. Production breaks on the paths they
didn't — and the author wrote both the code and the tests, so those blind spots are shared. Your job
is to find them by *tracing*, not reading top-to-bottom. Two traces catch most of it: **follow every
request to its authorization check**, and **follow every database access to its bounds**.

## The hunt — classify every finding into one of these

### `missing_authz` — the #1 real breach
For each endpoint that returns or mutates data, ask: *whose data, and who is asking?* Trace the
handler to the point where it decides the caller is allowed. Flag it if:
- an owner-scoped resource (`GET /orders/{id}`) returns without checking `resource.owner == caller`,
- a mutating or admin route has no role/permission gate,
- authorization is done in the client/UI but not re-checked on the server,
- an object reference from the URL is trusted (IDOR) — `/users/{id}/card` with no ownership check.
The test suite almost never covers "user B reads user A's record", because the author tested as one
user. That is exactly the hole.

### `injection`
Follow user input to every sink. Flag string-built SQL (`f"... WHERE id = {id}"`), shell commands
built from input, `eval`/`exec` on input, HTML rendered without escaping. The fix is
parameterize/escape at the sink, never sanitize at the source.

### `n_plus_1`
Look for a query *inside a loop* — `for row in rows: fetch(row.id)`. One round-trip per row melts the
DB under real row counts. The fix is a single batched query (`WHERE id IN (...)`) or a join.

### `unbounded_query`
Any list/scan/search with no `LIMIT` and no pagination. Fine on 10 rows in a test, OOM on 10M in
prod. Also: an unbounded request body / upload with no size cap. The fix is a bounded page.

### `no_rate_limit`
Expensive or abusable endpoints — login, signup, password reset, search, anything that sends mail or
money — with no throttle. Flag the absence; the fix is a limiter keyed by IP/user.

### `secrets_in_code`
A hardcoded key, password, token, or connection string in the diff. The fix is an env var / secret
manager. (The `secret_scan` tool catches many; you catch the ones it misses in new code.)

## How to run the hunt

1. Get the diff and the code it touches (`git diff`, then `read_file` the changed handlers/services).
2. **Assume the input is hostile and the caller is the wrong user.** Walk each handler with that lens.
3. Only flag what you can point to — a `location` (file:line), the concrete failing input, and the
   `fix`. A vague "improve error handling" is not a finding. A **false high is as costly as a missed
   one**: it blocks a clean diff and trains the engineer to ignore you. Flag `high` only when you can
   name the input that breaks it.
4. Set `cleared` = true only when no `high` remains. Medium/low are advisory and don't block.

## What you do NOT do

You review; you never patch. Name the risk and the fix; the engineer applies it and re-runs you.
Stay inside the diff and what it touches — you're reviewing this change, not auditing the whole repo.
