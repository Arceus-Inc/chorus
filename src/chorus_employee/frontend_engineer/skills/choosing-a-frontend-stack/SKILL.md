---
name: choosing-a-frontend-stack
description: How to choose the right frontend stack for the job — weighing interactivity, shared state, number of views/routing, SSR/SEO, and bundle budget against build/verify cost — and how to right-size so you neither over-engineer nor under-reach.
when_to_use: Read FIRST on every build, right after sizing the slice with spec-to-working-app and before writing code. Picking the stack is your decision to make and justify; this is how to make it well.
---

# Choosing a Frontend Stack

Choosing the stack is part of the engineering, not a detail someone hands you. The same intent can be
best served by hand-written HTML/JS, a light view library, or a full framework — and picking the wrong
one is a real defect: a heavyweight framework wrapped around a static page is dead weight, and a
hand-rolled tangle where a framework should own routing/state is a maintenance trap. **Judge fit, not
fashion, and write down why.**

## The one rule

**Pick the smallest stack that cleanly carries the app's real complexity — then record the decision and
its trade-offs in your summary so a reviewer can judge the fit.**

## Weigh the forces

Read the intent and the existing repo, then weigh:

- **Interactivity & shared state** — a mostly-static page with a little scripting wants little; many
  interacting controls sharing state want a component model with real state management.
- **Views & routing** — one screen is trivial; several routed views push you toward a router/framework.
- **SSR / SEO / first-paint** — if content must render server-side or be crawlable, that points at a
  meta-framework (server rendering), not a client-only SPA.
- **Bundle & performance budget** — every dependency ships to the user. A framework must earn its
  kilobytes; on a tiny surface it rarely does.
- **The existing repo** — if there's already a stack/design system in the worktree, extend it. Don't
  introduce a second framework alongside one that's already there.
- **Time & verifiability** — whatever you pick must still run `npm test` + `npx playwright test` green
  within the beat. A stack you can't get to green is the wrong stack.

## Right-size — both directions are failures

- **Over-engineering**: a framework, a router, a state library, a build pipeline for what a single HTML
  file and a few functions would do. This is the more common trap under pressure to look sophisticated.
- **Under-reaching**: hand-rolling routing, reactive state, or DOM diffing that a framework you're
  already pulling in would give you for free. Reinvention is not simplicity.
- When two options both fit, choose the lighter one — it's faster to build, test, and re-run.

## A rough map (not a mandate)

- **No framework (HTML + ES modules)** — static or lightly-interactive single surfaces. See
  `es-module-architecture` for the pure/view seam and `unit-testing-with-node-test` for the runner.
- **A component framework (React, Vue, Svelte, …) scaffolded with a build tool** — real interactivity,
  shared state, or several views. Scaffold it with `scaffolding-with-vite`, test components with
  `component-testing`, and if you chose React read `react-doctor` for the common footguns.
- **A meta-framework (server rendering / routing built in)** — when SSR/SEO or many routes dominate.
- Whatever you pick, `playwright-e2e-authoring` proves the real app in a browser regardless of stack.

## Before you finish

1. Can you state, in one sentence, which stack you chose and the single biggest reason?
2. Does the complexity of the app actually justify the weight of the stack — no dead framework, no
   reinvented framework?
3. Did you check the existing repo and extend rather than duplicate its stack?
4. Is the decision + trade-off written in `test_evidence/summary.md`, and does the app reach green with
   it?
