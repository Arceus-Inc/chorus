import { computeSplit, formatUSD, sanitizeInputs } from './calc.js';

const els = {
  bill: document.querySelector('#billAmount'),
  tipSelect: document.querySelector('#tipPercent'),
  customTipField: document.querySelector('#customTipField'),
  customTip: document.querySelector('#customTip'),
  people: document.querySelector('#peopleCount'),
  tipAmount: document.querySelector('#tipAmount'),
  totalAmount: document.querySelector('#totalAmount'),
  perPersonAmount: document.querySelector('#perPersonAmount'),
  announce: document.querySelector('#announce'),
  billError: document.querySelector('#billError'),
  tipError: document.querySelector('#tipError'),
  peopleError: document.querySelector('#peopleError'),
};

function getTipPercentValue() {
  const v = els.tipSelect.value;
  if (v === 'custom') return els.customTip.value;
  return v;
}

function setError(el, message) {
  el.textContent = message || '';
}

function render() {
  const { bill, people, tipPercent, meta } = sanitizeInputs({
    billInput: els.bill.value,
    peopleInput: els.people.value,
    tipPercentInput: getTipPercentValue(),
  });

  // Inline guidance (non-blocking). We avoid making the UI "invalid" in a way
  // that traps the user; we just show a gentle message and keep stable output.
  setError(
    els.billError,
    meta.billKind === 'invalid' || (bill !== null && bill < 0)
      ? 'Enter a valid bill amount (0 or more).'
      : ''
  );

  setError(
    els.peopleError,
    meta.peopleKind === 'invalid'
      ? 'Enter a whole number of people (1 or more).'
      : ''
  );

  setError(
    els.tipError,
    meta.tipKind === 'invalid' ? 'Enter a valid tip percentage (0 or more).' : ''
  );

  const values = computeSplit({
    bill: bill ?? 0,
    people: people ?? 0,
    tipPercent: tipPercent ?? 0,
  });

  els.tipAmount.textContent = formatUSD(values.tip);
  els.totalAmount.textContent = formatUSD(values.total);
  els.perPersonAmount.textContent = formatUSD(values.perPerson);

  // Optional screen reader announcement that updates but doesn't spam too much.
  els.announce.textContent = `Tip ${els.tipAmount.textContent}, total ${
    els.totalAmount.textContent
  }, per person ${els.perPersonAmount.textContent}.`;
}

function syncCustomTipVisibility() {
  const isCustom = els.tipSelect.value === 'custom';
  els.customTipField.hidden = !isCustom;
  if (!isCustom) {
    els.customTip.value = '';
    setError(els.tipError, '');
  }
}

function onAnyInput() {
  syncCustomTipVisibility();
  render();
}

// Live update
['input', 'change'].forEach((evt) => {
  els.bill.addEventListener(evt, onAnyInput);
  els.people.addEventListener(evt, onAnyInput);
  els.tipSelect.addEventListener(evt, onAnyInput);
  els.customTip.addEventListener(evt, onAnyInput);
});

// Initial paint
syncCustomTipVisibility();
render();
