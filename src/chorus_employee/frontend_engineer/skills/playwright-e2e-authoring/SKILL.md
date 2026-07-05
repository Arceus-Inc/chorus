---
name: playwright-e2e-authoring
description: How to set up and write a Playwright end-to-end test that drives the real app in a real browser — a minimal playwright.config.js with a webServer, role/label locators, and a spec that exercises the core user flow.
when_to_use: Read while writing your e2e specs, whatever stack you chose. It pairs with web-first-assertions (how to assert) and test-evidence-discipline (how to capture the run); the browsers are already cached on this machine.
---

# Playwright E2E Authoring

Unit tests prove the logic; only a real browser proves the *app*. Playwright loads your app in a real
browser, clicks and types like a user, and asserts on what the user sees. It is **stack-neutral** — it
drives the rendered DOM identically whether that DOM came from hand-written HTML, React, Vue, Svelte, or
anything else — which is exactly why it's the e2e proof here. The browsers are already installed on this
machine, so the only setup is the dev dependency and a small config.

## The one rule

**One e2e that drives the real app the way a user does — navigate, click, type — and asserts a visible
outcome of the core flow. That test is your proof the app works.**

## Set it up

```js
// playwright.config.js (or .ts)
import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './e2e',
  use: { baseURL: 'http://127.0.0.1:4173' },
  webServer: {
    // Serve the app HOWEVER your chosen stack serves it — Playwright starts this itself.
    //   static / no build:     'python -m http.server 4173'   (or 'npx serve -l 4173')
    //   a built bundle:         'npm run build && npm run preview -- --port 4173'
    //   a dev server:           'npm run dev -- --port 4173'
    command: 'npm run preview -- --port 4173',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: true,
  },
});
```

- `npm install -D @playwright/test` (you'll already have a `package.json` from scaffolding your stack).
  No `npx playwright install` is needed — the browsers are cached.
- `webServer` lets Playwright start the server itself, so the run is self-contained. Point `command` at
  whatever serves YOUR build; keep `baseURL`/`url`/port in sync.

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

1. Is there a `playwright.config.*` whose `webServer` serves the app the way your stack serves it?
2. Does the spec navigate, perform the real user action, and assert a user-visible outcome?
3. Are locators role/label/text-based, not brittle CSS?
4. Did you actually run `npx playwright test` and see it pass?
