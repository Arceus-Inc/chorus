import React from 'react';
import { Link } from 'react-router-dom';
import { useBudget } from '../BudgetStore.jsx';
import {
  breakdownByCategoryForMonth,
  formatMoney,
  sumSpentForMonth,
} from '../../domain/transactions.js';
import CategoryBreakdown from '../components/CategoryBreakdown.jsx';

export default function DashboardPage() {
  const { state } = useBudget();
  const total = sumSpentForMonth(state.transactions);
  const breakdown = breakdownByCategoryForMonth(state.transactions);

  return (
    <div className="grid cols-2">
      <section className="panel" aria-labelledby="dash-title">
        <div className="panel-hd">
          <h1 id="dash-title" style={{ margin: 0 }}>Dashboard</h1>
        </div>
        <div className="panel-bd stack">
          <div className="kpis">
            <div className="kpi" role="region" aria-label="Total spent this month">
              <div className="label">Total spent (current month)</div>
              <div className="value">{formatMoney(total)}</div>
            </div>
            <div className="kpi" role="region" aria-label="Transaction count">
              <div className="label">Transactions stored</div>
              <div className="value">{state.transactions.length}</div>
            </div>
          </div>
          <div className="row-actions">
            <Link className="btn primary" to="/add">Add a transaction</Link>
            <Link className="btn" to="/transactions">View transactions</Link>
          </div>
        </div>
      </section>

      <section className="panel" aria-labelledby="breakdown-title">
        <div className="panel-hd">
          <h2 id="breakdown-title" style={{ margin: 0, fontSize: '1.1rem' }}>Spending by category</h2>
        </div>
        <div className="panel-bd">
          <CategoryBreakdown items={breakdown} />
        </div>
      </section>
    </div>
  );
}
