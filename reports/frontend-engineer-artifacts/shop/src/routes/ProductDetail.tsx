import { Link, useParams } from 'react-router-dom';
import { getProductById, PRODUCTS } from '../data/products';
import { formatMoneyFromCents, getCartItemCount, getCartTotalCents } from '../cart/cart';
import { useCart } from '../cart/CartProvider';

export function ProductDetail() {
  const { id } = useParams();
  const product = id ? getProductById(id) : undefined;
  const { state, dispatch } = useCart();

  if (!product) {
    return (
      <main aria-labelledby="page-title">
        <h1 id="page-title">Product not found</h1>
        <p>
          <Link to="/">Back to products</Link>
        </p>
      </main>
    );
  }

  const count = getCartItemCount(state);
  const total = getCartTotalCents(state, PRODUCTS);

  return (
    <main aria-labelledby="page-title">
      <h1 id="page-title">{product.name}</h1>
      <p style={{ color: 'var(--muted)' }}>{product.description}</p>
      <p style={{ fontSize: 18, fontWeight: 700 }}>{formatMoneyFromCents(product.priceCents)}</p>

      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <button
          type="button"
          onClick={() => dispatch({ type: 'add', productId: product.id })}
        >
          Add to cart
        </button>
        <Link to="/cart">Go to cart</Link>
      </div>

      <hr style={{ margin: '16px 0', borderColor: 'var(--border)' }} />
      <p style={{ margin: 0 }}>
        Cart now: <strong aria-label="Cart items">{count}</strong> items,{' '}
        <strong aria-label="Cart total">{formatMoneyFromCents(total)}</strong>
      </p>
    </main>
  );
}
