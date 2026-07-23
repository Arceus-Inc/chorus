# Budget tracker — sprint 1 summary

## Stack choice + rationale

**Chosen stack:** React + React Router + Vite (SPA), unit tests with **Vitest**, end-to-end tests with **Playwright**.

**Why this stack:** The acceptance criteria require **multiple routed screens with real URLs**, deep-linking directly to a specific transaction detail route, and reliable back/forward navigation while keeping shared in-memory state (the transaction list) consistent across pages. React Router cleanly owns the routing/history behavior, and React makes shared state + immediate UI updates after add/edit/delete straightforward without hand-rolled DOM/routing code. Vite keeps the build/test loop fast and predictable.

Trade-off: this is heavier than a no-framework vanilla approach, but the app’s requirements (routing + shared CRUD state + accessible forms + tests) justify a component framework and router.

## What was built

A multi-screen budget tracker SPA with these routes:

- `/` — **Dashboard**: shows total spent for the current month and a breakdown by category.
- `/transactions` — **Transactions list**: shows all stored transactions, with search-by-text and category filter (stored in the URL query params for share/back/forward).
- `/add` — **Add transaction**: description, positive amount, category, date.
- `/transactions/:id` — **Transaction detail/edit**: edit any field and save, or delete.

### Persistence

Transactions are persisted to `localStorage` under the key `budgetTracker.transactions.v1`.

- On app start, the provider loads transactions from storage.
- Any add/update/delete dispatch updates React state; a `useEffect` persists the updated list back to storage.
- This supports refresh/browser restart persistence and direct linking to a detail route.

### Domain logic seam

Pure logic lives in `src/domain/*` (validation, filtering/search, monthly totals, category rollups, storage adapter). UI reads/writes through the reducer and uses the domain functions to derive dashboard metrics and list filtering.

## Accessibility decisions

- Semantic landmarks: `header` (banner), `nav` with `aria-label="Primary"`, `main`.
- Keyboard operability: native links/buttons/inputs, standard tab order; visible focus ring via CSS `outline`.
- Forms:
  - Proper `<label htmlFor>` for every input.
  - Field-level validation errors shown as text and wired via `aria-describedby` + `aria-invalid`.
  - Submit button is **disabled until the form is valid**, and a submit attempt reveals per-field errors (screen readers will announce via `role="alert"`).

## Responsive behavior

Mobile-first single-column layout, with a denser multi-column dashboard at wider widths:

- On narrow viewports, dashboard stacks into one column with no horizontal scrolling.
- At `min-width: 860px`, the dashboard uses a two-column grid and the controls/table spacing is denser.

## Tests

### Unit tests (npm test)

Vitest unit tests cover:

- Validation rules: required fields, positive amount, allowed categories, valid ISO date.
- Aggregation: current-month total spent and category breakdown.
- Search/filter behavior (query + category filter combination).

Result: see `test_evidence/unit.txt` (8 tests passed).

### E2E tests (npx playwright test)

Playwright covers:

- Routing across screens (Dashboard → Add → Transactions).
- Add form validation + submit disabled until valid.
- Persistence across reload (transaction remains after refresh).
- Deep-link to a specific transaction detail route and **edit** flow.
- Back/forward navigation behavior.
- Responsive assertions: no horizontal scroll at phone width; multi-column grid at desktop width.

Result: see `test_evidence/e2e.txt` (2 tests passed).

## Known gaps / trade-offs

- Delete flow is implemented (with a native confirm) but the main e2e focuses on the edit path rather than delete; delete can be added as a follow-up scenario if needed.
- Currency is formatted as USD for simplicity.
