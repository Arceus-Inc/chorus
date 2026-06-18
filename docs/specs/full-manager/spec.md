# The Manager — Slice 2: the adaptive integrate (`submit_task` + `assign_task`)

Slice 1 (shipped — see [`HANDOFF.md`](HANDOFF.md)) gave the manager a **mechanical** loop: decompose
once, park, and when every child is terminal the kernel marks the parent `done`. It is a correct
*walking skeleton*, but the manager is **dumb** — it fans out a fixed wave and the kernel rubber-stamps
"all children terminal." Slice 2 makes the manager **adaptive**: it reads how its reports actually did
and *decides* what to do next — spawn a fix, reassign, scope another wave, or accept the subtree.

---

## Why we want an adaptive manager (the motivation)

The mechanical DoD — "all children terminal → `done`" — is wrong in three ways that a real org never
tolerates:

1. **Terminal ≠ good.** A child can land `done` (its own DoD passed in its own worktree) yet its merge
   conflicted (`merged=false`), or two children's merges are individually green but *integrate*
   broken (the combined tree fails). The mechanical manager ships a subtree it never actually looked
   at. A real manager **reads the outcomes** and integrates only when the *whole* is good.
2. **A stuck report kills the goal.** Slice 1's long run showed it: one child that can't pass its DoD
   strands `blocked`, and because `blocked` isn't terminal the parent waits **forever**. A real
   manager reacts — reassigns the work, narrows it, or spawns a corrective subtask — instead of
   waiting on a report that will never finish.
3. **The plan is fixed at fan-out.** A good manager learns from the first wave: "the API child
   revealed we also need a migration." The mechanical model can't add that — it decomposed once and is
   done. An adaptive manager **submits incremental work** as understanding grows (the non-blocking
   delegation model, B1.2/B1.3 — adaptive "see results → create more" happens *across beats*).

This is the difference between a *task fan-out primitive* and a **manager**. Slice 1 proved the
plumbing; Slice 2 puts a brain on it. The two capability tools Slice 1 stubbed in the manifest now go
live **and get used** — they only earn their keep in the adaptive beat.

---

## The three capabilities, by responsibility (no redundancy)

| Tool | Responsibility | When the manager reaches for it |
|---|---|---|
| `decompose` *(Slice 1)* | **bulk wave** — create an N-child DAG + assign + wire deps in one call | the *first* plan of a goal |
| `submit_task` *(Slice 2)* | **incremental add** — create **one** child of the current task | mid-flight: a fix after reading a failed child, or newly-discovered work |
| `assign_task` *(Slice 2)* | **route / reassign** — (re)assign an *existing* task to a chosen report | a report is stuck/overloaded; hand its child to someone else |

They are distinct creators, not overlapping ones: `decompose` is the opening bulk move; `submit_task`
adds a *single* child so `children_done` still fires correctly (the integrate loop keeps working);
`assign_task` mutates ownership of work that already exists. All three are model-callable dream
`BaseTool`s over the same `CapabilityService`, idempotent on `(parent, label)` / assign-to-same.

---

## High-Level Design

The single structural change: **the integrate stops being a kernel short-circuit and becomes a real
manager beat.**

```
Slice 1 (mechanical):
  children_done → kernel: all terminal? → land `done` (no model)        ← dumb, no judgement

Slice 2 (adaptive):
  children_done → manager INTEGRATE beat (read child outcomes) → the manager decides:
     • everything good        → confirm: the subtree is integrated → `done`
     • a child failed/blocked  → submit_task(a corrective child) OR assign_task(reassign) → re-PARK
     • more work discovered    → submit_task / decompose a follow-on wave → re-PARK
  The Mechanical DoD ("all children terminal") gives way to "the manager decided it's integrated."
```

The decompose → park half is unchanged. What changes is the **re-invocation**: instead of the kernel
landing it, the manager runs a beat with the three capability tools and the subtree's outcomes in
context, and either **closes** the goal or **delegates more** (which re-parks the parent on the new
children via the existing `gates_parent` + M2 gate). The loop is identical machinery; only the *integrate
disposition* gains a model in the seat.

### The hard part (learned from Slice 1)

Slice 1's bug #3 is the whole risk: a model integrate beat that can call `decompose` will
**over-decompose** — re-plan the same goal and balloon the subtree. Slice 2 must give the manager a
model beat *without* that failure mode. The fix is **scoped intent + a verdict-shaped DoD**, not raw
re-planning:

- The integrate beat is dispatched with an **integrate intent** (the child outcomes + "decide if this
  subtree is complete"), not the original goal — so the model reasons about *results*, not *re-planning*.
- Its tools lean to `submit_task` (incremental) / `assign_task` (route); a fresh full `decompose` of an
  already-decomposed goal is refused by the exact-once claim (it returns the existing children).
- Completion is the manager's **explicit decision** (an `AgentReview`-style "integrated?" verdict),
  recorded on the parent — not a side effect of the kernel counting children.

---

## Low-Level Design

| Component | Contract | Detail |
|---|---|---|
| `submit_task` tool (`chorus_tools/_submit_task.py`) | `submit_task(label, intent, assignee, depends_on?)` → child id | one `CapabilityService.submit_one(parent, label, …)`; idempotent on `(parent, label)`; `gates_parent=True` so it re-parks the parent and `children_done` re-fires when it lands |
| `assign_task` tool (`chorus_tools/_assign_task.py`) | `assign_task(task_id, assignee)` → ok | validates the target is an invokable **report** of the manager; assign-to-same is a no-op; reuses `lifecycle._coordination.assign_task` |
| `CapabilityService` (extend) | `submit_one(...)`, `reassign(...)` | thin wrappers over `create_child` / `assign_task`, same `(parent,label)` idempotency + assignee validation as Slice 1 |
| Integrate disposition (`_scheduler.py`) | re-invocation runs a **manager integrate beat**, not the mechanical short-circuit | the beat gets the child outcomes in its intent; post-beat: created new non-terminal children ⇒ re-PARK; declared integrated ⇒ `done` + `ManagerLander`; otherwise stays parked (a stuck child is now actionable, not a deadlock) |
| Manager harness (`chorus_employee/manager/`) | `tools=("read_file","decompose","submit_task","assign_task")` | the dropped-tools note is removed; the brief gains an **integrate-beat section**: "when re-invoked, judge the subtree from its child outcomes; do not re-plan a finished goal" |
| Integrate context | the child roster + each child's status / artifact / DoD verdict, threaded into the beat | so the manager reasons about *what its reports produced*, surfaced via the per-beat `BeatContext` (extended) or the intent text |

The mechanical-integrate short-circuit added in Slice 1 (`run_beat`) is **replaced** by dispatching the
integrate beat; the park branch and the stale-wake drain stay exactly as they are.

---

## Build order

1. **`CapabilityService.submit_one` + `reassign`** (TDD, dream-free) — extend the seam; same
   idempotency + validation rules as `decompose`.
2. **`submit_task` + `assign_task` tools** (`chorus_tools/`, TDD) — dream `BaseTool`s over the new
   service methods; factory registers them when the role declares them.
3. **Manifest + brief** — manager `tools` gains the two; the brief gains the integrate-beat section
   (judge from outcomes; don't re-plan).
4. **Adaptive integrate disposition** (`_scheduler.py`, TDD) — replace the mechanical short-circuit
   with a manager integrate beat; thread child outcomes into context; handle decide→close vs
   decide→delegate-more (re-park). Keep park + stale-wake drain.
5. **Keyed acceptance** — a goal where the **first wave has a deliberately failing child**; the manager
   reads it, `submit_task`s (or reassigns) a fix, the fix lands, then it integrates → `done`. Prove the
   manager *reacted* (not just waited). Re-run the multi-wave long run for the report.

## Touch list

| Layer | Files |
|---|---|
| Capability | `src/chorus/lifecycle/_capability.py` (extend) |
| Tools | `src/chorus_tools/_submit_task.py`, `_assign_task.py`, `__init__.py`, `_factory.py` (register) |
| Manager | `src/chorus_employee/manager/_harness.py` (tools), `_brief.py` (integrate section) |
| Kernel | `src/chorus/heartbeat/_scheduler.py` (adaptive integrate disposition), `_beat_context.py` (child-outcome context, if threaded there) |
| Tests | `tests/lifecycle/test_capability.py`, `tests/tools/`, `tests/heartbeat/test_m3_park_integrate.py` (adaptive cases), keyed `examples/m3_adaptive_acceptance.py` |

---

## Out of scope (the other open M3 piece) — the Reviewer

Separate from Slice 2, M3 still owes the **Reviewer** as a *load-bearing* role. It is declared today
(`chorus_employee/reviewer/`: read-only, PLAN, `outcome_kind="verdict"`) but **inert** — the
`AGENT_REVIEW` DoD kind exists yet the scheduler never dispatches a reviewer beat, and there is no
`verdict` lander. To finish it: the kernel orchestrates an `AgentReview` DoD by dispatching a read-only
reviewer beat that renders an approve/block verdict which **gates completion**, plus a `ReviewerLander`
(verdict), wired so judgment-class work (a PM's spec, an analyst's finding, and eventually the
manager's "is this subtree good?") is reviewer-verified rather than self-asserted. This pairs naturally
with Slice 2: the adaptive manager's "integrated?" decision is exactly the kind of judgment a Reviewer
should be able to verify.
