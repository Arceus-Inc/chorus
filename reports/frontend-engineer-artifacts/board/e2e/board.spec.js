import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => window.localStorage.clear());
});

test('add a card, move across lanes, refresh, and it stays in Done', async ({ page }) => {
  await page.getByLabel('Task title').fill('Ship sprint 1');
  await page.getByRole('button', { name: 'Add' }).click();

  const todoLane = page.getByRole('region', { name: 'To do' });
  await expect(todoLane.getByText('Ship sprint 1')).toBeVisible();

  await todoLane.getByRole('button', { name: 'Move “Ship sprint 1” to next lane' }).click();
  const inProgressLane = page.getByRole('region', { name: 'In progress' });
  await expect(inProgressLane.getByText('Ship sprint 1')).toBeVisible();

  await inProgressLane.getByRole('button', { name: 'Move “Ship sprint 1” to next lane' }).click();
  const doneLane = page.getByRole('region', { name: 'Done' });
  await expect(doneLane.getByText('Ship sprint 1')).toBeVisible();

  await page.reload();
  await expect(page.getByRole('region', { name: 'Done' }).getByText('Ship sprint 1')).toBeVisible();
});

test('keyboard-only: add, move right twice, then remove', async ({ page }) => {
  await page.getByLabel('Task title').fill('Keyboard only');
  await page.getByRole('button', { name: 'Add' }).press('Enter');

  await page.getByRole('button', { name: 'Move “Keyboard only” to next lane' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('region', { name: 'In progress' }).getByText('Keyboard only')).toBeVisible();

  await page.getByRole('button', { name: 'Move “Keyboard only” to next lane' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('region', { name: 'Done' }).getByText('Keyboard only')).toBeVisible();

  await page.getByRole('button', { name: 'Remove “Keyboard only”' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByText('Keyboard only')).toHaveCount(0);
});
