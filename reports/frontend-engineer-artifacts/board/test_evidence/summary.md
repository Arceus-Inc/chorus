# Sprint 1 — run-board

## What shipped

A dependency-light, static three-lane task board you can open via `python -m http.server` and load `index.html`.

User-visible behavior:
- The board always renders **exactly three lanes**: **To do**, **In progress**, and **Done**.
- You can add a new task using the **“Task title”** text input and the **“Add”** button. New tasks always start in **To do**.
- Each card has explicit controls to:
  - **Move left** (to the previous lane)
  - **Move right** (to the next lane)
  - **Remove** (delete the card)
- All mutations persist to **`localStorage`**; refreshing the page restores the same cards in the same lanes.

Implementation notes:
- Pure logic lives in `src/boardState.js` (add/move/remove + persistence encode/decode).
- DOM wiring lives in `src/app.js` and renders from a single in-memory state object.

## Accessibility & keyboard operability

- Semantic elements by construction:
  - Add flow is a real `<form>` with a `<label for>` and a submit `<button>`.
  - Card actions are real `<button>` elements (no clickable divs).
  - Lanes are `<section>` elements labeled by headings, so automated tests (and AT) can locate them as **regions**.
- Every interactive control has an accessible name:
  - “Add” button is named by its visible label.
  - Move/remove buttons include specific `aria-label` text like `Move “{title}” to next lane` and `Remove “{title}”`.
- Keyboard-only operation:
  - Tab reaches the input and every card control.
  - Buttons activate via Enter/Space (native button behavior).
  - Focus is visible via `:focus-visible` outline with a high-contrast ring.

## Resilience

- Empty lanes render an “Empty.” hint (no blank/white screen).
- Storage failures are handled with a non-blocking alert message; the app still renders and works in-memory.

## Unit tests (Node)

- Runner: `node --test`
- File: `tests/boardState.test.js`
- Coverage:
  - `addCard` trims input, requires a non-empty title, and adds into the `todo` lane.
  - `moveCard` enforces adjacent-lane moves only and blocks moving past the ends.
  - `removeCard` removes by id and is a no-op when the id doesn’t exist.
  - `encodeState`/`decodeState` round-trip and corrupted/wrong-shape decode fallback to an empty board.

Result: **8/8 unit tests passed** (see `test_evidence/unit.txt`).

## E2E tests (Playwright)

- Runner: `npx playwright test`
- File: `e2e/board.spec.js`
- Coverage:
  1. Adds a card, moves it across lanes into **Done**, refreshes the page, and verifies it is still visible in the **Done** lane.
  2. Verifies **keyboard-only** operation by focusing buttons and using **Enter** to move a card and then remove it.

Result: **2/2 e2e tests passed** (see `test_evidence/e2e.txt`).

## Known gaps / tradeoffs

- Focus after remove currently returns to the add input (simple and predictable). A more elaborate approach could focus the next card in the lane, but wasn’t required for this slice.
