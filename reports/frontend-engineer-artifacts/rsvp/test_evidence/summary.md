# Sprint 1 — RSVP page (buildless)

## What I built

A dependency-light, buildless RSVP page served as static files (`index.html` + ES modules under `src/`).

The page renders an RSVP form that collects:
- Guest name
- Email address
- Number of attendees (1–10)
- Vegetarian meal needed? (Yes/No radio group)

As the user fills the form, the **Confirm RSVP** button stays disabled until every field is valid. On a valid submit, the form is replaced with a confirmation view that repeats back the submitted values.

## How it works (wiring)

- `src/validation.js` contains pure validation + normalization functions:
  - `validateName`, `validateEmail`, `validateAttendees`, `validateVegetarian`
  - `validateAll(values)` returns `{ errors, isValid }`
  - `normalizeSubmission(values)` trims strings and converts types (attendees number; vegetarian boolean)
- `src/app.js` owns DOM wiring and rendering.
  - State is kept in a single object with `status` (`editing` / `confirmed`), current `values`, `touched`, and `submitted`.
  - Rendering is derived from state; on each update we re-render the form/confirmation.
  - Submit is guarded: on submit attempt we mark all fields touched, validate, and if invalid we **focus the first invalid field**.

## Accessibility decisions

- Semantic HTML controls are used: `<form>`, `<label for>`, `<input>`, and a `<fieldset>/<legend>` for the vegetarian radio group.
- Inline, field-specific errors are exposed to assistive tech:
  - When a field has an error, its control gets `aria-invalid="true"`.
  - Error text is programmatically associated via `aria-describedby` pointing at the error element id.
  - For the radio group, both radios and the fieldset receive invalid state, and the error text id is used as `aria-describedby` for the radios.
- Full keyboard operation is supported because controls are native form controls; the submit button is reachable and can be activated via Enter/Space.
- A visible focus indicator is provided via `:focus-visible` outline styling.
- Colors were chosen to keep high contrast for text and error messages on the dark background.

## Tests

### Unit tests

- `tests/validation.test.js` uses Node’s built-in runner (`node --test`) to cover:
  - required/boundary behavior for each validator
  - `validateAll` returning field-specific errors and correct `isValid`
  - `normalizeSubmission` trimming and type conversions

### E2E test (Playwright)

- `e2e/rsvp.spec.js` drives the core happy path in a real browser:
  1) visits the page
  2) confirms the submit button is disabled until all fields are completed
  3) fills name, email, attendee count, selects vegetarian = Yes
  4) submits and asserts the confirmation view is visible and repeats back the values

## Results

- Unit suite: PASS (see `test_evidence/unit.txt`)
- E2E suite: PASS (see `test_evidence/e2e.txt`)
