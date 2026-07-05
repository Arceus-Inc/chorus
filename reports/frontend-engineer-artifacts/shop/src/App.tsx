import { Link, NavLink, Route, Routes } from 'react-router-dom';
import { CartProvider, useCart } from './cart/CartProvider';
import { PRODUCTS } from './data/products';
import { formatMoneyFromCents, getCartItemCount, getCartTotalCents } from './cart/cart';
import { ProductList } from './routes/ProductList';
import { ProductDetail } from './routes/ProductDetail';
import { CartView } from './routes/CartView';

export default function App() {
  return (
    <CartProvider>
      <div className="appShell">
        <SiteHeader />
        <div className="content">
          <Routes>
            <Route path="/" element={<ProductList />} />
            <Route path="/product/:id" element={<ProductDetail />} />
            <Route path="/cart" element={<CartView />} />
            <Route
              path="*"
              element={
                <main aria-labelledby="page-title">
                  <h1 id="page-title">Not found</h1>
                  <p>
                    <Link to="/">Back to products</Link>
                  </p>
                </main>
              }
            />
          </Routes>
        </div>
      </div>
    </CartProvider>
  );
}

function SiteHeader() {
  return (
    <header className="siteHeader">
      <div className="siteHeader__inner">
        <nav aria-label="Primary">
          <NavLink to="/" end>
            Products
          </NavLink>
          <NavLink to="/cart">Cart</NavLink>
        </nav>

        <CartSummary />
      </div>
    </header>
  );
}

function CartSummary() {
  const { state } = useCart();
  const count = getCartItemCount(state);
  const total = getCartTotalCents(state, PRODUCTS);

  return (
    <div className="cartSummary" aria-label="Cart summary">
      <span>
        Items: <strong aria-label="Cart items">{count}</strong>
      </span>
      <span>
        Total: <strong aria-label="Cart total">{formatMoneyFromCents(total)}</strong>
      </span>
    </div>
  );
}
