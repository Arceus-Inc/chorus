const FILTERS = /** @type {const} */ ({
  all: 'all',
  todo: 'todo',
  done: 'done',
});

/**
 * @typedef {{ id: string, title: string, done: boolean }} Task
 * @typedef {{ tasks: Task[], filter: keyof typeof FILTERS }} TodoState
 */

export function createInitialState() {
  /** @type {TodoState} */
  return { tasks: [], filter: FILTERS.all };
}

function makeId() {
  // Small, collision-resistant enough for this slice.
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** @param {string} title */
export function normalizeTitle(title) {
  return String(title ?? '').trim().replace(/\s+/g, ' ');
}

/**
 * @param {TodoState} state
 * @param {string} title
 * @returns {TodoState}
 */
export function addTask(state, title) {
  const normalized = normalizeTitle(title);
  if (!normalized) return state;

  const task = { id: makeId(), title: normalized, done: false };
  return { ...state, tasks: [task, ...state.tasks] };
}

/**
 * @param {TodoState} state
 * @param {string} id
 * @returns {TodoState}
 */
export function toggleTask(state, id) {
  let changed = false;
  const tasks = state.tasks.map((t) => {
    if (t.id !== id) return t;
    changed = true;
    return { ...t, done: !t.done };
  });
  return changed ? { ...state, tasks } : state;
}

/**
 * @param {TodoState} state
 * @param {string} id
 * @returns {TodoState}
 */
export function removeTask(state, id) {
  const next = state.tasks.filter((t) => t.id !== id);
  return next.length === state.tasks.length ? state : { ...state, tasks: next };
}

/**
 * @param {TodoState} state
 * @param {keyof typeof FILTERS} filter
 * @returns {TodoState}
 */
export function setFilter(state, filter) {
  if (!Object.values(FILTERS).includes(filter)) return state;
  return state.filter === filter ? state : { ...state, filter };
}

/**
 * @param {TodoState} state
 * @returns {Task[]}
 */
export function selectVisibleTasks(state) {
  switch (state.filter) {
    case FILTERS.todo:
      return state.tasks.filter((t) => !t.done);
    case FILTERS.done:
      return state.tasks.filter((t) => t.done);
    case FILTERS.all:
    default:
      return state.tasks;
  }
}

/**
 * @param {TodoState} state
 * @returns {number}
 */
export function selectRemainingCount(state) {
  return state.tasks.reduce((acc, t) => acc + (t.done ? 0 : 1), 0);
}

export function remainingLabel(count) {
  return `${count} task${count === 1 ? '' : 's'} remaining`;
}

export { FILTERS };
