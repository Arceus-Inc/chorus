---
name: cross-beat-resume
description: Durable TODO.md checklist protocol so a budget-killed beat resumes instead of restarting.
when_to_use: Load at beat start when TODO.md exists, when the task spans multiple beats, or when the budget warning appears. Pair with cross-beat-recall for prior beat summaries.
---

# Cross-beat resume — keep a checklist, reconcile, continue

Your worktree survives beat death. The model context does not. `TODO.md` is the durable spine.

## Protocol

1. **List the whole task up front** with `todo_write` — every step you will need, not just the current one.
2. **Check items off the moment they are done** — not at the end. A kill is abrupt.
3. **First tools every beat:** `read_file` on `TODO.md` if it exists, then reconcile against reality (`git status`, artifacts on disk, green test commands).
4. **Resume unchecked steps.** If a checked step's tests now fail, re-verify it before advancing.
5. **Never restart from scratch** when a checklist and prior work already sit in the worktree.

## Budget flush

When a tool result warns that beat budget is under 10%, call `todo_write` immediately to sync the checklist before the beat dies.

## Trust green artifacts

A step is done when its durable artifact exists and is green. Do not re-run verification "just to be sure" when you have not changed the code it covers — jump to the first checklist item whose artifact is still missing.
