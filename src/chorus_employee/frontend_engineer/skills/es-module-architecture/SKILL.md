---
name: es-module-architecture
description: How to structure a vanilla-JS app into small ES modules with a testable seam — pure logic (reducers, formatters, validation) separated from DOM glue — so the logic can be unit-tested by importing it directly.
when_to_use: Read while deciding how to split files. It is the structure that makes unit-testing-with-node-test possible and keeps state-driven-ui's reducer pure and importable.
---

# ES Module Architecture

Logic tangled into DOM event handlers can't be unit-tested and is hard to reason about. The single most
valuable structural decision in a small web app is to pull the pure logic out of the DOM glue, so you
can `import` it into a Node test and check it directly, with no browser.

## The one rule

**Pure logic lives in modules with no DOM references; DOM glue imports that logic. The seam between them
is where your unit tests plug in.**

## Separate pure logic from the DOM

- **Pure modules** — reducers/state updates, formatters, parsers, validation, calculations — take
  inputs and return outputs. No `document`, no `window`, no side effects. Export named functions.
- **Glue module** — reads the DOM, calls the pure functions, writes the DOM, wires event listeners. It's
  thin: it translates events into state updates and state into DOM.
- Because the pure module never touches the DOM, `import { reducer } from './logic.js'` works verbatim
  under `node --test`.

## Keep modules small and single-purpose

- One responsibility per module; a clear name that says what it does. If a module both computes and
  renders, split it.
- Prefer named exports (they're greppable and tree-shakeable). Avoid a giant do-everything file.
- No needless dependency — vanilla JS covers the vast majority of a small app. Reach for a library only
  when it earns its weight.

## Load without a build step

- Use native ES modules in the browser: `<script type="module" src="./app.js">`, and `import` between
  your files with relative paths. This runs directly off `python -m http.server` — no bundler.

## Before you finish

1. Can you `import` your core logic into a Node test with zero DOM mocking? If not, the seam is wrong.
2. Is each module single-purpose with a clear name, and is the DOM glue thin?
3. Did you avoid dependencies vanilla JS would have covered?
4. Does it run as native ES modules with no build step?
