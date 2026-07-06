---
name: spec-to-working-app
description: How to turn a one-line intent into the smallest interface that actually works — sizing the slice, naming the user-visible behavior that means "done", and wiring it end to end before polishing.
when_to_use: Read FIRST on every build, before writing any code. It is the sizing-and-scoping discipline the whole workflow hangs off; pair it with `choosing-a-frontend-stack` to pick the tech, and component/state skills build on the slice it defines.
---

# Spec → Working App

The failure that matters is shipping code that *looks* finished but doesn't run, isn't wired, or breaks
on the first click. It usually starts at the beginning: building too much, or building the wrong thing,
before anything actually works. This is how to size the job so "done" means "a user can use it".

## The one rule

**Name the user-visible behavior that means "working", build the smallest thing that delivers it, wire
it end to end, and run it — before you add anything else.**

## Size the slice

- Read the intent and any existing code / `DESIGN.md` in the worktree FIRST. Build *to* an existing
  design system and *extend* existing code — don't rewrite what's there.
- Write down, in one sentence, the observable behavior a user would point at and say "it works" (e.g.
  "typing a city and pressing search shows that city's current temperature"). That sentence is your
  target and your first e2e assertion.
- Cut to the smallest slice that delivers that sentence. Defer everything else. A working small thing
  beats an impressive broken thing every time.
- Once you know the slice, choose the stack that FITS it — see `choosing-a-frontend-stack`. Right-size:
  don't reach for a heavyweight framework for a mostly-static page, and don't hand-roll routing/state/
  rendering that a framework you're already pulling in should own. The stack is a decision you justify.

## Wire it end to end, early

- Get a trivial version of the whole path working first — input → logic → visible output — even with a
  hard-coded value. Prove the wiring, then fill in the real logic.
- Never build a beautiful surface with dead buttons. An event listener that does nothing is worse than
  no button. Wire the interaction the moment you add the control.

## Don't gold-plate, don't stop short

- Adding scope the intent didn't ask for is a failure mode, not diligence — it dilutes focus and adds
  untested surface.
- Stopping before the behavior actually happens in the browser is the *other* failure mode. "Working"
  is the floor, not the ceiling.

## Before you finish

1. Can you state the one user-visible behavior that means "working"? Does an e2e test assert exactly it?
2. Is the whole path wired — does clicking/typing actually change what the user sees?
3. Did you build only the slice the intent asked for, and all of it?
4. Does it actually RUN and pass its tests — `npm test` green and `npx playwright test` green against the
   app served however your chosen stack serves it (a static file, a dev server, a preview build)?
