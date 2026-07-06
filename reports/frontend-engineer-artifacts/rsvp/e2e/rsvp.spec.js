import { test, expect } from '@playwright/test';

test('RSVP form enables submit when valid and shows a confirmation view', async ({ page }) => {
  await page.goto('/');

  const submit = page.getByRole('button', { name: 'Confirm RSVP' });
  await expect(submit).toBeDisabled();

  await page.getByLabel('Guest name').fill('Ada Lovelace');
  await expect(submit).toBeDisabled();

  await page.getByLabel('Email address').fill('ada@example.com');
  await expect(submit).toBeDisabled();

  await page.getByLabel('Number of attendees').fill('2');
  await expect(submit).toBeDisabled();

  await page.getByLabel('Yes').check();
  await expect(submit).toBeEnabled();

  await submit.click();

  await expect(page.getByRole('heading', { name: 'RSVP confirmed' })).toBeVisible();
  await expect(submit).toHaveCount(0);

  await expect(page.getByText('Ada Lovelace', { exact: true })).toBeVisible();
  await expect(page.getByText('ada@example.com', { exact: true })).toBeVisible();
  await expect(page.getByText('2', { exact: true })).toBeVisible();
  await expect(page.getByText('Yes', { exact: true })).toBeVisible();
});

test('attempting to submit an invalid form focuses the first invalid field', async ({ page }) => {
  await page.goto('/');

  // Start with everything invalid.
  await page.getByLabel('Guest name').focus();
  await page.keyboard.press('Enter');
  await expect(page.getByLabel('Guest name')).toBeFocused();

  // Make name valid; next invalid should be email.
  await page.getByLabel('Guest name').fill('Ada');
  await page.getByLabel('Guest name').focus();
  await page.keyboard.press('Enter');
  await expect(page.getByLabel('Email address')).toBeFocused();

  // Make email + attendees valid; vegetarian is still missing and should focus a radio.
  await page.getByLabel('Email address').fill('ada@example.com');
  await page.getByLabel('Number of attendees').fill('2');
  await page.getByLabel('Number of attendees').focus();
  await page.keyboard.press('Enter');
  await expect(page.getByLabel('Yes')).toBeFocused();
});
