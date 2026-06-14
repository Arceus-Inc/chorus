# 00 — Architecture & scope

The overview. What chorus *is*, the layering, the repo shape, and — most importantly — the scope
boundary (what it must never own). Parallels Paperclip's `doc/SPEC.md` + `01-system-overview`,
inverted for the dream-native world.

---

## 1. What chorus is

chorus is an **SDK** — a library, like dream — that ships the abstractions for *a workforce of
agents doing durable, assignable work*. It is **the org over the ledger**. The consumer supplies
the workspace; chorus supplies the employees, the task DAG, the scheduler, the DoD, and the
outcome-landing.

One-line charter: **chorus is everything that makes a `dream.run_task` belong to a named employee
in an org, and turns its artifacts into landed work.**

Paperclip's self-description was *"it looks like a task manager; under the hood: org charts,
budgets, governance, goal alignment, agent coordination."* chorus is that — minus the process
boundary, because it is dream-native.

---

## 2. The layering (three rings, six planes)

chorus is **ring 3** over dream's ring 2 (`run_task`) over ring 1 (the engine turn-loop). See
dream-sdk-explained.md §0. The planes, lowest to highest:

```
INTERFACE   intake (submit) · event stream · inspector            ← spec 08, 10
GOVERNANCE  budgets(2-gate) · trust(fail-closed) · audit          ← spec 04
CONTROL     scheduler/tick · assignment · decomposition ·         ← spec 02, 03
  (kernel)  recovery · outcome-landing · DoD
EXECUTION   the dream seam: run_task in-process                   ← spec 05
CONTRACT    dream.contracts (POSIX): ExecPlanLedger, Memory…
DATA        ledger (SQLite-WAL) · board (dream coordination) · memory git  ← spec 01
```

The discipline (B2.2): everything above DATA is **stateless over it** — the scheduler holds no
state not in the ledger, so crash + restart + re-read continues.

---

## 3. Repo shape

```
chorus/                          ← its own repo (Python, depends on dream)
  src/chorus/                    ← the SDK
    cron/  heartbeat/  roles/  memory/  ledger/  outcomes/  ...
  src/chorus_cli/                ← thin CLI (submit/inspect)
  examples/                      ← demo workforce wired to a demo workspace
  tests/                         ← incl. test_public_api.py (pins the surface, like dream)
  docs/specs/                    ← these specs
```

dream is a **package dependency**, not vendored. chorus reuses dream's `run_task`, `roles`,
`contracts`, `coordination` (the board), and `tasks/_cron` (the parser). It builds its own
`cron`/`heartbeat` org layer on top (the user's explicit choice).

---

## 4. What chorus owns

- **Identity** — `Employee` (name, role, toolset, memory scope). A `run_task` is always somebody's.
- **Org-as-data** — `Workforce` (`reports_to` tree). Hire/fire = a data edit.
- **The task ledger** — ExecPlans with `depends_on` edges, states, scored selection.
- **The scheduler** — dispatch eligible tasks, enforce caps, re-invoke managers on child completion
  (push, never blocking).
- **Assignment** — role-match (hard filter, no auto-router).
- **Definition-of-done** — typed, generated at intake, **evaluator-verified** (the differentiator).
- **Role plugins** — toolset + DoD generator + outcome artifact.
- **Persistence** — SQLite-WAL ledger; git-markdown memory (append-only).
- **Outcome landing** — role-specific (PR→CI→merge / persist artifact).

## 5. What chorus must NOT own (the boundary — the whole game)

- **Not the agent loop** — that is dream. chorus *calls* `run_task`; it never writes a turn FSM, a
  tool-call atom, or an evaluator. If you find yourself doing that, stop.
- **Not company direction** — that is **horizon** (the *next* sibling to be built; until it ships,
  chorus runs a *stub* intake — human/cron-driven — that horizon will later own and drive).
- **Not memory consolidation / employee growth** — that is **lattice** (a sibling; chorus captures
  memory at the **sprint level** — raw, append-only, with provenance — and **reserves the
  consolidation seam** lattice will own; chorus never decides what's *worth* remembering).
- **Not multi-tenant hosting, auth, billing, the web board** — that is **Arceus** (the product).
- chorus depends on dream; **nothing depends sideways**. The architecture is **four repos**
  (dream · chorus · horizon · lattice); horizon and lattice are siblings meeting only at the data
  layer + `dream.contracts`. chorus *stubs* intake (until horizon) and *writes raw* sprint memory
  (until lattice) — reserving both seams, absorbing neither.

> The moment the kernel "knows what a good sprint looks like," hardcodes a cadence, or bakes in
> "engineers open PRs," it has stopped being an SDK. Those are role plugins, horizon policy, and
> the company definition the SDK *interprets*.

### 5a. Reserved sibling seams (the four-repo contract)

chorus does not absorb horizon or lattice; it holds a **named seam** for each, so the sibling can
later plug in *without chorus changing*:

| Sibling | Owns (when built) | The seam chorus reserves now | chorus's stub today |
|---|---|---|---|
| **horizon** | direction · OKR tree · what-to-do-next prioritisation · cross-sprint objective health | `submit()` intake + the `goal` table (a local mirror horizon will feed) + `task.depth=0` "intake slot" | human/cron-driven `submit`; goals created flat at intake |
| **lattice** | memory consolidation · skill/role evolution · what's *worth* remembering | the `MemoryWriter` contract (chorus ships the append-only impl; lattice replaces it) + the provenance every record carries | `AppendOnlyMemoryWriter` — raw sprint deltas, never consolidated |

The rule: **a seam is a typed contract + a stub default, never a stub that the sibling must rip
out.** horizon reads/writes the same ledger + goal rows; lattice swaps the writer behind the same
`MemoryStore`/`MemoryWriter` split. Both bind to `dream.contracts` + chorus's own contracts (spec
09 §4), never to chorus internals.

### 5b. Glossary — the two heartbeats (used across every spec)

- **tick** — the *kernel pulse*: one pass over the ledger (recover → cron → monitors → dispatch).
  Holds no state; pure function of the rows (B2.2). The org's only timer. (spec 03 §3)
- **beat** — *one employee's* short `dream.run_task` invocation. Born from a `wake`, rehydrates an
  employee, does one pass, lands its outcome, dissolves. (spec 03 §3, B1.1)
- **wake** — a durable "run employee E for reason R" row; the *only* thing that starts a beat
  (push-driven dispatch). (spec 03 §2)
- **run** — the durable record of one beat (thin — no PID/stdout, because liveness is witnessed).

---

## 6. Non-goals (Paperclip's "is NOT" list, adapted)

chorus is **NOT**:
- an **agent runtime** (dream runs the agent; chorus orchestrates),
- a **chat app** (employees have jobs, not chat windows; CEO-chat is Arceus/horizon),
- a **workflow builder** (no drag-and-drop pipelines; work is tasks + dependencies),
- a **prompt manager** (roles bring their system prompts via manifests),
- a **knowledge base** (memory is a thin store + a lattice seam, not a wiki),
- **multi-tenant** in the SDK (one workforce; many companies is Arceus),
- **self-healing magic** (it *surfaces* stalls as visible recovery work; it never silently fixes).

---

## 7. Deployment: SDK vs distribution

| | chorus (SDK) | Arceus (distribution) |
|---|---|---|
| Storage | **SQLite-WAL** (a file) | Postgres (Railway) |
| Tenancy | one workforce | many companies, isolated |
| Surface | library + CLI + `examples/` | hosted API + web board + auth |
| Coordination | dream board (`board.sqlite`) | dream board / Postgres claims |

The schema stays in the SQLite ∩ Postgres intersection so the same kernel runs both (spec 01).

---

## 8. The dream-native thesis (why chorus is small)

Paperclip's control plane sees an **opaque byte stream** from a subprocess agent, so it
*reconstructs* "is it working?" from output-silence timing — ~350KB of watchdog/recovery code, plus
a whole adapter/MCP/auth/WebSocket stack to bridge the process boundary. chorus calls `run_task`
**in-process** and **witnesses** dream's structured event stream. So it deletes: the subprocess
adapter layer, the MCP phone-home + JWT injection, the output-silence watchdog, the regex-over-
stdout classifier, and the per-adapter stdout parsers (spec 05, 08). **The kernel is a fraction of
Paperclip's, not because it does less, but because the boundary moved.**
