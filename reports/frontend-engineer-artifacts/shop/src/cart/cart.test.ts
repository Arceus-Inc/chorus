import { describe, expect, it } from 'vitest';
import {
  cartReducer,
  createEmptyCart,
  formatMoneyFromCents,
  getCartItemCount,
  getCartTotalCents,
  loadCartFromStorage,
  saveCartToStorage,
} from './cart';
import type { Product } from '../data/products';

const PRODUCTS: Product[] = [
  { id: 'a', name: 'A', description: '', priceCents: 500 },
  { id: 'b', name: 'B', description: '', priceCents: 250 },
];

describe('cart reducer', () => {
  it('adds a new line', () => {
    const s0 = createEmptyCart();
    const s1 = cartReducer(s0, { type: 'add', productId: 'a' });
    expect(s1.lines).toEqual([{ productId: 'a', quantity: 1 }]);
  });

  it('increments quantity on repeated add', () => {
    const s0 = { lines: [{ productId: 'a', quantity: 1 }] };
    const s1 = cartReducer(s0, { type: 'add', productId: 'a', quantity: 2 });
    expect(s1.lines).toEqual([{ productId: 'a', quantity: 3 }]);
  });

  it('removes a line', () => {
    const s0 = { lines: [{ productId: 'a', quantity: 2 }] };
    const s1 = cartReducer(s0, { type: 'remove', productId: 'a' });
    expect(s1.lines).toEqual([]);
  });

  it('sets quantity and removes when set to 0', () => {
    const s0 = { lines: [{ productId: 'a', quantity: 2 }] };
    const s1 = cartReducer(s0, { type: 'setQuantity', productId: 'a', quantity: 5 });
    expect(s1.lines).toEqual([{ productId: 'a', quantity: 5 }]);

    const s2 = cartReducer(s1, { type: 'setQuantity', productId: 'a', quantity: 0 });
    expect(s2.lines).toEqual([]);
  });
});

describe('cart selectors', () => {
  it('computes item count', () => {
    const s = { lines: [{ productId: 'a', quantity: 2 }, { productId: 'b', quantity: 1 }] };
    expect(getCartItemCount(s)).toBe(3);
  });

  it('computes total cents and ignores unknown ids', () => {
    const s = {
      lines: [
        { productId: 'a', quantity: 2 },
        { productId: 'missing', quantity: 10 },
        { productId: 'b', quantity: 1 },
      ],
    };
    expect(getCartTotalCents(s, PRODUCTS)).toBe(500 * 2 + 250 * 1);
  });

  it('formats money', () => {
    expect(formatMoneyFromCents(0)).toMatch(/\$0\.00/);
  });
});

describe('storage', () => {
  it('loads empty on missing/invalid data', () => {
    const empty = loadCartFromStorage({ getItem: () => null });
    expect(empty.lines).toEqual([]);

    const invalid = loadCartFromStorage({ getItem: () => '{not json' });
    expect(invalid.lines).toEqual([]);
  });

  it('saves and loads round trip', () => {
    const store = new Map<string, string>();
    const storage = {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => {
        store.set(k, v);
      },
    };

    saveCartToStorage(storage, { lines: [{ productId: 'a', quantity: 3 }] });
    const loaded = loadCartFromStorage(storage);
    expect(loaded.lines).toEqual([{ productId: 'a', quantity: 3 }]);
  });
});
