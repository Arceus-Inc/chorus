import test from 'node:test';
import assert from 'node:assert/strict';

import {
  computeSplit,
  formatUSD,
  parseNumberLike,
  sanitizeInputs,
  canCompute,
} from '../src/calc.js';

test('parseNumberLike: empty vs invalid vs ok', () => {
  assert.deepEqual(parseNumberLike(''), { value: null, kind: 'empty' });
  assert.deepEqual(parseNumberLike('   '), { value: null, kind: 'empty' });
  assert.deepEqual(parseNumberLike(null), { value: null, kind: 'empty' });
  assert.deepEqual(parseNumberLike('nope'), { value: null, kind: 'invalid' });
  assert.deepEqual(parseNumberLike('12.5'), { value: 12.5, kind: 'ok' });
});

test('sanitizeInputs clamps negatives and floors people', () => {
  const r = sanitizeInputs({ billInput: '-10', peopleInput: '2.9', tipPercentInput: '-5' });
  assert.equal(r.bill, 0);
  assert.equal(r.people, 2);
  assert.equal(r.tipPercent, 0);
});

test('computeSplit: returns zeros when cannot compute', () => {
  assert.deepEqual(computeSplit({ bill: 0, people: 1, tipPercent: 10 }), {
    tip: 0,
    total: 0,
    perPerson: 0,
  });
  assert.deepEqual(computeSplit({ bill: 10, people: 0, tipPercent: 10 }), {
    tip: 0,
    total: 0,
    perPerson: 0,
  });
});

test('computeSplit: valid calculation', () => {
  const { tip, total, perPerson } = computeSplit({ bill: 100, people: 4, tipPercent: 15 });
  assert.equal(tip, 15);
  assert.equal(total, 115);
  assert.equal(perPerson, 28.75);
});

test('canCompute: requires bill>0, people>=1, tip>=0', () => {
  assert.equal(canCompute({ bill: 0, people: 1, tipPercent: 0 }), false);
  assert.equal(canCompute({ bill: 1, people: 1, tipPercent: 0 }), true);
  assert.equal(canCompute({ bill: 1, people: 0, tipPercent: 0 }), false);
  assert.equal(canCompute({ bill: 1, people: 1, tipPercent: -1 }), false);
});

test('formatUSD: never returns negative, NaN, or Infinity; always two decimals', () => {
  assert.equal(formatUSD(1), '$1.00');
  assert.equal(formatUSD(1.2), '$1.20');
  assert.equal(formatUSD(0), '$0.00');
  assert.equal(formatUSD(-5), '$0.00');
  assert.equal(formatUSD(Number.NaN), '$0.00');
  assert.equal(formatUSD(Number.POSITIVE_INFINITY), '$0.00');
});
