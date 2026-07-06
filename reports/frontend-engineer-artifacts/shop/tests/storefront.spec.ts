import { expect, test } from '@playwright/test';

test('storefront routing + cart correctness + back/forward + deep links', async ({ page }) => {
  // Deep link into a product detail page first.
  await page.goto('/product/p2');
  await expect(page.getByRole('heading', { name: 'Chorus Tee' })).toBeVisible();

  const cartSummary = page.getByLabel('Cart summary');
  await expect(cartSummary.getByLabel('Cart items')).toHaveText('0');
  await expect(cartSummary.getByLabel('Cart total')).toHaveText('$0.00');

  await page.getByRole('button', { name: 'Add to cart' }).click();
  await expect(cartSummary.getByLabel('Cart items')).toHaveText('1');
  await expect(cartSummary.getByLabel('Cart total')).toHaveText('$24.99');

  // Navigate to cart and edit quantities.
  await page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: 'Cart' }).click();
  await expect(page.getByRole('heading', { name: 'Your cart' })).toBeVisible();
  await expect(page.getByText('Chorus Tee')).toBeVisible();

  const qtyInput = page.getByLabel('Quantity');
  await qtyInput.fill('2');
  await expect(cartSummary.getByLabel('Cart items')).toHaveText('2');
  await expect(cartSummary.getByLabel('Cart total')).toHaveText('$49.98');

  await page.getByRole('button', { name: 'Remove' }).click();
  await expect(cartSummary.getByLabel('Cart items')).toHaveText('0');
  await expect(cartSummary.getByLabel('Cart total')).toHaveText('$0.00');

  // Navigate to products, then to a different product.
  await page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: 'Products' }).click();
  await expect(page.getByRole('heading', { name: 'Products' })).toBeVisible();

  // Add first product from the list (Arc Mug: $15.99)
  await page.getByRole('link', { name: 'View details' }).first().click();
  await expect(page.getByRole('heading', { name: 'Arc Mug' })).toBeVisible();
  await page.getByRole('button', { name: 'Add to cart' }).click();

  // Assert cart summary correctness after the second add (count + total).
  await expect(cartSummary.getByLabel('Cart items')).toHaveText('1');
  await expect(cartSummary.getByLabel('Cart total')).toHaveText('$15.99');

  // Back to products list and forward to product detail should keep cart state.
  await page.goBack();
  await expect(page.getByRole('heading', { name: 'Products' })).toBeVisible();
  await expect(cartSummary.getByLabel('Cart items')).toHaveText('1');
  await expect(cartSummary.getByLabel('Cart total')).toHaveText('$15.99');

  await page.goForward();
  await expect(page.getByRole('heading', { name: 'Arc Mug' })).toBeVisible();
  await expect(cartSummary.getByLabel('Cart items')).toHaveText('1');
  await expect(cartSummary.getByLabel('Cart total')).toHaveText('$15.99');

  // Deep link to cart URL works without prior in-app navigation.
  await page.goto('/cart');
  await expect(page.getByRole('heading', { name: 'Your cart' })).toBeVisible();
  await expect(cartSummary.getByLabel('Cart items')).toHaveText('1');
  await expect(cartSummary.getByLabel('Cart total')).toHaveText('$15.99');
  await expect(page.getByText('Arc Mug')).toBeVisible();
});

test('cart persists via localStorage and deep link to /cart works from cold start', async ({ page }) => {
  // Seed localStorage before app scripts run.
  await page.addInitScript(() => {
    window.localStorage.setItem(
      'run-shop.cart.v1',
      JSON.stringify({ lines: [{ productId: 'p2', quantity: 2 }] }),
    );
  });

  await page.goto('/cart');
  await expect(page.getByRole('heading', { name: 'Your cart' })).toBeVisible();
  await expect(page.getByText('Chorus Tee')).toBeVisible();

  const cartSummary = page.getByLabel('Cart summary');
  await expect(cartSummary.getByLabel('Cart items')).toHaveText('2');
  await expect(cartSummary.getByLabel('Cart total')).toHaveText('$49.98');
});
