import React from 'react';
import { NavLink, Route, Routes } from 'react-router-dom';
import DashboardPage from './pages/DashboardPage.jsx';
import TransactionsPage from './pages/TransactionsPage.jsx';
import AddTransactionPage from './pages/AddTransactionPage.jsx';
import TransactionDetailPage from './pages/TransactionDetailPage.jsx';
import NotFoundPage from './pages/NotFoundPage.jsx';
import { BudgetProvider } from './BudgetStore.jsx';

export default function App() {
  return (
    <BudgetProvider>
      <a className="skip-link" href="#main">Skip to content</a>
      <div className="app">
        <header className="header" role="banner">
          <div className="brand">
            <strong>Budget Tracker</strong>
            <span>Track spending with searchable transactions and monthly totals.</span>
          </div>
          <nav className="nav" aria-label="Primary">
            <NavLink to="/" end>
              Dashboard
            </NavLink>
            <NavLink to="/transactions">Transactions</NavLink>
            <NavLink to="/add">Add</NavLink>
          </nav>
        </header>

        <main id="main" tabIndex={-1}>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/transactions" element={<TransactionsPage />} />
            <Route path="/add" element={<AddTransactionPage />} />
            <Route path="/transactions/:id" element={<TransactionDetailPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </main>
      </div>
    </BudgetProvider>
  );
}
