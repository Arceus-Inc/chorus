import { test, expect } from '@playwright/test';

test('delete removes transaction from list and persists after reload', async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => localStorage.clear());
  await page.reload();

  await page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: 'Add' }).click();
  await page.getByLabel('Description').fill('Delete me');
  await page.getByLabel('Amount').fill('5');
  await page.getByLabel('Category').selectOption('Other');
  await page.getByRole('button', { name: 'Add transaction' }).click();

  await expect(page.getByRole('cell', { name: 'Delete me' })).toBeVisible();

  const href = await page.getByRole('link', { name: 'View / edit' }).getAttribute('href');
  await page.goto(href);

  page.once('dialog', (d) => d.accept());
  await page.getByRole('button', { name: 'Delete transaction' }).click();

  await expect(page.getByRole('heading', { name: 'Transactions' })).toBeVisible();
  await expect(page.getByRole('cell', { name: 'Delete me' })).toHaveCount(0);

  await page.reload();
  await expect(page.getByRole('cell', { name: 'Delete me' })).toHaveCount(0);
});
