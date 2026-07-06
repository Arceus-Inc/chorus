# run-shop storefront SPA — summary

## Stack choice + rationale

**Chosen stack:** React + TypeScript + Vite, with **React Router** for client-side routing; Vitest for unit tests; Playwright for end-to-end.

**Why this stack fits:** the goal requires a real three-view SPA with stable routes (`/`, `/product/:id`, `/cart`), browser back/forward history, and **persistent shared cart state** that must survive navigation. A component framework plus a router is the smallest, most maintainable way to deliver this without hand-rolling routing/state subscriptions. Vite gives a fast, verifiable build and a preview server that Playwright can drive.

Trade-off: this is heavier than a single HTML file, but the requirements (routing, shared state across views, deep links, back/forward) cross the threshold where framework + router reduces risk and complexity.

## What was built

- **Product list view (`/`)**
  - Renders all products.
  - Each product has a stable link to its detail route (`/product/:id`).
- **Product detail view (`/product/:id`)**
  - Shows name/description/price.
  - Includes an **“Add to cart”** button that updates cart state immediately.
- **Cart view (`/cart`)**
  - Lists line items.
  - Per-line quantity input (set to 0 removes) and a Remove button.
  - Clear cart button.
- **Persistent cart summary (always visible)**
  - Sticky header shows **item count** and **total price**.
  - Updates immediately when adding, changing quantity, removing, or clearing.

## State + persistence wiring

- Cart state is a pure reducer (`src/cart/cart.ts`) with selectors for **count** and **total**.
- A `CartProvider` wraps the app, storing cart state in React context.
- Cart is loaded from `localStorage` on first render and saved back on every cart state change, so navigation/back-forward does not reset the cart.

## Unit tests (npm test)

- Vitest unit tests cover the pure cart module:
  - `add` (new line and increment existing)
  - `remove`
  - `setQuantity` (including removal at 0)
  - selectors: `getCartItemCount`, `getCartTotalCents` (including unknown product IDs)
  - storage load/save round-trip and invalid/missing storage cases

Result: **9 unit tests passed**.

## End-to-end test (Playwright)

- `tests/storefront.spec.ts` drives the real app via the preview build:
  - deep link to `/product/p2`
  - add to cart and assert header cart summary count/total
  - navigate to `/cart`, change quantity, remove item and assert count/total throughout
  - navigate to products list, open another product, add to cart
  - browser **back/forward** and assert the view matches history and cart state remains correct
  - direct navigation to `/cart` and assert correct rendering without prior in-app navigation

Result: **1 e2e test passed**.

## Accessibility notes

- Semantic landmarks (`<header>`, `<nav aria-label="Primary">`, `<main>`), headings per view.
- All controls have accessible names (buttons, links, quantity input uses a `<label>`).
- Visible focus ring via `:focus-visible` and strong contrast (dark background, light text, high-contrast focus outline).

## Known gaps / trade-offs

- Product data is static in-module (no network loading states). The cart module and UI are structured so introducing async fetch later would be straightforward.
