const CURRENCY_FORMATTER = new Intl.NumberFormat(undefined, {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function formatMoney(amount) {
  if (!Number.isFinite(amount)) return '—';
  return CURRENCY_FORMATTER.format(amount);
}

function parseLooseNumber(raw) {
  const s = String(raw ?? '').trim();
  if (!s) return { ok: false, value: null, reason: 'empty' };
  // allow commas in human input
  const normalized = s.replace(/,/g, '');
  const num = Number(normalized);
  if (!Number.isFinite(num)) return { ok: false, value: null, reason: 'nan' };
  return { ok: true, value: num, reason: null };
}

export function validateBill(rawBill) {
  const parsed = parseLooseNumber(rawBill);
  if (!parsed.ok) return { ok: false, value: null, message: 'Enter a bill amount.' };
  if (parsed.value < 0) return { ok: false, value: null, message: 'Bill cannot be negative.' };
  return { ok: true, value: parsed.value, message: '' };
}

export function validatePeople(rawPeople) {
  const parsed = parseLooseNumber(rawPeople);
  if (!parsed.ok) return { ok: false, value: null, message: 'Enter number of people.' };
  // People should be integer-like.
  if (!Number.isInteger(parsed.value))
    return { ok: false, value: null, message: 'People must be a whole number.' };
  if (parsed.value < 1) return { ok: false, value: null, message: 'People must be at least 1.' };
  return { ok: true, value: parsed.value, message: '' };
}

export function validateTipPercent(rawTip, { allowEmpty = true } = {}) {
  const parsed = parseLooseNumber(rawTip);
  if (!parsed.ok) {
    if (allowEmpty && String(rawTip ?? '').trim() === '') {
      return { ok: true, value: null, message: '' };
    }
    return { ok: false, value: null, message: 'Tip must be a number.' };
  }
  if (parsed.value < 0) return { ok: false, value: null, message: 'Tip cannot be negative.' };
  return { ok: true, value: parsed.value, message: '' };
}

function roundCurrency(amount) {
  // Guard against float drift.
  return Math.round((amount + Number.EPSILON) * 100) / 100;
}

export function calculateSplit({ bill, tipPercent, people }) {
  if (!Number.isFinite(bill) || bill < 0) {
    return { ok: false, tip: null, total: null, perPerson: null, reason: 'invalid-bill' };
  }
  if (!Number.isFinite(people) || people < 1) {
    return { ok: false, tip: null, total: null, perPerson: null, reason: 'invalid-people' };
  }
  if (!Number.isFinite(tipPercent) || tipPercent < 0) {
    return { ok: false, tip: null, total: null, perPerson: null, reason: 'invalid-tip' };
  }

  const tip = roundCurrency(bill * (tipPercent / 100));
  const total = roundCurrency(bill + tip);
  const perPerson = roundCurrency(total / people);

  return { ok: true, tip, total, perPerson, reason: null };
}
