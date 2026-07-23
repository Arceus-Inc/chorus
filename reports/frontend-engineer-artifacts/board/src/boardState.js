const LANES = /** @type {const} */ (['todo', 'inprogress', 'done']);

export const laneLabels = /** @type {const} */ ({
  todo: 'To do',
  inprogress: 'In progress',
  done: 'Done',
});

export const storageKey = 'run-board:v1';

/**
 * @typedef {typeof LANES[number]} Lane
 * @typedef {{ id: string, title: string, lane: Lane }} Card
 * @typedef {{ cards: Card[] }} BoardState
 */

export function createEmptyState() {
  /** @type {BoardState} */
  return { cards: [] };
}

export function laneIndex(lane) {
  return LANES.indexOf(lane);
}

export function canMove(cardLane, direction) {
  const idx = laneIndex(cardLane);
  if (idx === -1) return false;
  const next = direction === 'forward' ? idx + 1 : idx - 1;
  return next >= 0 && next < LANES.length;
}

function defaultIdFactory() {
  // Prefer crypto.randomUUID in browsers; fall back to time+random for tests/older envs.
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  return `c_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

export function addCard(state, title, idFactory = defaultIdFactory) {
  const trimmed = String(title ?? '').trim();
  if (!trimmed) throw new Error('Title is required');
  /** @type {Card} */
  const card = { id: idFactory(), title: trimmed, lane: 'todo' };
  return { cards: [card, ...state.cards] };
}

export function moveCard(state, cardId, direction) {
  const idx = state.cards.findIndex((c) => c.id === cardId);
  if (idx === -1) return state;
  const card = state.cards[idx];
  if (!canMove(card.lane, direction)) return state;

  const newLane = /** @type {Lane} */ (
    LANES[laneIndex(card.lane) + (direction === 'forward' ? 1 : -1)]
  );

  const nextCards = state.cards.slice();
  nextCards[idx] = { ...card, lane: newLane };
  return { cards: nextCards };
}

export function removeCard(state, cardId) {
  const nextCards = state.cards.filter((c) => c.id !== cardId);
  if (nextCards.length === state.cards.length) return state;
  return { cards: nextCards };
}

export function encodeState(state) {
  return JSON.stringify({ v: 1, cards: state.cards });
}

export function decodeState(raw) {
  if (typeof raw !== 'string' || raw.trim() === '') return createEmptyState();
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return createEmptyState();
    if (parsed.v !== 1 || !Array.isArray(parsed.cards)) return createEmptyState();

    /** @type {Card[]} */
    const cards = [];
    for (const c of parsed.cards) {
      if (!c || typeof c !== 'object') continue;
      const id = c.id;
      const title = c.title;
      const lane = c.lane;
      if (typeof id !== 'string' || typeof title !== 'string') continue;
      if (!LANES.includes(lane)) continue;
      cards.push({ id, title, lane });
    }
    return { cards };
  } catch {
    return createEmptyState();
  }
}

export function loadFromStorage(storage) {
  const raw = storage.getItem(storageKey);
  return decodeState(raw);
}

export function saveToStorage(storage, state) {
  storage.setItem(storageKey, encodeState(state));
}
