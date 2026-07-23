import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useBudget } from '../BudgetStore.jsx';
import TransactionForm from '../components/TransactionForm.jsx';

function todayISO() {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

export default function AddTransactionPage() {
  const { dispatch } = useBudget();
  const navigate = useNavigate();

  return (
    <section className="panel" aria-labelledby="add-title">
      <div className="panel-hd">
        <h1 id="add-title" style={{ margin: 0 }}>Add transaction</h1>
      </div>
      <div className="panel-bd">
        <TransactionForm
          initial={{ description: '', amount: '', category: '', date: todayISO() }}
          submitLabel="Add transaction"
          onSubmit={(tx) => {
            dispatch({ type: 'transaction/add', transaction: tx });
            navigate('/transactions');
          }}
        />
      </div>
    </section>
  );
}
