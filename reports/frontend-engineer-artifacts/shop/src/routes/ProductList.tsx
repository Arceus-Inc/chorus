import { Link } from 'react-router-dom';
import { PRODUCTS } from '../data/products';
import { formatMoneyFromCents } from '../cart/cart';

export function ProductList() {
  return (
    <main aria-labelledby="page-title">
      <h1 id="page-title">Products</h1>
      <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'grid', gap: 12 }}>
        {PRODUCTS.map((p) => (
          <li
            key={p.id}
            style={{
              border: '1px solid var(--border)',
              borderRadius: 8,
              padding: 12,
              background: 'var(--panel)',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
              <div>
                <h2 style={{ margin: '0 0 4px' }}>{p.name}</h2>
                <p style={{ margin: 0, color: 'var(--muted)' }}>{p.description}</p>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontWeight: 700 }}>{formatMoneyFromCents(p.priceCents)}</div>
                <Link to={`/product/${p.id}`}>View details</Link>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </main>
  );
}
