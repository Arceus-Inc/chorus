import { validateAll, normalizeSubmission, MAX_ATTENDEES } from './validation.js';

const appEl = document.getElementById('app');

const initialState = {
  status: 'editing', // editing | confirmed
  values: {
    name: '',
    email: '',
    attendees: '',
    vegetarian: '',
  },
  touched: {
    name: false,
    email: false,
    attendees: false,
    vegetarian: false,
  },
  submitted: null,
};

let state = structuredClone(initialState);

function setState(patch) {
  state = { ...state, ...patch };
  render();
}

function setValue(field, value) {
  const values = { ...state.values, [field]: value };
  setState({ values });
}

function markTouched(field) {
  const touched = { ...state.touched, [field]: true };
  setState({ touched });
}

function markAllTouched() {
  setState({
    touched: {
      name: true,
      email: true,
      attendees: true,
      vegetarian: true,
    },
  });
}

function fieldIds(field) {
  return {
    inputId: `rsvp-${field}`,
    errorId: `rsvp-${field}-error`,
  };
}

function render() {
  appEl.replaceChildren(state.status === 'confirmed' ? renderConfirmation() : renderForm());
}

function attemptSubmit() {
  markAllTouched();
  const next = validateAll(state.values);
  if (!next.isValid) {
    focusFirstInvalid(next.errors);
    return;
  }

  const submitted = normalizeSubmission(state.values);
  setState({ status: 'confirmed', submitted });
}

function renderForm() {
  const { errors, isValid } = validateAll(state.values);

  const form = document.createElement('form');
  form.noValidate = true;
  form.ariaLabel = 'RSVP form';

  form.append(
    renderTextField({
      field: 'name',
      label: 'Guest name',
      autocomplete: 'name',
      value: state.values.name,
      error: state.touched.name ? errors.name : null,
      onInput: (v) => setValue('name', v),
      onBlur: () => markTouched('name'),
    }),
    renderEmailField({
      field: 'email',
      label: 'Email address',
      autocomplete: 'email',
      value: state.values.email,
      error: state.touched.email ? errors.email : null,
      onInput: (v) => setValue('email', v),
      onBlur: () => markTouched('email'),
    }),
    renderNumberField({
      field: 'attendees',
      label: 'Number of attendees',
      hint: `Enter a whole number from 1 to ${MAX_ATTENDEES}.`,
      value: state.values.attendees,
      error: state.touched.attendees ? errors.attendees : null,
      onInput: (v) => setValue('attendees', v),
      onBlur: () => markTouched('attendees'),
    }),
    renderVegetarianField({
      field: 'vegetarian',
      label: 'Vegetarian meal needed?',
      value: state.values.vegetarian,
      error: state.touched.vegetarian ? errors.vegetarian : null,
      onChange: (v) => setValue('vegetarian', v),
      onBlur: () => markTouched('vegetarian'),
    }),
    renderActions({ isValid })
  );

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    attemptSubmit();
  });

  // Allow keyboard users to trigger validation even while the submit button is disabled
  // (e.g. pressing Enter inside a field).
  form.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;

    const active = document.activeElement;
    const isTextLike =
      active instanceof HTMLInputElement &&
      (active.type === 'text' || active.type === 'email' || active.type === 'number');

    if (!isTextLike) return;

    e.preventDefault();
    attemptSubmit();
  });

  return form;
}

function focusFirstInvalid(errors) {
  const order = ['name', 'email', 'attendees', 'vegetarian'];
  const first = order.find((f) => errors[f]);
  if (!first) return;

  if (first === 'vegetarian') {
    const { inputId } = fieldIds('vegetarian');
    const checked = document.querySelector(`input[name="vegetarian"]:checked`);
    const target = checked ?? document.getElementById(`${inputId}-yes`) ?? document.getElementById(`${inputId}-no`);
    target?.focus();
    return;
  }

  const { inputId } = fieldIds(first);
  document.getElementById(inputId)?.focus();
}

function renderFieldShell({ field, labelText, controlEl, errorText, hintText }) {
  const shell = document.createElement('div');
  shell.className = 'field';

  const label = document.createElement('label');
  const { inputId, errorId } = fieldIds(field);
  label.htmlFor = inputId;
  label.textContent = labelText;

  const describedBy = [];

  if (hintText) {
    const hint = document.createElement('p');
    hint.className = 'hint';
    hint.id = `${inputId}-hint`;
    hint.textContent = hintText;
    describedBy.push(hint.id);
    shell.append(label, hint);
  } else {
    shell.append(label);
  }

  if (errorText) {
    const err = document.createElement('p');
    err.className = 'error';
    err.id = errorId;
    err.textContent = errorText;
    describedBy.push(errorId);
    shell.append(controlEl, err);
  } else {
    shell.append(controlEl);
  }

  if (describedBy.length) {
    controlEl.setAttribute('aria-describedby', describedBy.join(' '));
  } else {
    controlEl.removeAttribute('aria-describedby');
  }

  controlEl.setAttribute('aria-invalid', errorText ? 'true' : 'false');

  return shell;
}

function renderTextField({ field, label, autocomplete, value, error, onInput, onBlur }) {
  const input = document.createElement('input');
  const { inputId } = fieldIds(field);
  input.type = 'text';
  input.id = inputId;
  input.name = field;
  input.autocomplete = autocomplete;
  input.required = true;
  input.value = value;
  input.addEventListener('input', (e) => onInput(e.currentTarget.value));
  input.addEventListener('blur', () => onBlur());

  return renderFieldShell({ field, labelText: label, controlEl: input, errorText: error });
}

function renderEmailField({ field, label, autocomplete, value, error, onInput, onBlur }) {
  const input = document.createElement('input');
  const { inputId } = fieldIds(field);
  input.type = 'email';
  input.id = inputId;
  input.name = field;
  input.autocomplete = autocomplete;
  input.required = true;
  input.value = value;
  input.addEventListener('input', (e) => onInput(e.currentTarget.value));
  input.addEventListener('blur', () => onBlur());

  return renderFieldShell({ field, labelText: label, controlEl: input, errorText: error });
}

function renderNumberField({ field, label, hint, value, error, onInput, onBlur }) {
  const input = document.createElement('input');
  const { inputId } = fieldIds(field);
  input.type = 'number';
  input.id = inputId;
  input.name = field;
  input.inputMode = 'numeric';
  input.min = '1';
  input.max = String(MAX_ATTENDEES);
  input.step = '1';
  input.required = true;
  input.value = value;
  input.addEventListener('input', (e) => onInput(e.currentTarget.value));
  input.addEventListener('blur', () => onBlur());

  return renderFieldShell({ field, labelText: label, controlEl: input, errorText: error, hintText: hint });
}

function renderVegetarianField({ field, label, value, error, onChange, onBlur }) {
  const { inputId, errorId } = fieldIds(field);

  const fieldset = document.createElement('fieldset');
  fieldset.id = inputId;
  fieldset.dataset.fieldset = 'true';

  const legend = document.createElement('legend');
  legend.textContent = label;

  const radios = document.createElement('div');
  radios.className = 'radios';

  const yesId = `${inputId}-yes`;
  const noId = `${inputId}-no`;

  const yes = document.createElement('input');
  yes.type = 'radio';
  yes.name = field;
  yes.id = yesId;
  yes.value = 'yes';
  yes.required = true;
  yes.checked = value === 'yes';

  const yesLabel = document.createElement('label');
  yesLabel.htmlFor = yesId;
  yesLabel.textContent = 'Yes';

  const no = document.createElement('input');
  no.type = 'radio';
  no.name = field;
  no.id = noId;
  no.value = 'no';
  no.required = true;
  no.checked = value === 'no';

  const noLabel = document.createElement('label');
  noLabel.htmlFor = noId;
  noLabel.textContent = 'No';

  const yesLine = document.createElement('div');
  yesLine.className = 'radioLine';
  yesLine.append(yes, yesLabel);

  const noLine = document.createElement('div');
  noLine.className = 'radioLine';
  noLine.append(no, noLabel);

  radios.append(yesLine, noLine);

  if (error) {
    yes.setAttribute('aria-describedby', errorId);
    no.setAttribute('aria-describedby', errorId);
    fieldset.setAttribute('aria-describedby', errorId);
  } else {
    yes.removeAttribute('aria-describedby');
    no.removeAttribute('aria-describedby');
    fieldset.removeAttribute('aria-describedby');
  }

  yes.setAttribute('aria-invalid', error ? 'true' : 'false');
  no.setAttribute('aria-invalid', error ? 'true' : 'false');
  fieldset.setAttribute('aria-invalid', error ? 'true' : 'false');

  yes.addEventListener('change', (e) => {
    if (e.currentTarget.checked) onChange('yes');
  });
  no.addEventListener('change', (e) => {
    if (e.currentTarget.checked) onChange('no');
  });

  yes.addEventListener('blur', () => onBlur());
  no.addEventListener('blur', () => onBlur());

  fieldset.append(legend, radios);

  if (error) {
    const err = document.createElement('p');
    err.className = 'error';
    err.id = errorId;
    err.textContent = error;
    fieldset.append(err);
  }

  return fieldset;
}

function renderActions({ isValid }) {
  const actions = document.createElement('div');
  actions.className = 'actions';

  const submit = document.createElement('button');
  submit.type = 'submit';
  submit.className = 'primary';
  submit.textContent = 'Confirm RSVP';
  submit.disabled = !isValid;

  const note = document.createElement('p');
  note.className = 'hint';
  note.textContent = 'All fields are required.';

  actions.append(submit, note);
  return actions;
}

function renderConfirmation() {
  const wrap = document.createElement('div');
  wrap.className = 'confirmation';

  const h2 = document.createElement('h2');
  h2.textContent = 'RSVP confirmed';

  const p = document.createElement('p');
  p.className = 'hint';
  p.textContent = 'Thanks! Here is what we received:';

  const card = document.createElement('div');
  card.className = 'card';

  const dl = document.createElement('dl');

  const submitted = state.submitted;
  const vegText = submitted.vegetarian ? 'Yes' : 'No';

  dl.append(
    dtdd('Guest name', submitted.name),
    dtdd('Email address', submitted.email),
    dtdd('Number of attendees', String(submitted.attendees)),
    dtdd('Vegetarian meal needed?', vegText)
  );

  card.append(dl);
  wrap.append(h2, p, card);

  return wrap;
}

function dtdd(dtText, ddText) {
  const dt = document.createElement('dt');
  dt.textContent = dtText;
  const dd = document.createElement('dd');
  dd.textContent = ddText;
  const frag = document.createDocumentFragment();
  frag.append(dt, dd);
  return frag;
}

render();
