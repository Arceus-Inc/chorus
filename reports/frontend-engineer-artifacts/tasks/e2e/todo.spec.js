import { test, expect } from '@playwright/test';

test('to-do flow: add, toggle, filter, remove, remaining count', async ({ page }) => {
  await page.goto('/');

  const title = page.getByLabel('New task');
  const add = page.getByRole('button', { name: 'Add' });
  const remaining = page.getByLabel('Unfinished tasks count');
  const list = page.getByRole('list');

  // Add two tasks
  await title.fill('Buy milk');
  await add.click();
  await expect(list.getByText('Buy milk')).toBeVisible();
  await expect(remaining).toHaveText('1 task remaining');

  await title.fill('Walk dog');
  await add.click();
  await expect(list.getByText('Walk dog')).toBeVisible();
  await expect(remaining).toHaveText('2 tasks remaining');

  // Mark "Walk dog" done
  await page.getByRole('checkbox', { name: 'Mark Walk dog as done' }).click();
  await expect(remaining).toHaveText('1 task remaining');

  // Filter to To do -> only Buy milk visible
  await page.getByRole('radio', { name: 'To do' }).check();
  await expect(list.getByText('Buy milk')).toBeVisible();
  await expect(list.getByText('Walk dog')).toHaveCount(0);
  await expect(remaining).toHaveText('1 task remaining');

  // Filter to Done -> only Walk dog visible
  await page.getByRole('radio', { name: 'Done' }).check();
  await expect(list.getByText('Walk dog')).toBeVisible();
  await expect(list.getByText('Buy milk')).toHaveCount(0);

  // Remove the done task
  await page.getByRole('button', { name: 'Remove Walk dog' }).click();
  await expect(list.getByText('Walk dog')).toHaveCount(0);
  await expect(remaining).toHaveText('1 task remaining');

  // All -> only Buy milk
  await page.getByRole('radio', { name: 'All' }).check();
  await expect(list.getByText('Buy milk')).toBeVisible();
});
