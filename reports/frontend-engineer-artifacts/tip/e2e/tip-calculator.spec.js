import { test, expect } from '@playwright/test';

test('calculates tip, grand total, and per-person as inputs change', async ({ page }) => {
  await page.goto('/index.html');

  await page.getByLabel('Bill amount').fill('42.50');
  await page.getByLabel('Number of people').fill('3');

  // Default preset is 15%
  await expect(page.getByTestId('tipAmount')).toHaveText('$6.38');
  await expect(page.getByTestId('grandTotal')).toHaveText('$48.88');
  await expect(page.getByTestId('perPerson')).toHaveText('$16.29');

  // Change tip via custom value
  await page.getByLabel('Custom %').fill('20');

  await expect(page.getByTestId('tipAmount')).toHaveText('$8.50');
  await expect(page.getByTestId('grandTotal')).toHaveText('$51.00');
  await expect(page.getByTestId('perPerson')).toHaveText('$17.00');
});
