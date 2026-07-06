---
name: user-flow-mapping
description: How to map the path a user takes through a task across screens — entry points, steps, decisions, and exits — before designing individual screens, so the flow is coherent instead of a set of disconnected views.
when_to_use: Read at the start of any multi-screen feature or task, before designing individual screens. Pairs with information-density (per-screen load) and states-empty-loading-error (each step's states).
---

# User-Flow Mapping

Designing screens before mapping the flow produces beautiful views that don't connect — a login with no
error path, a checkout that dead-ends, a wizard with no way back. A fluent model tends to design the
screen it was asked about in isolation. This skill zooms out to the *task* first.

## The one rule

**Map the whole task before designing any screen.** Know the entry points, every step, every branch,
and every exit before you draft a single view — the flow constrains the screens, not the reverse.

## What a flow map captures

- **Entry points**: how does the user *arrive* at this task? (nav, link, deep link, notification, empty-
  state CTA). Each entry may need different context.
- **Steps**: the ordered screens/states to complete the task. Fewer is better — every step is a chance
  to drop off.
- **Decisions/branches**: where the path forks (has an account vs not, valid vs invalid input, one item
  vs many). Each branch is a path you must design.
- **Exits**: success (what confirms it, where does the user land next?) *and* abandonment (can they
  back out, cancel, save-for-later without losing work?).
- **Error & recovery paths**: what happens when a step fails — and how the user gets back on track.

## Principles

- **Minimize steps and decisions.** Every step and every choice is friction. Collapse steps, default
  decisions (see `information-density`), remove dead ends.
- **Always a way back.** No screen is a trap; there's always cancel/back/undo. Coordinate with
  `keyboard-and-focus` for overlays.
- **Preserve work across steps.** Going back must not lose entered data.
- **Design the unhappy paths.** The error and empty branches are part of the flow, not afterthoughts.

## Before you finish

1. Draw (in words) the flow: entry → steps → branches → exits, including error and abandonment paths.
2. Count the steps and decisions — can any be removed, merged, or defaulted?
3. Confirm every screen has a way forward *and* a way back, with work preserved.
4. Only then design the individual screens — and check each against its place in the flow.
