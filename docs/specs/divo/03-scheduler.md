# 03 — Scheduler (heartbeat + cron)

The kernel **tick**, the **wake** model, and **cron/routines**. This supersedes the design sketch
in heartbeat-cron.md with the concrete schema (spec 01) and the recovery
sequence (spec 02). Built on dream's cron parser; the locks, lease, and *org scheduling* are
chorus's own — on its ledger (spec 01). dream's coordination board is reused only for the
intra-task swarm, never for chorus task ownership.

> **Two heartbeats, named apart** (the disambiguation that unblocks everything):
> **tick** = the kernel's pulse (one pass over the ledger); **beat** = one employee's short
> `dream.run_task` invocation (born from a wake, dies on completion). The tick drives the org; a
> beat is one unit of work. (B1.1: a beat *rehydrates* an employee, does one pass, dissolves.)

---

## 1. Dispatch is push-only (the decisive deviation from Paperclip)

Paperclip wakes an agent on events **and** on a blind idle timer. chorus drops the idle timer for
dispatch (B2.3): **an employee is woken only when there is a durable `wake` row.** The tick is the
*only* timer, and it exists to drain wakes, fire cron, and recover crashes — not to make every
employee re-check its inbox. The idle timer survives only as the recovery/monitor sweep (§3a, §3c).

This is why chorus's scheduler is a fraction of Paperclip's: the per-agent poll, the output-silence
watchdog, and the inbox re-check all collapse into *"the tick reads the ledger."*

---

## 2. The wake model

A `wake` (spec 01) is *"run employee E because reason R, payload P."* Reasons and their fire points:

| Reason | Fired when | By |
|---|---|---|
| `task_assigned` | a task gains an assignee + leaves backlog | assignment |
| `deps_resolved` | the **last** `depends_on` of a task reaches `done` | beat completion |
| `children_done` | **all** direct children of a parent are terminal → wake the manager | beat completion |
| `message` | an inter-employee mailbox message lands (M2+) | mailbox |
| `cron_due` | a routine fires (§4) | tick |
| `monitor_due` | a `monitor.next_check_at` comes due | tick |
| `recovery` | the tick finds stranded work / stale lease | tick |
| `manual` | operator / CLI | intake |

**Coalescing:** the `wake_queued_key_uq` partial-unique index (spec 01) makes "at most one queued
wake per `coalesce_key`" a *database* guarantee — a flurry of identical triggers folds into one
(bump `coalesced_count`), so the employee runs once. (Paperclip's `coalescedCount`, enforced by an
index instead of code.)

**Lifecycle:** `enqueue (coalesces) → tick claims (concurrency-capped) → checkout on the ledger
(atomic CAS) → beat runs dream.run_task → on terminal, mark_done + fire downstream wakes.`

---

## 3. The tick — pure function of the ledger

One loop, fixed interval, **holds no state** (B2.2). Each decision is re-derivable from rows; crash
+ restart + re-read continues. One pass, in this order (the §10 recovery sequence first, so a
crashed beat is reaped before new dispatch):

```python
async def tick(now):
    # (a) RECOVER — reap tasks whose run lease passed, requeue orphaned wakes
    for stale in ledger.stale_leases(now):             # run.lease_expires_at < now (this ledger)
        ledger.release_locks(stale.task_id)            # compare-and-clear, terminal-only
        recovery.open_or_update(stale)                 # liveness-as-visibility (spec 02 §6)
    reconcile_stranded(now)                            # spec 02 §9 modes a/b (bounded: one wake)

    # (b) CRON — fire due routines (double-fire-guarded)
    for trig in routine_triggers_due(now):             # next_run_at <= now, enabled
        if not claim_cron_edge(trig, now):             # conditional UPDATE next_run_at
            continue
        fire_routine(trig, now)                        # §4

    # (c) MONITORS — deferred self-wakes due now
    for m in monitors_due(now):
        if exhausted(m): apply_recovery_policy(m); continue
        wakes.enqueue(Wake(m.employee_id, "monitor_due", {"task_id": m.task_id}))
        clear(m)                                       # one-shot; assignee must re-arm

    # (d) DISPATCH — drain wakes, capped by concurrency (budget gate 1)
    for w in wakes.claim(limit=free_slots()):          # prioritized: in_progress → deps-ready → age
        task = resolve_task(w)
        if budgets.invocation_blocked(task): continue  # spec 04 two-gate, gate 1
        run = ledger.checkout(task.id, w.employee_id)  # conditional UPDATE … RETURNING; None = 409 → skip
        if run is None: continue
        dispatch_async(run_beat, w, run)               # NON-blocking — the tick never awaits a beat
```

Dispatch priority (Paperclip's): in-progress resumes first → dependency-ready → priority/age. The
tick **never runs `run_task` inline** — it kicks the beat off async and moves on, so one slow beat
can't stall the pulse.

**The deterministic sort key.** `wakes.claim` orders the eligible set by a total, tie-broken key so
two ticks (or two Arceus processes) always agree on *which* wake is next — no nondeterministic
ordering, no starvation:

```python
sort_key = (
    0 if task.status == "in_progress" else 1,   # 1. resume live work before starting new
    0 if task.deps_all_done else 1,             # 2. dependency-ready before still-gated
    PRIORITY_RANK[task.priority],               # 3. critical=0 high=1 medium=2 low=3
    wake.created_at,                            # 4. FIFO within a band (oldest first — anti-starve)
    wake.id,                                    # 5. final tie-break: stable, total order
)
```

Every component is a stored column, so the key is a pure function of the rows (B2.2). `wake.id` as
the last element guarantees a *total* order even when all else ties — the property multi-tick
exact-once dispatch (§5) relies on.

**Tick cadence.** default `tick_interval = 1 s`; the tick is idempotent, so the exact value only
trades latency for wakeups. In the multi-process (Arceus) deployment each process adds a small
random **jitter** (±250 ms) so ticks don't synchronize and contend on the same rows. If a tick's
work exceeds the interval, the next tick is skipped (no overlap) — there is never more than one tick
in flight *per process*; cross-process safety is §5.

### The beat (`run_beat`)

```python
async def run_beat(wake, run):
    emp  = workforce.rehydrate(wake.employee_id)       # identity: org row + memory read (B1.1)
    task = ledger.get(wake.task_id)
    ledger.begin_execution(task.id, run.id)            # set execution_run_id + lease (this ledger)
    result = await dream.run_task(                     # the ONE seam — planner→sprint→evaluator
        task_id=task.id, intent=task.intent,
        role=emp.role.manifest, dod=task.dod,
        observer=event_bus.emit,                       # witness liveness (no watchdog)
    )
    memory_writer.apply(raw_delta(emp, result))        # append-only raw sprint delta; lattice consolidates later
    land_outcome(task, result)                         # role-specific (spec 04)
    set_status(task, "done" if result.passed else "blocked")
    ledger.release_locks(task.id)                      # compare-and-clear, terminal-only
    fire_downstream_wakes(task)                         # deps_resolved / children_done
    wakes.mark_done(wake.id)
```

Almost none of this is new logic — the locks, the lease, the beat are dream. chorus's new code is
the **wake/routine tables, assignment, `fire_downstream_wakes`** (the recursion), and the
outcome/DoD seam.

---

## 4. Cron / routines — fire writes a task, never runs an agent

`fire_routine` resolves a `routine_trigger` into ledger writes (Paperclip: "each firing creates an
execution issue assigned to the routine's agent — picked up in the normal heartbeat flow"):

```python
def fire_routine(trig, now):
    r = routine_of(trig)
    rr = routine_run(routine_id=r.id, trigger_id=trig.id, status="received",
                     idempotency_key=f"{r.id}:{trig.id}:{trig.next_run_at}")  # exact-once
    if r.concurrency_policy == "skip_if_active" and has_live_task(r):
        rr.status = "suppressed"; return
    if r.target == "spawn_task":
        task = ExecPlan.from_template(r.intent_template, now,
                 assignee=r.employee_id, goal=r.goal_id, parent=r.parent_task_id,
                 origin=("routine_execution", r.id), fingerprint=rr.idempotency_key,
                 dod=generate_dod(r.intent_template))
        ledger.submit(task)                            # exact-once: task_open_routine_uq (spec 01)
        rr.linked_task_id = task.id; rr.status = "dispatched"
        wakes.enqueue(Wake.cron_due(r.employee_id, task_id=task.id))
    else:  # next_beat — dream WakeNote pattern: no new task, just extra context next beat
        wakes.enqueue(Wake.cron_due(r.employee_id, note=render(r.intent_template, now)))
    trig.next_run_at = next_tick(parse_cron(trig.cron_expression), now)   # dream cron parser
    trig.last_fired_at = now
```

- **`spawn_task`** is the normal path — a real `task`, exact-once by `task_open_routine_uq` + the
  `routine_run.idempotency_key`, so a routine firing while its prior task is still open can't
  duplicate.
- **Double-fire guard** is the conditional `claim_cron_edge` UPDATE (spec 01) — two ticks (or, in
  Arceus, two processes) can't fire the same `next_run_at` edge.
- **`catch_up_policy`**: `skip_missed` (default) fires once for a missed window; `backfill_one`
  fires one catch-up task.

The cron parser is **dream's** (`tasks/_cron.py`, same 5-field shape as Paperclip's `cron.ts`) —
chorus does not rewrite it.

---

## 5. Concurrency, fairness, caps

- **Concurrency cap**: `free_slots()` = `max_concurrent_runs − count(running)`; sourced from a ledger
  `count(run WHERE status='running')`. This is budget **gate 1** at the dispatch layer.
- **Per-employee serialization**: at most one live beat per employee (a per-employee claim) — the
  in-process analog of Paperclip's `agent-start-lock`. Two queued wakes for one employee run
  sequentially, not concurrently.
- **Fairness**: prioritized claim avoids starving old/low-priority wakes; round-robin across
  employees within a priority band.

### Multi-tick safety (one ledger, many ticking processes — the Arceus/Postgres case)

In the SQLite SDK there is one process and one tick; exact-once is the partial-unique indexes
alone. In the **Arceus/Postgres** distribution several workers may tick the *same* ledger, so every
claim step must be exact-once at the row level — the design never assumes a single ticker:

- **`wakes.claim`** is a single `UPDATE … SET status='claimed', claimed_by=:pid WHERE id IN (SELECT
  … ORDER BY <sort_key> LIMIT :n FOR UPDATE SKIP LOCKED) RETURNING *`. `SKIP LOCKED` lets two
  workers drain disjoint wakes with zero contention; the deterministic sort key (§3) means they
  pull the *right* ones. (SQLite has no `SKIP LOCKED`, but with one writer it doesn't need it — the
  same statement degrades to a plain ordered `UPDATE … RETURNING`.)
- **`claim_cron_edge`** stays a conditional `UPDATE routine_trigger SET next_run_at=:next WHERE
  id=:id AND next_run_at=:edge` — only one worker's UPDATE matches the edge, so a routine fires
  exactly once even if every worker sees it due.
- **The checkout** (`ledger.checkout`) is an atomic CAS — a conditional `UPDATE task SET
  checkout_run_id=… WHERE checkout_run_id IS NULL RETURNING` on the chorus ledger; a `None`/`409`
  means a peer won the lock → skip, never retry.
- For the recovery pass, workers take a **Postgres advisory lock** (`pg_try_advisory_lock`) around
  the stale-lease reap so two workers don't both reclaim the same claim; under SQLite the single
  writer makes this a no-op.

The rule: **no scheduler step trusts "I am the only ticker."** Every mutation is a conditional
write that exactly one caller can win, so correctness is identical whether one process ticks or ten.

---

## 6. Milestone fit

- **M1** (one engineer): a *trivial* tick — "is there an eligible task? checkout + beat." No wake
  table, no cron. Just `run` + lease recovery.
- **M2** (two engineers, deps): the `wake` table + `task_assigned`/`deps_resolved` + the dispatch
  loop + per-employee serialization. **This is where the tick earns its keep.**
- **M3** (manager + reports): `children_done` wakes (non-blocking re-invocation) + decomposition.
- **M4** (routines): `routine`/`routine_trigger`/`routine_run` + cron firing + monitors.

> Bottom line: the **tick** is the heartbeat (pure over the ledger); **wakes** are push-driven
> beats; **cron** is a trigger that writes a task and lets normal dispatch run it. The substance to
> build first is the tick + wakes; cron is a thin M4 layer over dream's parser.
