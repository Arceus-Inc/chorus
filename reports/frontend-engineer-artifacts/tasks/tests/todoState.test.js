import test from 'node:test';
import assert from 'node:assert/strict';
import {
  addTask,
  createInitialState,
  removeTask,
  selectRemainingCount,
  selectVisibleTasks,
  setFilter,
  toggleTask,
} from '../src/todoState.js';

test('addTask: adds a trimmed task (prepends) and increments remaining count', () => {
  let state = createInitialState();
  state = addTask(state, '  buy   milk  ');

  assert.equal(state.tasks.length, 1);
  assert.equal(state.tasks[0].title, 'buy milk');
  assert.equal(state.tasks[0].done, false);
  assert.equal(selectRemainingCount(state), 1);
});

test('addTask: rejects empty/whitespace-only titles', () => {
  const state = createInitialState();
  const next = addTask(state, '   ');
  assert.equal(next, state);
  assert.equal(next.tasks.length, 0);
  assert.equal(selectRemainingCount(next), 0);
});

test('toggleTask: flips done/undone and updates remaining count', () => {
  let state = createInitialState();
  state = addTask(state, 'one');
  state = addTask(state, 'two');

  const id = state.tasks[0].id; // "two" due to prepend

  assert.equal(selectRemainingCount(state), 2);
  state = toggleTask(state, id);
  assert.equal(state.tasks[0].done, true);
  assert.equal(selectRemainingCount(state), 1);

  state = toggleTask(state, id);
  assert.equal(state.tasks[0].done, false);
  assert.equal(selectRemainingCount(state), 2);
});

test('removeTask: removes a task and updates remaining count', () => {
  let state = createInitialState();
  state = addTask(state, 'a');
  state = addTask(state, 'b');

  const removeId = state.tasks[1].id; // "a"
  state = toggleTask(state, state.tasks[0].id); // mark "b" done

  assert.equal(selectRemainingCount(state), 1);
  state = removeTask(state, removeId);

  assert.equal(state.tasks.length, 1);
  assert.equal(state.tasks[0].title, 'b');
  assert.equal(selectRemainingCount(state), 0);
});

test('filter selector: returns visible tasks for all/todo/done', () => {
  let state = createInitialState();
  state = addTask(state, 'x');
  state = addTask(state, 'y');
  state = toggleTask(state, state.tasks[0].id); // mark y done

  assert.equal(selectVisibleTasks(state).length, 2);

  state = setFilter(state, 'todo');
  assert.deepEqual(
    selectVisibleTasks(state).map((t) => t.title),
    ['x']
  );

  state = setFilter(state, 'done');
  assert.deepEqual(
    selectVisibleTasks(state).map((t) => t.title),
    ['y']
  );
});

test('setFilter: ignores invalid filter values', () => {
  const state = createInitialState();
  // @ts-expect-error - deliberately invalid
  const next = setFilter(state, 'nope');
  assert.equal(next, state);
});
