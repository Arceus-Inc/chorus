---
name: es-module-architecture
description: How to separate pure logic (reducers, formatters, validation) from the view/DOM glue so the logic can be unit-tested by importing it directly — shown with vanilla ES modules, but the same seam applies to any stack.
when_to_use: Read while deciding how to split files, whatever stack you chose. The pure/view seam is what makes fast unit tests possible in vanilla, React, Vue, or Svelte alike; `component-testing` covers testing the view layer on top of it.
---

# Module Architecture: the pure/view seam

Logic tangled into the view (DOM event handlers, or a component body) can't be unit-tested and is hard
to reason about. The single most valuable structural decision in any frontend app is to pull the pure
logic out of the view glue, so you can `import` it into a test and check it directly, with no browser.
This is shown below with vanilla ES modules; the **same seam exists in every framework** — pure
reducers/selectors/helpers separated from components — and it's what keeps a framework app testable too.

## The one rule

**Pure logic lives in modules with no DOM references; DOM glue imports that logic. The seam between them
is where your unit tests plug in.**

## Separate pure logic from the DOM

- **Pure modules** — reducers/state updates, formatters, parsers, validation, calculations — take
  inputs and return outputs. No `document`, no `window`, no side effects. Export named functions.
- **Glue module** — reads the DOM, calls the pure functions, writes the DOM, wires event listeners. It's
  thin: it translates events into state updates and state into DOM.
- Because the pure module never touches the view, `import { reducer } from './logic.js'` works verbatim
  under your unit runner — no browser, no mocking. That's the whole point of the seam.

## Keep modules small and single-purpose

- One responsibility per module; a clear name that says what it does. If a module both computes and
  renders, split it.
- Prefer named exports (they're greppable and tree-shakeable). Avoid a giant do-everything file.
- No needless dependency — for a small app vanilla JS often covers it; for a richer app a framework
  earns its weight. Either way, don't reinvent what your chosen stack already gives you.

## The vanilla realization (no build step)

- With no framework, use native ES modules in the browser: `<script type="module" src="./app.js">`, and
  `import` between your files with relative paths. This runs directly off a static server — no bundler.
- With a framework, you don't hand-wire this — the scaffold (e.g. via `scaffolding-with-vite`) sets up
  module resolution and the build for you. The pure/view seam above still applies inside it.

## Before you finish

1. Can you `import` your core logic into a test with zero DOM/component mocking? If not, the seam is wrong.
2. Is each module single-purpose with a clear name, and is the view glue thin?
3. Did you avoid dependencies your chosen stack would have covered (no reinvention, no dead weight)?
4. Does the project actually run and its unit tests pass through `npm test`?
