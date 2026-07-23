import test from 'node:test';
import assert from 'node:assert/strict';

import {
  calculateSplit,
  formatMoney,
  validateBill,
  validatePeople,
  validateTipPercent,
} from '../src/logic.js';

test('validateBill: empty is invalid, negative is invalid, normal number is valid', () => {
  assert.equal(validateBill('').ok, false);
  assert.equal(validateBill('  ').ok, false);
  assert.equal(validateBill('-1').ok, false);

  const v = validateBill('42.50');
  assert.equal(v.ok, true);
  assert.equal(v.value, 42.5);
});

test('validatePeople: requires integer >= 1', () => {
  assert.equal(validatePeople('').ok, false);
  assert.equal(validatePeople('0').ok, false);
  assert.equal(validatePeople('-2').ok, false);
  assert.equal(validatePeople('2.5').ok, false);

  const v = validatePeople('3');
  assert.equal(v.ok, true);
  assert.equal(v.value, 3);
});

test('validateTipPercent: empty allowed (null), negative invalid, numeric valid', () => {
  const empty = validateTipPercent('', { allowEmpty: true });
  assert.equal(empty.ok, true);
  assert.equal(empty.value, null);

  assert.equal(validateTipPercent('-5', { allowEmpty: true }).ok, false);

  const v = validateTipPercent('18', { allowEmpty: true });
  assert.equal(v.ok, true);
  assert.equal(v.value, 18);
});

test('calculateSplit: computes rounded tip/total/per-person and formats money', () => {
  const res = calculateSplit({ bill: 42.5, tipPercent: 20, people: 3 });
  assert.equal(res.ok, true);
  assert.equal(res.tip, 8.5);
  assert.equal(res.total, 51);
  assert.equal(res.perPerson, 17);

  assert.equal(formatMoney(res.tip), '$8.50');
  assert.equal(formatMoney(res.total), '$51.00');
  assert.equal(formatMoney(res.perPerson), '$17.00');
});

test('calculateSplit: rejects invalid inputs instead of NaN/Infinity', () => {
  assert.equal(calculateSplit({ bill: -1, tipPercent: 10, people: 2 }).ok, false);
  assert.equal(calculateSplit({ bill: 10, tipPercent: -1, people: 2 }).ok, false);
  assert.equal(calculateSplit({ bill: 10, tipPercent: 10, people: 0 }).ok, false);
});
