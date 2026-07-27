---
name: how-to-plan-a-roadmap
description: Turn a mission and the current reality into a small, staffable, measurable roadmap — a decision and the goals that realize it — proposed through roadmap_propose.
when_to_use: Use when forming or re-planning the company's direction — after the mission is set, when a goal lands, when capacity frees, or when the roadmap has gone stale and horizon has woken you to re-plan.
---

# How to plan a roadmap

A roadmap is not a wish list. It is the **smallest set of outcomes** that moves the mission forward
*and* that the company you have can actually ship this sprint. You are the only mind that authors it;
`roadmap_propose` is a deterministic pen — it validates structure and records the plan, it does not
think. The thinking is here.

## When NOT to use this
- The direction is sound and nothing changed — do not churn a working roadmap.
- You are adjudicating a single funnel proposal — use `proposal_approve` / `proposal_reject`.
- You are re-aiming one existing goal — use `goal_set_priority` / `goal_archive`.

## The method
1. **Read the reality first.** Call `governance_read`. Note what is **done** (never re-propose it),
   what is **blocked** (decide: unblock, re-scope, or drop), what is **in flight** (capacity already
   committed), and the **capacity by profession** (how much building power is actually free).
2. **Cover the mission by capability, not by feature count.** Break the mission into the few outcomes
   that, together, discharge it. Each goal is an **outcome** ("users can capture a note in one tap"),
   never a task ("write the editor component").
3. **Size the roadmap to capacity.** Propose only as many goals as the free capacity can actually
   staff and ship this sprint. A roadmap of ten goals for a team that can build two is a fiction — it
   is better to ship two and re-plan than to queue eight that starve. If the mission needs more than
   you can staff, that is a hiring signal, not a bigger roadmap.
4. **Make every goal measurable.** Give each a concrete `metric` and a `target` a reviewer could check
   ("activation rate", "40%"; "p95 latency", "< 200ms"). "Improve UX" is not a goal. If you cannot
   name the metric, the goal is not yet a goal.
5. **Score by impact × confidence against effort.** Set each goal's initial `score` in [0, 1] — higher
   means work on it sooner. Reserve the high band for the few that most move the mission.
6. **Sequence by dependency.** If a goal must follow another, give the predecessor a `key` and list it
   in the dependent's `depends_on`. Keep the graph acyclic and shallow; most roadmaps are flat.

Then call `roadmap_propose` once with the decision `statement` and the goals. It stores a **proposed**
decision — nothing reaches the workforce until it is approved. Read it back with `governance_read`;
do not re-propose the same roadmap.

## Rules
- **Fewer goals, fully staffable.** A roadmap you can ship beats a roadmap that looks ambitious.
- **Outcomes, not tasks.** Decomposition into tasks is the pod's job, not the roadmap's.
- **Never re-propose done work.** The ledger rejects a duplicate of a completed goal — and so should you.
- **Every goal carries a metric and a target.** No metric, no goal.
- **Ground it in the digest.** Cite the numbers you planned against in each goal's `rationale`.

## Common failure modes
- **Roadmap inflation** — more goals than capacity can ship; the queue starves and nothing lands.
- **Task-shaped goals** — "build the API"; these belong inside a pod, not on the roadmap.
- **Unmeasurable goals** — no metric/target, so "done" can never be judged.
- **Re-proposing shipped work** — ignoring the done list and re-queuing what already landed.
- **Ignoring capacity** — planning design-heavy goals with no designer free.

## Cross-references
- `strategic-prioritization` — how to choose the single priority among the goals you propose.
- `okrs-and-metrics` — how to shape a metric + target that is actually checkable.
- `capital-allocation` — sizing spend to the roadmap you can staff.
