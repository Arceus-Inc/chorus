import React, { createContext, useContext, useEffect, useMemo, useReducer } from 'react';
import {
  cartReducer,
  createEmptyCart,
  loadCartFromStorage,
  saveCartToStorage,
  type CartAction,
  type CartState,
} from './cart';

type CartContextValue = {
  state: CartState;
  dispatch: React.Dispatch<CartAction>;
};

const CartContext = createContext<CartContextValue | null>(null);

export function CartProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(cartReducer, undefined, () => {
    if (typeof window === 'undefined') return createEmptyCart();
    return loadCartFromStorage(window.localStorage);
  });

  useEffect(() => {
    saveCartToStorage(window.localStorage, state);
  }, [state]);

  const value = useMemo(() => ({ state, dispatch }), [state]);

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
}

export function useCart(): CartContextValue {
  const ctx = useContext(CartContext);
  if (!ctx) throw new Error('useCart must be used within CartProvider');
  return ctx;
}
