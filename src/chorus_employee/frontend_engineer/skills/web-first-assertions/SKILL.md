---
name: web-first-assertions
description: How to assert on UI state without flakiness — using Playwright's auto-retrying web-first assertions, asserting user-visible outcomes rather than implementation details, and eliminating arbitrary waits.
when_to_use: Read alongside playwright-e2e-authoring while writing the assertions in an e2e spec. It is the difference between a test that proves something and one that flakes or asserts nothing.
---

# Web-First Assertions

The two ways an e2e goes wrong are flaking (passing or failing at random because of timing) and being
hollow (green but proving nothing). Playwright's web-first assertions fix both: they auto-retry until
the condition is met or a timeout elapses, so you assert the *outcome* and let the framework handle the
timing.

## The one rule

**Assert the user-visible outcome with an auto-retrying `expect(locator)` — never sleep, never assert on
internals, never assert something that's true regardless of whether the app worked.**

## Use auto-retrying assertions

- `await expect(locator).toBeVisible()`, `.toHaveText(...)`, `.toContainText(...)`, `.toHaveValue(...)`,
  `.toBeEnabled()` — these poll until they pass or time out. They remove the race without a sleep.
- **Never** `await page.waitForTimeout(1000)`. A fixed sleep is both slow and flaky; it's the classic
  source of "passes on my machine". Wait for the *condition*, not the clock.

## Assert what the user sees

- Assert the observable result of the action: the result text appeared, the count updated, the error
  banner is visible, the button is now disabled. That's what "it works" means to a user.
- Don't assert implementation details (a class name, an internal variable). They pass while the UI is
  broken and break when you refactor working code.

## Make it a real proof

- Every assertion should be one that would **fail if the feature were broken**. `expect(page).toHaveURL`
  after a `goto` proves navigation, not your feature — go further and assert the feature's output.
- Assert on a role/label/text locator so the assertion also quietly checks the element is accessible.

## Before you finish

1. Are all assertions auto-retrying `expect(locator)` calls — zero `waitForTimeout`?
2. Do they assert user-visible outcomes, not class names or internals?
3. Would each assertion actually fail if the feature broke?
4. Did the spec stay green across a couple of runs (no intermittent failures)?
