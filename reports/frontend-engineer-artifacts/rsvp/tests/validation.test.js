import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  MAX_ATTENDEES,
  validateName,
  validateEmail,
  validateAttendees,
  validateVegetarian,
  validateAll,
  normalizeSubmission,
} from '../src/validation.js';

test('validateName requires at least 2 non-whitespace characters', () => {
  assert.equal(validateName(''), 'Please enter your name.');
  assert.equal(validateName('  '), 'Please enter your name.');
  assert.equal(validateName('A'), 'Name must be at least 2 characters.');
  assert.equal(validateName('  Al '), null);
});

test('validateEmail requires an @ and a plausible domain', () => {
  assert.equal(validateEmail(''), 'Please enter your email address.');
  assert.equal(validateEmail('not-an-email'), 'Please enter a valid email address.');
  assert.equal(validateEmail('a@b'), 'Please enter a valid email address.');
  assert.equal(validateEmail(' a@example.com '), null);
});

test('validateAttendees requires a whole number between 1 and MAX_ATTENDEES', () => {
  assert.equal(validateAttendees(''), 'Please enter how many people are attending.');
  assert.equal(validateAttendees('2.5'), 'Attendee count must be a whole number.');
  assert.equal(
    validateAttendees(String(MAX_ATTENDEES + 1)),
    `Attendee count must be between 1 and ${MAX_ATTENDEES}.`
  );
  assert.equal(validateAttendees('1'), null);
  assert.equal(validateAttendees(String(MAX_ATTENDEES)), null);
});

test('validateVegetarian requires a yes/no choice', () => {
  assert.equal(validateVegetarian(''), 'Please choose whether you need a vegetarian meal.');
  assert.equal(validateVegetarian('maybe'), 'Please choose whether you need a vegetarian meal.');
  assert.equal(validateVegetarian('yes'), null);
  assert.equal(validateVegetarian('no'), null);
});

test('validateAll reports field-specific errors and isValid when no errors', () => {
  const bad = validateAll({ name: '', email: 'x', attendees: '0', vegetarian: '' });
  assert.equal(bad.isValid, false);
  assert.equal(typeof bad.errors.name, 'string');
  assert.equal(typeof bad.errors.email, 'string');
  assert.equal(typeof bad.errors.attendees, 'string');
  assert.equal(typeof bad.errors.vegetarian, 'string');

  const good = validateAll({ name: 'Ada', email: 'ada@example.com', attendees: '2', vegetarian: 'no' });
  assert.deepEqual(good.errors, { name: null, email: null, attendees: null, vegetarian: null });
  assert.equal(good.isValid, true);
});

test('normalizeSubmission trims strings and converts attendees/vegetarian types', () => {
  const norm = normalizeSubmission({
    name: '  Ada Lovelace ',
    email: ' ada@example.com ',
    attendees: '3',
    vegetarian: 'yes',
  });

  assert.deepEqual(norm, {
    name: 'Ada Lovelace',
    email: 'ada@example.com',
    attendees: 3,
    vegetarian: true,
  });
});
