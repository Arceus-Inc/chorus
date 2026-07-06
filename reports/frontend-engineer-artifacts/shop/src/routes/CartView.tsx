import { Link } from 'react-router-dom';
import { PRODUCTS } from '../data/products';
import {
  formatMoneyFromCents,
  getCartItemCount,
  getCartTotalCents,
  type CartLine,
} from '../cart/cart';
import { useCart } from '../cart/CartProvider';

function getProductName(productId: string): string {
  return PRODUCTS.find((p) => p.id === productId)?.name ?? productId;
}

function getProductPriceCents(productId: string): number | undefined {
  return PRODUCTS.find((p) => p.id === productId)?.priceCents;
}

export function CartView() {
  const { state, dispatch } = useCart();

  const count = getCartItemCount(state);
  const total = getCartTotalCents(state, PRODUCTS);

  return (
    <main aria-labelledby="page-title">
      <h1 id="page-title">Your cart</h1>

      {state.lines.length === 0 ? (
        <p>
          Your cart is empty. <Link to="/">Browse products</Link>.
        </p>
      ) : (
        <>
          <ul style={{ listStyle: 'none', padding: 0, margin: '0 0 12px', display: 'grid', gap: 12 }}>
            {state.lines.map((line) => (
              <CartLineItem key={line.productId} line={line} />
            ))}
          </ul>

          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              padding: 12,
              border: '1px solid var(--border)',
              borderRadius: 8,
              background: 'var(--panel)',
            }}
          >
            <div>
              <div>
                Items: <strong aria-label="Cart items">{count}</strong>
              </div>
              <div>
                Total: <strong aria-label="Cart total">{formatMoneyFromCents(total)}</strong>
              </div>
            </div>
            <button type="button" onClick={() => dispatch({ type: 'clear' })}>
              Clear cart
            </button>
          </div>
        </>
      )}
    </main>
  );
}

function CartLineItem({ line }: { line: CartLine }) {
  const { dispatch } = useCart();
  const name = getProductName(line.productId);
  const priceCents = getProductPriceCents(line.productId);
  const lineTotal = (priceCents ?? 0) * line.quantity;
  const inputId = `qty-${line.productId}`;

  return (
    <li
      style={{
        border: '1px solid var(--border)',
        borderRadius: 8,
        padding: 12,
        background: 'var(--panel)',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
        <div>
          <div style={{ fontWeight: 700 }}>{name}</div>
          <div style={{ color: 'var(--muted)' }}>{formatMoneyFromCents(priceCents ?? 0)} each</div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontWeight: 700 }}>{formatMoneyFromCents(lineTotal)}</div>
          <button
            type="button"
            onClick={() => dispatch({ type: 'remove', productId: line.productId })}
          >
            Remove
          </button>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10 }}>
        <label htmlFor={inputId}>Quantity</label>
        <input
          id={inputId}
          type="number"
          inputMode="numeric"
          min={0}
          max={999}
          value={line.quantity}
          onChange={(e) =>
            dispatch({
              type: 'setQuantity',
              productId: line.productId,
              quantity: Number(e.currentTarget.value),
            })
          }
          style={{ width: 100 }}
        />
      </div>
    </li>
  );
}
