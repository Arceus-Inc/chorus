import { describe, expect, test } from 'vitest';
import {
  breakdownByCategoryForMonth,
  filterTransactions,
  isValidISODate,
  sumSpentForMonth,
  validateTransactionDraft,
} from './transactions.js';

describe('validation', () => {
  test('requires description, positive amount, known category, valid date', () => {
    const v = validateTransactionDraft({
      description: '',
      amount: '-1',
      category: 'NotAReal',
      date: '2025-13-40',
    });
    expect(v.ok).toBe(false);
    expect(v.errors.description).toMatch(/required/i);
    expect(v.errors.amount).toMatch(/positive/i);
    expect(v.errors.category).toMatch(/recognized/i);
    expect(v.errors.date).toMatch(/valid/i);
  });

  test('accepts valid input', () => {
    const v = validateTransactionDraft({
      description: 'Coffee',
      amount: '3.5',
      category: 'Dining',
      date: '2026-06-15',
    });
    expect(v.ok).toBe(true);
    expect(v.errors).toEqual({});
  });

  test('isValidISODate checks actual calendar', () => {
    expect(isValidISODate('2026-02-29')).toBe(false);
    expect(isValidISODate('2024-02-29')).toBe(true);
  });
});

describe('aggregation', () => {
  const txs = [
    { id: 'a', description: 'Rent', amount: 1000, category: 'Rent', date: '2026-06-02' },
    { id: 'b', description: 'Groceries', amount: 50, category: 'Groceries', date: '2026-06-03' },
    { id: 'c', description: 'Dinner', amount: 25, category: 'Dining', date: '2026-05-15' },
    { id: 'd', description: 'More groceries', amount: 10, category: 'Groceries', date: '2026-06-10' },
  ];

  test('sumSpentForMonth sums current month only', () => {
    const now = new Date('2026-06-20T12:00:00.000Z');
    expect(sumSpentForMonth(txs, now)).toBe(1060);
  });

  test('breakdownByCategoryForMonth groups and sorts', () => {
    const now = new Date('2026-06-20T12:00:00.000Z');
    const b = breakdownByCategoryForMonth(txs, now);
    expect(b).toEqual([
      { category: 'Rent', total: 1000 },
      { category: 'Groceries', total: 60 },
    ]);
  });
});

describe('search and filter', () => {
  const txs = [
    { id: 'a', description: 'Coffee', amount: 3.5, category: 'Dining', date: '2026-06-02' },
    { id: 'b', description: 'Bus pass', amount: 25, category: 'Transport', date: '2026-06-03' },
    { id: 'c', description: 'Grocery run', amount: 12, category: 'Groceries', date: '2026-06-04' },
  ];

  test('search matches description or category (case-insensitive)', () => {
    expect(filterTransactions(txs, { query: 'cof' }).map((t) => t.id)).toEqual(['a']);
    expect(filterTransactions(txs, { query: 'transport' }).map((t) => t.id)).toEqual(['b']);
  });

  test('category filter narrows results', () => {
    expect(filterTransactions(txs, { category: 'Groceries' }).map((t) => t.id)).toEqual(['c']);
  });

  test('category filter and search combine', () => {
    expect(filterTransactions(txs, { category: 'Dining', query: 'bus' }).length).toBe(0);
  });
});
