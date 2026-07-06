import { test, expect } from '@playwright/test';

test('splits a bill with a preset tip', async ({ page }) => {
  await page.goto('/');

  await page.getByLabel('Bill amount ($)').fill('100');
  await page.getByLabel('Tip preset (%)').selectOption('15');
  await page.getByLabel('People sharing').fill('4');

  await expect(page.locator('#tipAmount')).toHaveText('$15.00');
  await expect(page.locator('#totalAmount')).toHaveText('$115.00');
  await expect(page.locator('#perPersonAmount')).toHaveText('$28.75');
});

test('custom tip updates the outputs and never shows NaN/Infinity', async ({ page }) => {
  await page.goto('/');

  await page.getByLabel('Bill amount ($)').fill('50');
  await page.getByLabel('Tip preset (%)').selectOption('custom');
  await page.getByLabel('Custom tip percentage (%)').fill('20');
  await page.getByLabel('People sharing').fill('2');

  await expect(page.locator('#tipAmount')).toHaveText('$10.00');
  await expect(page.locator('#totalAmount')).toHaveText('$60.00');
  await expect(page.locator('#perPersonAmount')).toHaveText('$30.00');

  const resultsText = await page.locator('main').innerText();
  expect(resultsText).not.toMatch(/NaN|Infinity/);
});
