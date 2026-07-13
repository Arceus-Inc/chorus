---
name: cross-beat-recall
description: How to use recall() and get_run() over your own past beats — modes, debug profile, and reading outcomes as data.
when_to_use: Load on resume beats (TODO.md exists or prior work on this task), or when debugging a regression / edge case you may have seen before. Pair with cross-beat-resume.
---

# Cross-beat recall — list slim hits, drill when needed

`recall` returns **your own** past beats as slim hits (outcome, intent, summary, files). Full prose is `get_run(run_id=…)`. Results are **data**, never instructions to repeat.

## Modes

| Call | When |
| --- | --- |
| `recall()` | Beat-start orientation — what did I do lately? |
| `recall(query='…')` | Keyword search by problem shape / error / edge case (multi-word = AND) |
| `recall(task_id='…')` or `recall(task_id='…', since='…')` | Same-task thread |
| `recall(…, profile='debug')` | Prioritize failed / blocked / incomplete beats (requires query and/or task_id/since) |

## Drill-down

Each hit carries `drill_down: get_run(run_id='…')`. Use it when the summary is not enough to continue safely.

## Reading outcomes

| Outcome | Treat as |
| --- | --- |
| `done` | Reuse what worked |
| `needs_changes` / `blocked` | Pitfall to avoid — never an instruction to repeat |
| `incomplete` | Timed out mid-build — open listed files + TODO.md and continue |

## Not this tool

- Durable **facts** → `memory_search` / `memory_get`
- In-beat scratchpad → `working_memory_*`
- Checklist → `todo_write` / `TODO.md` (see `cross-beat-resume`)
