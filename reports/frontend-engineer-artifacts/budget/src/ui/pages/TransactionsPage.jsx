import React from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useBudget } from '../BudgetStore.jsx';
import { CATEGORIES } from '../../domain/categories.js';
import {
  filterTransactions,
  formatMoney,
  sortTransactionsNewestFirst,
} from '../../domain/transactions.js';

export default function TransactionsPage() {
  const { state } = useBudget();
  const [params, setParams] = useSearchParams();

  const query = params.get('q') ?? '';
  const category = params.get('cat') ?? '';

  const filtered = React.useMemo(() => {
    return sortTransactionsNewestFirst(
      filterTransactions(state.transactions, { query, category })
    );
  }, [state.transactions, query, category]);

  return (
    <section className="panel" aria-labelledby="tx-title">
      <div className="panel-hd" style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: '.75rem', flexWrap: 'wrap' }}>
        <h1 id="tx-title" style={{ margin: 0 }}>Transactions</h1>
        <Link className="btn primary" to="/add">Add</Link>
      </div>

      <div className="panel-bd stack">
        <form className="controls" aria-label="Search and filter">
          <div className="field">
            <label htmlFor="search">Search</label>
            <input
              id="search"
              name="search"
              type="search"
              value={query}
              onChange={(e) => {
                const next = new URLSearchParams(params);
                const v = e.target.value;
                if (v) next.set('q', v);
                else next.delete('q');
                setParams(next, { replace: true });
              }}
              placeholder="Search description or category"
            />
          </div>

          <div className="field">
            <label htmlFor="category">Category</label>
            <select
              id="category"
              name="category"
              value={category}
              onChange={(e) => {
                const next = new URLSearchParams(params);
                const v = e.target.value;
                if (v) next.set('cat', v);
                else next.delete('cat');
                setParams(next, { replace: true });
              }}
            >
              <option value="">All categories</option>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>

          <div className="row-actions">
            <button
              type="button"
              className="btn"
              onClick={() => setParams(new URLSearchParams(), { replace: true })}
            >
              Clear
            </button>
          </div>
        </form>

        {filtered.length === 0 ? (
          <p className="help" role="status">No transactions match your search/filter.</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="table" aria-label="Transactions table">
              <thead>
                <tr>
                  <th scope="col">Date</th>
                  <th scope="col">Description</th>
                  <th scope="col">Category</th>
                  <th scope="col" className="no-wrap">Amount</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((t) => (
                  <tr key={t.id}>
                    <td className="no-wrap">{t.date}</td>
                    <td>{t.description}</td>
                    <td><span className="badge">{t.category}</span></td>
                    <td className="no-wrap">{formatMoney(t.amount)}</td>
                    <td>
                      <div className="row-actions">
                        <Link className="btn" to={`/transactions/${t.id}`}>View / edit</Link>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
