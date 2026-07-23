import { CATEGORIES } from './categories.js';

export function normalizeText(s) {
  return String(s ?? '').trim();
}

export function parseAmount(value) {
  if (value === '' || value == null) return NaN;
  const n = Number(value);
  return Number.isFinite(n) ? n : NaN;
}

export function isValidISODate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value))) return false;
  const d = new Date(`${value}T00:00:00.000Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === value;
}

export function validateTransactionDraft(draft) {
  const errors = {};

  const description = normalizeText(draft.description);
  if (!description) errors.description = 'Description is required.';

  const amount = parseAmount(draft.amount);
  if (!Number.isFinite(amount) || amount <= 0) errors.amount = 'Amount must be a positive number.';

  const category = normalizeText(draft.category);
  if (!category) errors.category = 'Category is required.';
  else if (!CATEGORIES.includes(category)) errors.category = 'Category is not recognized.';

  const date = normalizeText(draft.date);
  if (!date) errors.date = 'Date is required.';
  else if (!isValidISODate(date)) errors.date = 'Date must be a valid YYYY-MM-DD.';

  return { ok: Object.keys(errors).length === 0, errors };
}

export function isSameMonth(isoDate, year, monthIndex) {
  const d = new Date(`${isoDate}T00:00:00.000Z`);
  return d.getUTCFullYear() === year && d.getUTCMonth() === monthIndex;
}

export function getCurrentMonthYear(now = new Date()) {
  return { year: now.getFullYear(), monthIndex: now.getMonth() };
}

export function sumSpentForMonth(transactions, now = new Date()) {
  const { year, monthIndex } = getCurrentMonthYear(now);
  return transactions
    .filter((t) => isSameMonth(t.date, year, monthIndex))
    .reduce((acc, t) => acc + t.amount, 0);
}

export function breakdownByCategoryForMonth(transactions, now = new Date()) {
  const { year, monthIndex } = getCurrentMonthYear(now);
  const map = new Map();
  for (const t of transactions) {
    if (!isSameMonth(t.date, year, monthIndex)) continue;
    map.set(t.category, (map.get(t.category) ?? 0) + t.amount);
  }
  return Array.from(map.entries())
    .map(([category, total]) => ({ category, total }))
    .sort((a, b) => b.total - a.total);
}

export function matchesQuery(transaction, query) {
  const q = normalizeText(query).toLowerCase();
  if (!q) return true;
  return (
    transaction.description.toLowerCase().includes(q) ||
    transaction.category.toLowerCase().includes(q)
  );
}

export function filterTransactions(transactions, { query = '', category = '' } = {}) {
  const cat = normalizeText(category);
  return transactions.filter((t) => {
    if (cat && t.category !== cat) return false;
    return matchesQuery(t, query);
  });
}

export function formatMoney(amount) {
  const n = Number(amount);
  if (!Number.isFinite(n)) return '$0.00';
  return n.toLocaleString(undefined, { style: 'currency', currency: 'USD' });
}

export function sortTransactionsNewestFirst(transactions) {
  return [...transactions].sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
}
