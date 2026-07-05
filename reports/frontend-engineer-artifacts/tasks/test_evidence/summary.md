# Sprint 1 — Buildless to-do app slice (with tests + evidence)

## What I built
A dependency-light, buildless to-do list app that runs directly from `index.html` (served via `python -m http.server`). The UI supports:

- Adding tasks via a labelled text input (“New task”) and an **Add** submit button.
- Rendering each task row with:
  - a checkbox toggle to mark done/undone,
  - a visible text label (the task title),
  - a **Remove** button.
- Filtering tasks with a radio-group control: **All**, **To do**, **Done**.
- An always-visible unfinished count (e.g. “2 tasks remaining”) that stays accurate after add/toggle/remove and when switching filters.

## Architecture / wiring
- **State-driven UI**: the app maintains a single `state` object `{ tasks, filter }` and a `render()` function that re-renders the visible list and remaining count from that state. Event handlers only compute the next state and call `setState(next)`.
- **Pure logic module**: `src/todoState.js` contains the pure state transitions and selectors:
  - `addTask(state, title)` (trims/collapses whitespace; rejects empty)
  - `toggleTask(state, id)`
  - `removeTask(state, id)`
  - `setFilter(state, filter)`
  - `selectVisibleTasks(state)`
  - `selectRemainingCount(state)`

The DOM glue lives in `src/app.js`.

## Resilience / empty states
- If there are no tasks at all, the app shows: “No tasks yet. Add your first one above.”
- If tasks exist but none match the current filter, it shows: “No tasks match this filter.”
- Empty/whitespace-only submissions are rejected and show an inline error message; the app never crashes or white-screens.

## Accessibility decisions
- Semantic structure: `main`, headings, `form`, `fieldset`.
- The add input has a proper `<label for="task-title">`.
- Filters use native **radio inputs** (keyboard-friendly, correct semantics).
- Task completion uses a native **checkbox**; done state is visible both via checkbox state and strikethrough styling (not color alone).
- Remove uses a real `<button>` with an accessible name including the task title (e.g. “Remove Walk dog”).
- Visible focus indicator via `:focus-visible { outline: 3px solid ... }` and high-contrast colors.

## Unit tests (Node test runner)
Location: `tests/todoState.test.js`

Coverage:
- `addTask` adds a trimmed task and rejects empty/whitespace-only titles.
- `toggleTask` flips done/undone and `selectRemainingCount` updates accordingly.
- `removeTask` removes tasks and keeps the remaining count accurate.
- `selectVisibleTasks` returns the correct subset for `all` / `todo` / `done`.

Result (from `test_evidence/unit.txt`): **5 passed, 0 failed**.

## E2E tests (Playwright)
Location: `e2e/todo.spec.js`

Flow exercised:
- Add two tasks.
- Toggle one task to done.
- Switch filters to **To do** and **Done** and assert which tasks are visible.
- Remove a task and assert the remaining count and visible tasks update.

Result (from `test_evidence/e2e.txt`): **1 passed**.

## Commands run
- Unit: `npm run test:unit` (captured to `test_evidence/unit.txt`)
- E2E: `npm run test:e2e` (captured to `test_evidence/e2e.txt`)
