/**
 * Pure calculation + parsing helpers for the tip splitter.
 */

export function clampNumber(n, { min = -Infinity, max = Infinity } = {}) {
  if (!Number.isFinite(n)) return null;
  if (n < min) return min;
  if (n > max) return max;
  return n;
}

/**
 * Parse a numeric input from a string or number.
 * Returns: { value: number|null, kind: 'empty'|'invalid'|'ok' }
 */
export function parseNumberLike(value) {
  if (value === null || value === undefined) return { value: null, kind: 'empty' };
  const s = String(value).trim();
  if (s === '') return { value: null, kind: 'empty' };
  const n = Number(s);
  if (!Number.isFinite(n)) return { value: null, kind: 'invalid' };
  return { value: n, kind: 'ok' };
}

export function formatUSD(amount) {
  const safe = Number.isFinite(amount) && amount > 0 ? amount : 0;
  return `$${safe.toFixed(2)}`;
}

export function canCompute({ bill, people, tipPercent }) {
  return bill > 0 && people >= 1 && tipPercent >= 0;
}

export function computeSplit({ bill, people, tipPercent }) {
  if (!canCompute({ bill, people, tipPercent })) {
    return { tip: 0, total: 0, perPerson: 0 };
  }

  const tip = bill * (tipPercent / 100);
  const total = bill + tip;
  const perPerson = total / people;

  // Extra guardrails: never leak NaN/Infinity/negatives.
  const safe = (n) => (Number.isFinite(n) && n >= 0 ? n : 0);
  return {
    tip: safe(tip),
    total: safe(total),
    perPerson: safe(perPerson),
  };
}

export function sanitizeInputs({ billInput, peopleInput, tipPercentInput }) {
  const billParsed = parseNumberLike(billInput);
  const peopleParsed = parseNumberLike(peopleInput);
  const tipParsed = parseNumberLike(tipPercentInput);

  const bill =
    billParsed.kind === 'ok' ? clampNumber(billParsed.value, { min: 0 }) : null;

  // Keep people null when empty/invalid so UI can show 0.00 but allow correction.
  const people =
    peopleParsed.kind === 'ok'
      ? clampNumber(Math.floor(peopleParsed.value), { min: 1 })
      : null;

  const tipPercent =
    tipParsed.kind === 'ok' ? clampNumber(tipParsed.value, { min: 0 }) : null;

  return {
    bill,
    people,
    tipPercent,
    meta: {
      billKind: billParsed.kind,
      peopleKind: peopleParsed.kind,
      tipKind: tipParsed.kind,
    },
  };
}
