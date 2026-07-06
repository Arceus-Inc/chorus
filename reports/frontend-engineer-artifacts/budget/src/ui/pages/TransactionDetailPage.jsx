import React from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useBudget } from '../BudgetStore.jsx';
import TransactionForm from '../components/TransactionForm.jsx';

export default function TransactionDetailPage() {
  const { id } = useParams();
  const { state, dispatch } = useBudget();
  const navigate = useNavigate();

  const tx = state.transactions.find((t) => t.id === id);

  if (!tx) {
    return (
      <section className="panel" aria-labelledby="missing-title">
        <div className="panel-hd">
          <h1 id="missing-title" style={{ margin: 0 }}>Transaction not found</h1>
        </div>
        <div className="panel-bd stack">
          <p className="help" role="status">We couldn’t find that transaction (it may have been deleted).</p>
          <Link className="btn" to="/transactions">Back to transactions</Link>
        </div>
      </section>
    );
  }

  return (
    <section className="panel" aria-labelledby="detail-title">
      <div className="panel-hd" style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', flexWrap: 'wrap', gap: '.75rem' }}>
        <h1 id="detail-title" style={{ margin: 0 }}>Edit transaction</h1>
        <Link className="btn" to="/transactions">Back</Link>
      </div>
      <div className="panel-bd stack">
        <TransactionForm
          initial={tx}
          submitLabel="Save changes"
          onSubmit={(patch) => {
            dispatch({ type: 'transaction/update', id: tx.id, patch });
            navigate('/transactions');
          }}
        />

        <hr style={{ border: 0, borderTop: '1px solid rgba(42,53,98,.9)', width: '100%' }} />

        <div className="row-actions">
          <button
            type="button"
            className="btn danger"
            onClick={() => {
              const ok = window.confirm('Delete this transaction? This cannot be undone.');
              if (!ok) return;
              dispatch({ type: 'transaction/delete', id: tx.id });
              navigate('/transactions');
            }}
          >
            Delete transaction
          </button>
        </div>
      </div>
    </section>
  );
}
