import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => localStorage.clear());
  await page.reload();
});

test('routing + add validation + persistence across reload + edit flow', async ({ page }) => {
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();

  await page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: 'Add' }).click();
  await expect(page.getByRole('heading', { name: 'Add transaction' })).toBeVisible();

  const addBtn = page.getByRole('button', { name: 'Add transaction' });
  await expect(addBtn).toBeDisabled();

  await page.getByLabel('Description').fill('Test lunch');
  await expect(addBtn).toBeDisabled();

  await page.getByLabel('Amount').fill('12.50');
  await expect(addBtn).toBeDisabled();

  await page.getByLabel('Category').selectOption('Dining');
  await expect(addBtn).toBeEnabled();

  await addBtn.click();

  await expect(page.getByRole('heading', { name: 'Transactions' })).toBeVisible();
  await expect(page.getByRole('cell', { name: 'Test lunch' })).toBeVisible();

  await page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: 'Dashboard' }).click();
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Total spent this month' })).toContainText('$12.50');

  await page.reload();
  await page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: 'Transactions' }).click();
  await expect(page.getByRole('cell', { name: 'Test lunch' })).toBeVisible();

  const href = await page.getByRole('link', { name: 'View / edit' }).getAttribute('href');
  await page.goto(href);
  await expect(page.getByRole('heading', { name: 'Edit transaction' })).toBeVisible();

  await page.getByLabel('Description').fill('Test lunch updated');
  await page.getByRole('button', { name: 'Save changes' }).click();

  await expect(page.getByRole('heading', { name: 'Transactions' })).toBeVisible();
  await expect(page.getByRole('cell', { name: 'Test lunch updated' })).toBeVisible();

  await page.goBack();
  await expect(page.getByRole('heading', { name: 'Edit transaction' })).toBeVisible();
  await page.goForward();
  await expect(page.getByRole('heading', { name: 'Transactions' })).toBeVisible();
});

test('responsive: no horizontal scroll on core routes at phone width', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });

  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
  let hasHScroll = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth
  );
  expect(hasHScroll).toBe(false);

  await page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: 'Transactions' }).click();
  await expect(page.getByRole('heading', { name: 'Transactions' })).toBeVisible();
  hasHScroll = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth
  );
  expect(hasHScroll).toBe(false);

  await page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: 'Add' }).click();
  await expect(page.getByRole('heading', { name: 'Add transaction' })).toBeVisible();
  hasHScroll = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth
  );
  expect(hasHScroll).toBe(false);
});

test('responsive: dashboard uses denser multi-column layout at desktop', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 800 });
  await page.goto('/');

  const dashboardPanel = page.getByRole('heading', { name: 'Dashboard' }).locator('..').locator('..');
  const breakdownPanel = page.getByRole('heading', { name: 'Spending by category' }).locator('..').locator('..');

  const dashBox = await dashboardPanel.boundingBox();
  const breakBox = await breakdownPanel.boundingBox();

  expect(dashBox).not.toBeNull();
  expect(breakBox).not.toBeNull();

  // side-by-side: the left edge of the breakdown panel should be to the right of the dashboard panel
  expect(breakBox.x).toBeGreaterThan(dashBox.x + dashBox.width * 0.6);
});
