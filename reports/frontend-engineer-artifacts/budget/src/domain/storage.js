const STORAGE_KEY = 'budgetTracker.transactions.v1';

export function loadTransactions(storage = window.localStorage) {
  const raw = storage.getItem(STORAGE_KEY);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    // minimal shape validation
    return parsed
      .filter((t) => t && typeof t.id === 'string')
      .map((t) => ({
        id: String(t.id),
        description: String(t.description ?? ''),
        amount: Number(t.amount ?? 0),
        category: String(t.category ?? ''),
        date: String(t.date ?? ''),
      }));
  } catch {
    return [];
  }
}

export function saveTransactions(transactions, storage = window.localStorage) {
  storage.setItem(STORAGE_KEY, JSON.stringify(transactions));
}

export function clearTransactions(storage = window.localStorage) {
  storage.removeItem(STORAGE_KEY);
}
