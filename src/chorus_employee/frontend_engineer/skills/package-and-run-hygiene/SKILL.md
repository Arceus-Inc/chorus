---
name: package-and-run-hygiene
description: How to keep the project runnable and dependency-light — initializing package.json only when needed, adding tools as devDependencies, avoiding needless runtime deps, and keeping the app buildless so it serves straight off a static server.
when_to_use: Read when setting up the project scaffolding and pulling in Playwright. It keeps the app fast to run and easy to verify; the browsers are already cached so no install step is needed.
---

# Package & Run Hygiene

A small web app should stay small: no bundler, no framework you don't need, no dependency that pulls in
a hundred more. Keeping it buildless and dependency-light makes it start instantly, test reliably, and
survive the after-beat re-run without surprises.

## The one rule

**The app runs with no build step off a static server; the only dependencies are the test tools, and
they're devDependencies.**

## Scaffold minimally

- `npm init -y` once to get a `package.json` (needed so `@playwright/test` resolves). Keep it lean.
- Install test tooling as **dev** dependencies: `npm install -D @playwright/test`. Unit tests need
  nothing — `node --test` is built in.
- Do **not** run `npx playwright install`: the browsers are already cached on this machine. Installing
  them again wastes the beat and can fail offline.

## Stay buildless and dependency-light

- Ship native ES modules loaded by the browser (`<script type="module">`), so `python -m http.server`
  serves the app directly — no webpack/vite/rollup.
- Add a runtime dependency only when vanilla JS genuinely can't do the job. Every dep is surface area
  that can break the run; most small apps need zero.
- If you add scripts to `package.json` (`"test": "node --test"`, `"e2e": "playwright test"`), keep them
  obvious and matching how the evidence is captured.

## Keep it reproducible

- Reference the app by relative paths so it works from any checkout.
- Don't commit `node_modules`; don't rely on a global install. The devDependency in `package.json` is
  the contract.

## Before you finish

1. Does the app run with no build step, straight off `python -m http.server`?
2. Are test tools devDependencies, with zero needless runtime deps?
3. Did you avoid re-installing the cached Playwright browsers?
4. Are paths relative so a fresh checkout runs the same way?
