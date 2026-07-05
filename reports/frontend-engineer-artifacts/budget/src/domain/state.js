import { loadTransactions, saveTransactions } from './storage.js';
import { makeId } from './ids.js';

export function createInitialState(storage) {
  const transactions = typeof window === 'undefined' ? [] : loadTransactions(storage);
  return { transactions };
}

export function budgetReducer(state, action) {
  switch (action.type) {
    case 'transaction/add': {
      const tx = { ...action.transaction };
      if (!tx.id) tx.id = makeId();
      return { ...state, transactions: [...state.transactions, tx] };
    }
    case 'transaction/update': {
      const { id, patch } = action;
      return {
        ...state,
        transactions: state.transactions.map((t) => (t.id === id ? { ...t, ...patch, id } : t)),
      };
    }
    case 'transaction/delete': {
      return { ...state, transactions: state.transactions.filter((t) => t.id !== action.id) };
    }
    case 'transactions/replace': {
      return { ...state, transactions: [...action.transactions] };
    }
    default:
      return state;
  }
}

export function persistState(state, storage) {
  if (typeof window === 'undefined') return;
  saveTransactions(state.transactions, storage);
}
