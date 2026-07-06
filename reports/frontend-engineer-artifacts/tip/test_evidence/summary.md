# Sprint 1 — Tip + bill splitter (run-tip)

## What I built
A single-page, dependency-light tip + bill splitting helper (served as static files) with live-updating results.

- **Entry point:** `index.html`
- **UI wiring:** `src/app.js`
- **Pure logic (unit-testable):** `src/calc.js`

### User-visible behavior (definition of working)
On one page, the user can enter:
1) **Bill amount** (dollars),
2) **Tip preset** (select a common percent or choose **Custom…**), and
3) **People sharing**.

As any input changes, the page immediately updates three outputs:
- **Tip amount** (USD, 2 decimals)
- **Total (with tip)** (USD, 2 decimals)
- **Per person** (USD, 2 decimals)

The computation matches the spec:
- `tip = bill * tipPercent/100`
- `total = bill + tip`
- `perPerson = total / people`

## State handling / stability
The UI is designed to never show **NaN**, **Infinity**, or negative currency values.

- When inputs are **empty or invalid**, results remain a sensible non-error state: **$0.00** for all outputs.
- Values are only computed when **bill > 0**, **people >= 1**, and **tipPercent >= 0**.
- Invalid values are handled in a user-correctable way (no “white screen” states):
  - Bill is clamped to **min 0**.
  - People is floored to an integer and clamped to **min 1**.
  - Tip percent is clamped to **min 0**.
- Money formatting is always `$D.CC` via `formatUSD()`.

## Accessibility decisions
Built accessibly from the start:
- **Landmarks:** exactly one `<main>` landmark (header uses a normal `<div>` wrapper).
- **Native controls** only (`input`, `select`) so keyboard operation is automatic.
- Every input has a **visible label** using `label` + `for`:
  - “Bill amount ($)”, “Tip preset (%)”, optional “Custom tip percentage (%)”, “People sharing”.
- Results are a semantic **description list** (`dl`/`dt`/`dd`) and are announced with `aria-live="polite"`.
- A strong visible **focus ring** is provided with `:focus-visible`.
- Text/background contrast was chosen to be comfortably readable (light text on dark panels).

## Unit tests (Node built-in runner)
- Location: `tests/calc.test.js`
- What they cover:
  - Parsing behavior for **empty**, **invalid**, and **valid** numeric inputs.
  - Sanitization rules (clamping negatives, flooring people).
  - Calculation outputs for valid inputs.
  - Guard behavior when the app **cannot compute** yet (returns zeros).
  - Formatting guarantees: always **two decimals** and never negative/NaN/Infinity.

**Unit result:** PASS (6 tests)

## End-to-end tests (Playwright)
- Location: `e2e/tip-splitter.spec.js`
- What they exercise:
  - Fill bill + people, choose a **preset tip** and assert visible `$` outputs.
  - Choose **Custom…**, enter a custom tip percent, assert outputs, and verify the page does not contain “NaN”/“Infinity”.

**E2E result:** PASS (2 tests)

## Captured run logs
- `test_evidence/unit.txt` contains the real `node --test` output.
- `test_evidence/e2e.txt` contains the real `playwright test` output.

## Tradeoffs / known gaps
- The app intentionally stays minimal and does not attempt to enforce currency locale beyond USD `$` + 2 decimals.
- Inline error messaging is lightweight and non-blocking; results remain stable at $0.00 until inputs are valid.
