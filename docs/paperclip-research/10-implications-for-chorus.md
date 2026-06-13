# 10 — Implications for chorus

This is the payoff of the whole study. Paperclip is the chorus/horizon thesis already
shipped — and the single most important thing it teaches is *where chorus should draw a
different boundary*, and what to steal verbatim once it does.

---

## The central finding

Paperclip's ~350KB liveness/watchdog/recovery subsystem — the silent-stall machinery
([05](05-liveness-and-recovery.md)) — exists **only because its orchestration boundary is
a process boundary with an opaque byte stream** ([04](04-execution-and-adapters.md)). The
control plane cannot see the agent think, so it *reconstructs* "is the work alive?" from
output-silence timing + post-hoc side-effect evidence + DAG row-state.

**dream-native chorus has the structured in-process event stream.** It calls `run_task` as a
function and receives typed `tool_use`/`tool_result`/turn events directly. It **witnesses**
liveness instead of reconstructing it. So a large fraction of Paperclip's hardest, most
defensive code **evaporates** for chorus — the output-silence watchdog, the regex-over-stdout
liveness classifier, the "is it producing tokens vs making progress" heuristics. That is
chorus's structural reason to exist as something separate from Paperclip, proven at the code
level. (It is also exactly the class of bug — heartbeat watchdogs killing live work — that
motivated this whole investigation.)

But the boundary cuts both ways (see "the honest cost" below).

---

## Steal wholesale (orthogonal to observability — pure DAG / crash-recovery correctness)

These are hard, battle-tested, and chorus needs every one regardless of having the event stream:

1. **Exact-once decomposition with a durable partial result.** Keyed on a fingerprint
   (`sourceIssue, acceptedPlanRevision`), an `in_flight`/`completed` claim row with `childIssueIds`
   accumulated one-per-transaction. A manager that dies after creating 2 of 5 children resumes from
   the same fingerprint and reuses the 2 — never re-fans-out. (Paperclip `issue_plan_decompositions`.)
2. **Blocker-as-data + resolution wakes** for non-blocking re-invocation. "A waits for B" is an
   `issue_relations type=blocks` row; clearing the last blocker fires `issue_blockers_resolved`. The
   parent run *terminates* and is re-woken by an event — no coroutine ever awaits.
3. **Single-assignee atomic checkout as a CAS-on-a-column**, with the two-lock split
   (`checkoutRunId` ownership vs `executionRunId` liveness) and terminal-only stale-lock clearing.
   409 = real owner; never retry.
4. **The three-tier recovery ladder** (auto-recover once, preserving owner → explicit recovery action
   with a bounded owner → human escalation), conservative, **never auto-reassign**.
5. **Liveness-as-a-visibility contract**: every non-terminal task must have a declared next-action
   path (active run / queued wake / monitor / pending interaction / blocker chain / human owner /
   recovery action) — or it's surfaced as *visible recovery work*, never silently completed.
6. **Two-gate budgets**: a reactive auto-pause+kill on cost-event-over-limit **and** a proactive
   `getInvocationBlock` threaded at *every* run-start site. Caps are mechanism the SDK owns + a default;
   the numbers are consumer config.
7. **Fail-closed low-trust containment**: narrower-wins intersection across the layered policy sources
   (agent/project/issue/run), deny on conflict, sandbox-driver + isolated-workspace required.
8. **Slug-portable orgs**: export replaces IDs with slugs (`reportsTo → reportsToSlug` survives
   re-import), strips system-dependent values, and externalizes secrets as declared env-*inputs*
   (values never ship; re-materialized on import). This is the "portable git-markdown org" bet with
   the hard parts solved.
9. **State lives in rows + partial-unique indexes, not process memory.** Locks, holds, claims, leases,
   recovery owners — all durable, idempotent by Postgres constraint. Any worker crashes; another resumes
   by reading the ledger.

## Validates chorus's *hardest* bets

The three things the chorus direction doc treats as first-class hard problems are exactly the items
**still ⚪ open on Paperclip's roadmap**: **Enforced Outcomes**, **Artifacts & Work Products**,
**Memory**. A shipped product hasn't cracked them. Specifically:

- **The differentiator chorus should own.** Paperclip's "done" is **self-report + validation + optional
  human approval — the artifact is never independently verified** (confirmed in code:
  `run-liveness.ts` counts whether a run *progressed*, not whether the deliverable is *correct*). chorus
  can close this because **dream has an evaluator that sees the real artifact.** Make
  evaluator-verifies-the-deliverable the M1 requirement — it is differentiated *and* only possible
  because chorus is dream-native.
- **Memory** — Paperclip's plan (a thin control-plane binding layer + provider adapters, not a built-in
  engine) matches dream's `MemoryStore`/`MemoryWriter` contract shape. This is the lattice design space.

## What dream-native makes unnecessary (don't build these)

- the output-silence watchdog + thresholds (60min/4h),
- post-hoc `classifyRunLiveness` regex-over-stdout,
- the per-adapter stdout `parseStdoutLine` transcript reconstruction,
- heartbeat liveness *inference* from byte timing.

chorus replaces all of it with "subscribe to the dream observer event stream and react to typed
events." Stuck = the event stream stalled *and* the structured state says so — not a guess.

## The honest cost of going dream-native

Paperclip's process boundary is *also an abstraction boundary* — it's why Paperclip orchestrates
Claude, Codex, Cursor, OpenClaw, anything, via the `execute(ctx)→result` adapter contract. chorus
calling `run_task` in-process is **dream-only**. The clean reconciliation:

- **dream-native for the runtime edge** — get the event stream, kill the watchdog tax, get the evaluator.
- **steal Paperclip's row-based data model + invariants for the org edge** — the DAG, decomposition,
  recovery, budgets, trust, portability.
- **if BYO-agent is ever needed, ship chorus *as a Paperclip adapter*** (dream-as-adapter) — the process
  boundary becomes available without making it chorus's *internal* model.

---

## Concrete M1 starting point

The chorus M1 data model can be drafted by adopting Paperclip's schema, slimmed to the in-process case:

| Paperclip table | chorus M1 adoption |
|---|---|
| `issues` (+ status machine, two locks) | the task/plan entity; keep single-assignee + atomic checkout if chorus ever runs employees concurrently |
| `issue_relations type=blocks` | dependency edges (`depends_on`) |
| `issue_plan_decompositions` | exact-once decomposition claim (needed even in-process for crash safety) |
| `issue_recovery_actions` | the liveness-as-visibility primitive |
| `agents` (`reportsTo`) | `Employee` + the `Workforce` org tree |
| `budget_policies`/`incidents`/`cost_events` | caps (Q4) — two-gate enforcement |
| `goals` | the alignment chain (company → project → task) |
| company portability package | the reusable-workforce template format |

What chorus M1 **drops** vs Paperclip: the heartbeat scheduler's output-silence watchdog, the
adapter/subprocess layer (replaced by an in-process `run_task` call), the per-adapter stdout parsers,
and (for M1) the multi-company tenancy, the plugin worker system, and the React board.

> Bottom line: **be dream-native for the loop, Paperclip-shaped for the org, and own the evaluator-verified
> outcome that Paperclip still lacks.**
