import {
  addTask,
  createInitialState,
  FILTERS,
  removeTask,
  remainingLabel,
  selectRemainingCount,
  selectVisibleTasks,
  setFilter,
  toggleTask,
} from './todoState.js';

/** @type {import('./todoState.js').TodoState} */
let state = createInitialState();

const els = {
  form: /** @type {HTMLFormElement} */ (document.getElementById('add-form')),
  title: /** @type {HTMLInputElement} */ (document.getElementById('task-title')),
  error: /** @type {HTMLParagraphElement} */ (document.getElementById('title-error')),
  filterRadios: /** @type {NodeListOf<HTMLInputElement>} */ (
    document.querySelectorAll('input[name="filter"]')
  ),
  list: /** @type {HTMLUListElement} */ (document.getElementById('task-list')),
  empty: /** @type {HTMLDivElement} */ (document.getElementById('empty')),
  remaining: /** @type {HTMLDivElement} */ (document.getElementById('remaining')),
};

function setState(next) {
  state = next;
  render();
}

function showError(message) {
  if (!message) {
    els.error.hidden = true;
    els.error.textContent = '';
    els.title.removeAttribute('aria-invalid');
    els.title.setAttribute('aria-describedby', 'title-help');
    return;
  }

  els.error.textContent = message;
  els.error.hidden = false;
  els.title.setAttribute('aria-invalid', 'true');
  els.title.setAttribute('aria-describedby', 'title-help title-error');
}

function render() {
  // remaining count
  const remaining = selectRemainingCount(state);
  els.remaining.textContent = remainingLabel(remaining);

  // task list
  const visible = selectVisibleTasks(state);
  els.list.replaceChildren(...visible.map(renderTask));

  const emptyMessage =
    state.tasks.length === 0
      ? 'No tasks yet. Add your first one above.'
      : visible.length === 0
        ? 'No tasks match this filter.'
        : '';

  if (emptyMessage) {
    els.empty.hidden = false;
    els.empty.textContent = emptyMessage;
  } else {
    els.empty.hidden = true;
    els.empty.textContent = '';
  }
}

/** @param {import('./todoState.js').Task} task */
function renderTask(task) {
  const li = document.createElement('li');
  li.dataset.taskId = task.id;

  const toggleWrap = document.createElement('div');

  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.checked = task.done;
  const toggleLabel = task.done
    ? `Mark ${task.title} as not done`
    : `Mark ${task.title} as done`;
  checkbox.setAttribute('aria-label', toggleLabel);
  checkbox.addEventListener('change', () => {
    setState(toggleTask(state, task.id));
  });

  toggleWrap.appendChild(checkbox);

  const title = document.createElement('span');
  title.className = `task-title${task.done ? ' done' : ''}`;
  title.textContent = task.title;

  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'danger';
  remove.textContent = 'Remove';
  remove.setAttribute('aria-label', `Remove ${task.title}`);
  remove.addEventListener('click', () => {
    setState(removeTask(state, task.id));
  });

  li.append(toggleWrap, title, remove);
  return li;
}

// events
els.form.addEventListener('submit', (e) => {
  e.preventDefault();
  const before = state;
  const next = addTask(state, els.title.value);
  if (next === before) {
    showError('Please enter a task title.');
    els.title.focus();
    return;
  }

  showError('');
  setState(next);
  els.form.reset();
  els.title.focus();
});

els.title.addEventListener('input', () => {
  if (!els.error.hidden) showError('');
});

els.filterRadios.forEach((r) => {
  r.addEventListener('change', () => {
    if (!r.checked) return;
    const value = /** @type {keyof typeof FILTERS} */ (r.value);
    setState(setFilter(state, value));
  });
});

// initial a11y wiring
els.title.setAttribute('aria-describedby', 'title-help');

render();
