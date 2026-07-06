import type { Product } from '../data/products';

export type CartLine = {
  productId: string;
  quantity: number;
};

export type CartState = {
  lines: CartLine[];
};

export type AddToCartAction = {
  type: 'add';
  productId: string;
  quantity?: number;
};

export type RemoveFromCartAction = {
  type: 'remove';
  productId: string;
};

export type SetQuantityAction = {
  type: 'setQuantity';
  productId: string;
  quantity: number;
};

export type ClearCartAction = { type: 'clear' };

export type CartAction =
  | AddToCartAction
  | RemoveFromCartAction
  | SetQuantityAction
  | ClearCartAction;

export const CART_STORAGE_KEY = 'run-shop.cart.v1';

export function createEmptyCart(): CartState {
  return { lines: [] };
}

export function cartReducer(state: CartState, action: CartAction): CartState {
  switch (action.type) {
    case 'add': {
      const quantity = clampInt(action.quantity ?? 1, 1, 999);
      const existing = state.lines.find((l) => l.productId === action.productId);
      if (!existing) {
        return {
          lines: [...state.lines, { productId: action.productId, quantity }],
        };
      }
      return {
        lines: state.lines.map((l) =>
          l.productId === action.productId
            ? { ...l, quantity: clampInt(l.quantity + quantity, 1, 999) }
            : l,
        ),
      };
    }
    case 'remove': {
      return {
        lines: state.lines.filter((l) => l.productId !== action.productId),
      };
    }
    case 'setQuantity': {
      const quantity = clampInt(action.quantity, 0, 999);
      if (quantity === 0) {
        return {
          lines: state.lines.filter((l) => l.productId !== action.productId),
        };
      }
      const hasLine = state.lines.some((l) => l.productId === action.productId);
      if (!hasLine) return state;
      return {
        lines: state.lines.map((l) =>
          l.productId === action.productId ? { ...l, quantity } : l,
        ),
      };
    }
    case 'clear': {
      return createEmptyCart();
    }
    default: {
      return state;
    }
  }
}

export function getCartItemCount(state: CartState): number {
  return state.lines.reduce((sum, l) => sum + l.quantity, 0);
}

export function getCartTotalCents(state: CartState, products: Product[]): number {
  const priceById = new Map(products.map((p) => [p.id, p.priceCents] as const));
  return state.lines.reduce((sum, l) => {
    const price = priceById.get(l.productId);
    if (price == null) return sum;
    return sum + price * l.quantity;
  }, 0);
}

export function formatMoneyFromCents(amountCents: number): string {
  const dollars = amountCents / 100;
  return dollars.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
  });
}

export function loadCartFromStorage(storage: Pick<Storage, 'getItem'>): CartState {
  try {
    const raw = storage.getItem(CART_STORAGE_KEY);
    if (!raw) return createEmptyCart();
    const parsed = JSON.parse(raw) as unknown;
    const lines = parseLines(parsed);
    return { lines };
  } catch {
    return createEmptyCart();
  }
}

export function saveCartToStorage(
  storage: Pick<Storage, 'setItem'>,
  state: CartState,
): void {
  storage.setItem(CART_STORAGE_KEY, JSON.stringify({ lines: state.lines }));
}

function parseLines(value: unknown): CartLine[] {
  if (!value || typeof value !== 'object') return [];
  const v = value as { lines?: unknown };
  if (!Array.isArray(v.lines)) return [];
  const lines: CartLine[] = [];
  for (const entry of v.lines) {
    if (!entry || typeof entry !== 'object') continue;
    const e = entry as { productId?: unknown; quantity?: unknown };
    if (typeof e.productId !== 'string') continue;
    const q = typeof e.quantity === 'number' ? e.quantity : Number(e.quantity);
    if (!Number.isFinite(q)) continue;
    const quantity = clampInt(q, 1, 999);
    lines.push({ productId: e.productId, quantity });
  }
  // de-dupe by productId, keeping the last
  const byId = new Map<string, CartLine>();
  for (const l of lines) byId.set(l.productId, l);
  return [...byId.values()];
}

function clampInt(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  const v = Math.trunc(value);
  if (v < min) return min;
  if (v > max) return max;
  return v;
}
