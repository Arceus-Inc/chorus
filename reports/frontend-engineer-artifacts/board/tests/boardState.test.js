import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  addCard,
  createEmptyState,
  decodeState,
  encodeState,
  moveCard,
  removeCard,
  storageKey,
} from '../src/boardState.js';

test('addCard adds a trimmed title into the To do lane', () => {
  const idFactory = () => 'c1';
  const next = addCard(createEmptyState(), '  Write tests  ', idFactory);
  assert.equal(next.cards.length, 1);
  assert.deepEqual(next.cards[0], { id: 'c1', title: 'Write tests', lane: 'todo' });
});

test('addCard throws on empty/whitespace title', () => {
  assert.throws(() => addCard(createEmptyState(), '   ', () => 'x'), /Title is required/);
});

test('moveCard moves only to adjacent lanes forward/backward', () => {
  const state = {
    cards: [
      { id: 'a', title: 'A', lane: 'todo' },
      { id: 'b', title: 'B', lane: 'inprogress' },
      { id: 'c', title: 'C', lane: 'done' },
    ],
  };

  const s1 = moveCard(state, 'a', 'forward');
  assert.equal(s1.cards.find((c) => c.id === 'a')?.lane, 'inprogress');

  const s2 = moveCard(state, 'b', 'backward');
  assert.equal(s2.cards.find((c) => c.id === 'b')?.lane, 'todo');

  // Cannot move past ends.
  assert.equal(moveCard(state, 'a', 'backward'), state);
  assert.equal(moveCard(state, 'c', 'forward'), state);
});

test('moveCard is a no-op for unknown card id', () => {
  const state = { cards: [{ id: 'a', title: 'A', lane: 'todo' }] };
  assert.equal(moveCard(state, 'nope', 'forward'), state);
});

test('removeCard removes a card by id and is a no-op if id not found', () => {
  const state = {
    cards: [
      { id: 'a', title: 'A', lane: 'todo' },
      { id: 'b', title: 'B', lane: 'done' },
    ],
  };

  const s1 = removeCard(state, 'a');
  assert.deepEqual(
    s1.cards.map((c) => c.id),
    ['b'],
  );

  assert.equal(removeCard(state, 'nope'), state);
});

test('encodeState/decodeState round-trip', () => {
  const state = {
    cards: [
      { id: 'a', title: 'A', lane: 'todo' },
      { id: 'b', title: 'B', lane: 'inprogress' },
      { id: 'c', title: 'C', lane: 'done' },
    ],
  };

  const raw = encodeState(state);
  const decoded = decodeState(raw);
  assert.deepEqual(decoded, state);
});

test('decodeState falls back to empty on corrupted or wrong-shape input', () => {
  assert.deepEqual(decodeState(''), createEmptyState());
  assert.deepEqual(decodeState('not json'), createEmptyState());
  assert.deepEqual(decodeState('{"v":2,"cards":[]}'), createEmptyState());
  assert.deepEqual(decodeState('{"v":1,"cards":[{"id":1,"title":true,"lane":"todo"}]}'), createEmptyState());
});

test('persistence helpers use the expected storage key', () => {
  assert.equal(typeof storageKey, 'string');
  assert.match(storageKey, /run-board/);
});
