import React from 'react';
import { budgetReducer, createInitialState, persistState } from '../domain/state.js';

const BudgetContext = React.createContext(null);

export function BudgetProvider({ children, storage = window.localStorage }) {
  const [state, dispatch] = React.useReducer(budgetReducer, undefined, () => createInitialState(storage));

  React.useEffect(() => {
    persistState(state, storage);
  }, [state, storage]);

  const value = React.useMemo(() => ({ state, dispatch }), [state]);
  return <BudgetContext.Provider value={value}>{children}</BudgetContext.Provider>;
}

export function useBudget() {
  const ctx = React.useContext(BudgetContext);
  if (!ctx) throw new Error('useBudget must be used within <BudgetProvider>');
  return ctx;
}
