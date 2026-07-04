---
name: playwright-e2e-authoring
description: How to set up and write a Playwright end-to-end test that drives the real app in a real browser — a minimal playwright.config.js with a webServer, role/label locators, and a spec that exercises the core user flow.
when_to_use: Read while writing specs under e2e/. It pairs with web-first-assertions (how to assert) and test-evidence-discipline (how to capture the run); the browsers are already cached on this machine.
---

# Playwright E2E Authoring

Unit tests prove the logic; only a real browser proves the *app*. Playwright loads your `index.html`,
clicks and types like a user, and asserts on what the user sees. The browsers are already installed on
this machine, so the only setup is the dev dependency and a small config.

## The one rule

**One e2e that drives the real app the way a user does — navigate, click, type — and asserts a visible
outcome of the core flow. That test is your proof the app works.**

## Set it up

```js
// playwright.config.js
import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './e2e',
  use: { baseURL: 'http://127.0.0.1:4173' },
  webServer: {
    command: 'python -m http.server 4173',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: true,
  },
});
```

- `npm init -y` once, then `npm install -D @playwright/test`. No `npx playwright install` is needed —
  the browsers are cached.
- `webServer` lets Playwright start the static server itself, so the run is self-contained.

## Write the spec

```js
import { test, expect } from '@playwright/test';

test('user searches and sees a result', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('City').fill('Paris');
  await page.getByRole('button', { name: 'Search' }).click();
  await expect(page.getByRole('status')).toContainText('Paris');
});
```

- Locate elements by **role, label, or text** (`getByRole`, `getByLabel`, `getByText`) — the way users
  and assistive tech find them. Avoid brittle CSS/`nth` selectors that break on the smallest change.
- Drive the actual flow (`fill`, `click`, `press`), then assert the visible result — not just that the
  page loaded.

## Before you finish

1. Is there a `playwright.config.js` whose `testDir` is `./e2e` and whose `webServer` serves the app?
2. Does the spec navigate, perform the real user action, and assert a user-visible outcome?
3. Are locators role/label/text-based, not brittle CSS?
4. Did you actually run `npx playwright test` and see it pass?
