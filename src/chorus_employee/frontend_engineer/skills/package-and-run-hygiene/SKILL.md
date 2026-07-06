---
name: package-and-run-hygiene
description: How to keep the project reproducible and dependency-light whatever stack you chose — a real package.json with wired, CI-safe scripts, tools as devDependencies, no needless runtime deps, and a clean checkout that runs the same way twice.
when_to_use: Read when setting up your project scaffolding and wiring npm scripts. It keeps the app fast to run and reliable to verify; the Playwright browsers are already cached so no install step is needed.
---

# Package & Run Hygiene

However you build — hand-written HTML/JS, or a framework you scaffolded — the project has to run the
same way twice: on your machine, and in the after-beat re-run that re-executes `npm test` and
`npx playwright test`. Dependency-light, reproducible, and CI-safe scripts are what make that reliable.

## The one rule

**A real `package.json` with wired, CI-safe scripts; the only dependencies are the ones the app and its
tests actually need; a fresh checkout runs identically.**

## Wire the scripts the verifier expects

- A `"test"` script that runs your UNIT tests to completion and exits — `node --test`, `vitest run`,
  `jest`, whatever your stack uses. It must be non-interactive.
- Serve the app for e2e however your stack serves it (a static server, `vite preview`, a dev server) —
  wire it into the Playwright `webServer`, and add a `"build"`/`"preview"` script if your stack needs it.
- Keep script names obvious and matching how the evidence is captured (`npm test` → `unit.txt`).

## Make every script CI-safe

- The re-run is non-interactive. A watch mode that never exits will HANG the beat and fail the floor.
- Use the run-once form: `vitest run` (not bare `vitest`), `jest --ci`, `node --test`. If a tool
  defaults to watch, pass the flag or set `CI=1` so it runs once and exits.
- Prefer `npm ci` over `npm install` when a lockfile exists — it's reproducible and faster.

## Right-size dependencies

- Add a dependency only when it earns its place. A framework is worth it when the app has real
  interactivity, shared state, or many views; it's dead weight on a mostly-static page. Both
  over- and under-reaching are hygiene failures — see `choosing-a-frontend-stack`.
- Install test tooling as **dev** dependencies: `npm install -D @playwright/test` (plus your unit
  runner, if it isn't built in). Node's `node --test` needs nothing extra.
- Do **not** run `npx playwright install`: the browsers are already cached on this machine. Installing
  them again wastes the beat and can fail offline.

## Keep it reproducible

- Reference assets by relative paths so it works from any checkout.
- Don't commit `node_modules`; don't rely on a global install. `package.json` (plus a lockfile) is the
  contract.

## Before you finish

1. Is there a real `package.json` with a wired, non-interactive `"test"` script?
2. Are your test/serve scripts CI-safe — do they run once and EXIT (no watch mode)?
3. Are tools devDependencies, with dependencies right-sized to the problem (no dead weight)?
4. Did you avoid re-installing the cached Playwright browsers, and keep paths relative?

