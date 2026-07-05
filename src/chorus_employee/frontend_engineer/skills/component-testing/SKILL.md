---
name: component-testing
description: How to unit-test framework components with Vitest and Testing Library — rendering a component, querying by role/label like a user, driving interaction, and asserting behavior without leaning on implementation details.
when_to_use: Read when your stack is a framework (React, Vue, Svelte, …) and you're writing the unit/component layer. It is the framework counterpart to unit-testing-with-node-test; wire it to `npm test` and pair it with Playwright for the full-app proof.
---

# Component Testing

When you chose a framework, your unit layer tests **components**, not just plain functions. Vitest (the
Vite-native runner) plus Testing Library renders a component into a real DOM, lets you query it the way
a user would, and asserts on behavior. The discipline is the same as any unit test: prove real behavior
across the branches that matter, and never assert nothing.

## The one rule

**Render the component, query by role/label/text like a user, drive the real interaction, and assert
the user-visible result — test behavior, not implementation details.**

## Set it up

```bash
npm install -D vitest @testing-library/dom @testing-library/user-event
# framework binding: @testing-library/react, /vue, or svelte-testing-library
```

- Wire it run-once in `package.json`: `"test": "vitest run"` (bare `vitest` watches and will HANG the
  non-interactive re-run). Use a `jsdom`/`happy-dom` environment for DOM rendering.
- `npm test` must map to this so the captured `unit.txt` and the DoD re-run line up.

## The shape (React example; the pattern is the same in every binding)

```js
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { test, expect } from 'vitest';
import Counter from '../src/Counter';

test('increments the count when the user clicks', async () => {
  render(<Counter />);
  await userEvent.click(screen.getByRole('button', { name: /increment/i }));
  expect(screen.getByText('Count: 1')).toBeInTheDocument();
});
```

## Query and assert like a user

- Prefer `getByRole` / `getByLabelText` / `getByText` — the accessible queries. If you can't find a
  control by its role or label, that's an accessibility bug the test just surfaced.
- Drive interaction with `userEvent` (real click/type/tab), not by calling handlers directly.
- Assert the **rendered outcome** the user sees. Don't assert on state variables, internal method
  calls, or CSS classes — those are implementation details that make the test brittle and hollow.

## Keep tests genuine

- Test each meaningful branch: the happy path, the boundaries, and the error/empty states.
- Still separate pure logic (reducers/selectors/formatters) and test it directly — see
  `es-module-architecture`; component tests are for the rendered behavior on top of it.
- A test that renders and asserts nothing, or asserts a class name it also set, proves nothing — a
  reviewer will (rightly) call it a blocker.

## Before you finish

1. Is `npm test` wired to `vitest run` (run-once, no watch mode)?
2. Do tests query by role/label and drive real user interaction?
3. Do they assert the user-visible outcome, not implementation details?
4. Are branches/error states covered, and did you capture a real green run into `unit.txt`?
