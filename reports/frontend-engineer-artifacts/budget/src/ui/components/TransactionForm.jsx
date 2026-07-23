import React from 'react';
import { CATEGORIES } from '../../domain/categories.js';
import { validateTransactionDraft } from '../../domain/transactions.js';

function fieldDescribedBy(errorId, helpId, hasError) {
  const ids = [];
  if (hasError) ids.push(errorId);
  ids.push(helpId);
  return ids.join(' ');
}

export default function TransactionForm({
  initial,
  submitLabel,
  onSubmit,
  busy = false,
}) {
  const [draft, setDraft] = React.useState(() => ({
    description: initial.description ?? '',
    amount: initial.amount ?? '',
    category: initial.category ?? '',
    date: initial.date ?? '',
  }));

  const validation = React.useMemo(() => validateTransactionDraft(draft), [draft]);
  const canSubmit = validation.ok && !busy;

  const [submitted, setSubmitted] = React.useState(false);
  const showError = (name) => submitted && Boolean(validation.errors[name]);

  function submit(e) {
    e.preventDefault();
    setSubmitted(true);
    const v = validateTransactionDraft(draft);
    if (!v.ok) return;
    onSubmit({
      description: String(draft.description).trim(),
      amount: Number(draft.amount),
      category: draft.category,
      date: draft.date,
    });
  }

  return (
    <form className="stack" onSubmit={submit} noValidate>
      <div className="field">
        <label htmlFor="description">Description</label>
        <input
          id="description"
          name="description"
          type="text"
          value={draft.description}
          onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
          aria-invalid={showError('description') ? 'true' : 'false'}
          aria-describedby={fieldDescribedBy(
            'description-error',
            'description-help',
            showError('description')
          )}
          autoComplete="off"
          required
        />
        <div id="description-help" className="help">What did you spend money on?</div>
        {showError('description') && (
          <div id="description-error" className="error" role="alert">
            {validation.errors.description}
          </div>
        )}
      </div>

      <div className="field">
        <label htmlFor="amount">Amount</label>
        <input
          id="amount"
          name="amount"
          type="number"
          inputMode="decimal"
          min="0"
          step="0.01"
          value={draft.amount}
          onChange={(e) => setDraft((d) => ({ ...d, amount: e.target.value }))}
          aria-invalid={showError('amount') ? 'true' : 'false'}
          aria-describedby={fieldDescribedBy('amount-error', 'amount-help', showError('amount'))}
          required
        />
        <div id="amount-help" className="help">Enter a positive number (e.g., 12.34).</div>
        {showError('amount') && (
          <div id="amount-error" className="error" role="alert">
            {validation.errors.amount}
          </div>
        )}
      </div>

      <div className="field">
        <label htmlFor="category">Category</label>
        <select
          id="category"
          name="category"
          value={draft.category}
          onChange={(e) => setDraft((d) => ({ ...d, category: e.target.value }))}
          aria-invalid={showError('category') ? 'true' : 'false'}
          aria-describedby={fieldDescribedBy(
            'category-error',
            'category-help',
            showError('category')
          )}
          required
        >
          <option value="">Choose a category</option>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <div id="category-help" className="help">Used for your dashboard breakdown.</div>
        {showError('category') && (
          <div id="category-error" className="error" role="alert">
            {validation.errors.category}
          </div>
        )}
      </div>

      <div className="field">
        <label htmlFor="date">Date</label>
        <input
          id="date"
          name="date"
          type="date"
          value={draft.date}
          onChange={(e) => setDraft((d) => ({ ...d, date: e.target.value }))}
          aria-invalid={showError('date') ? 'true' : 'false'}
          aria-describedby={fieldDescribedBy('date-error', 'date-help', showError('date'))}
          required
        />
        <div id="date-help" className="help">Used for current-month totals.</div>
        {showError('date') && (
          <div id="date-error" className="error" role="alert">
            {validation.errors.date}
          </div>
        )}
      </div>

      <div className="row-actions">
        <button className="btn primary" type="submit" disabled={!canSubmit}>
          {busy ? 'Saving…' : submitLabel}
        </button>
      </div>
    </form>
  );
}
