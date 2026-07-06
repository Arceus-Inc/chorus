import React from 'react';
import { formatMoney } from '../../domain/transactions.js';

export default function CategoryBreakdown({ items }) {
  if (!items.length) {
    return <p className="help">No spending recorded for the current month yet.</p>;
  }

  return (
    <div className="stack" role="list" aria-label="Spending by category">
      {items.map((i) => (
        <div
          key={i.category}
          role="listitem"
          className="kpi"
          style={{ display: 'flex', justifyContent: 'space-between', gap: '.75rem' }}
        >
          <div>
            <div className="label">{i.category}</div>
          </div>
          <div className="value no-wrap" aria-label={`${i.category} total`}>{formatMoney(i.total)}</div>
        </div>
      ))}
    </div>
  );
}
