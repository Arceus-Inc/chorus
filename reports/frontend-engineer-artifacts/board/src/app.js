import {
  addCard,
  createEmptyState,
  laneLabels,
  loadFromStorage,
  moveCard,
  removeCard,
  saveToStorage,
} from './boardState.js';

const els = {
  form: /** @type {HTMLFormElement} */ (document.getElementById('add-form')),
  input: /** @type {HTMLInputElement} */ (document.getElementById('task-title')),
  error: /** @type {HTMLDivElement} */ (document.getElementById('task-error')),
  storageError: /** @type {HTMLDivElement} */ (document.getElementById('storage-error')),
  lists: {
    todo: /** @type {HTMLUListElement} */ (document.getElementById('cards-todo')),
    inprogress: /** @type {HTMLUListElement} */ (document.getElementById('cards-inprogress')),
    done: /** @type {HTMLUListElement} */ (document.getElementById('cards-done')),
  },
};

/** @typedef {{ state: import('./boardState.js').BoardState, lastMovedCardId: string|null }} AppState */

/** @type {AppState} */
let app = { state: createEmptyState(), lastMovedCardId: null };

function showInlineError(message) {
  els.error.textContent = message;
  els.error.hidden = !message;
}

function showStorageError(message) {
  els.storageError.textContent = message;
  els.storageError.hidden = !message;
}

function persist() {
  try {
    saveToStorage(window.localStorage, app.state);
    showStorageError('');
  } catch {
    showStorageError('Could not save to browser storage. Your changes may not persist.');
  }
}

function focusCardById(cardId) {
  if (!cardId) return;
  const btn = document.querySelector(`[data-focus-card-id="${CSS.escape(cardId)}"]`);
  if (btn && btn instanceof HTMLElement) btn.focus();
}

function render() {
  for (const lane of /** @type {const} */ (['todo', 'inprogress', 'done'])) {
    els.lists[lane].replaceChildren();
    const cards = app.state.cards.filter((c) => c.lane === lane);

    if (cards.length === 0) {
      const li = document.createElement('li');
      li.className = 'help';
      li.textContent = 'Empty.';
      els.lists[lane].append(li);
      continue;
    }

    for (const card of cards) {
      const li = document.createElement('li');
      li.className = 'card';

      const title = document.createElement('p');
      title.className = 'card-title';
      title.textContent = card.title;

      const actions = document.createElement('div');
      actions.className = 'card-actions';

      const moveLeft = document.createElement('button');
      moveLeft.type = 'button';
      moveLeft.textContent = 'Move left';
      moveLeft.dataset.action = 'move-backward';
      moveLeft.dataset.cardId = card.id;
      moveLeft.setAttribute('aria-label', `Move “${card.title}” to previous lane`);
      moveLeft.disabled = lane === 'todo';

      const moveRight = document.createElement('button');
      moveRight.type = 'button';
      moveRight.textContent = 'Move right';
      moveRight.dataset.action = 'move-forward';
      moveRight.dataset.cardId = card.id;
      moveRight.setAttribute('aria-label', `Move “${card.title}” to next lane`);
      moveRight.disabled = lane === 'done';

      const remove = document.createElement('button');
      remove.type = 'button';
      remove.textContent = 'Remove';
      remove.className = 'btn-danger';
      remove.dataset.action = 'remove';
      remove.dataset.cardId = card.id;
      remove.setAttribute('aria-label', `Remove “${card.title}”`);

      // The first enabled control becomes the focus target when we move.
      const focusTarget = !moveLeft.disabled ? moveLeft : moveRight;
      focusTarget.setAttribute('data-focus-card-id', card.id);

      actions.append(moveLeft, moveRight, remove);
      li.append(title, actions);
      els.lists[lane].append(li);
    }
  }

  if (app.lastMovedCardId) {
    const id = app.lastMovedCardId;
    app.lastMovedCardId = null;
    queueMicrotask(() => focusCardById(id));
  }
}

function dispatch(action) {
  showInlineError('');

  try {
    switch (action.type) {
      case 'add': {
        app.state = addCard(app.state, action.title);
        app.lastMovedCardId = app.state.cards[0]?.id ?? null;
        persist();
        render();
        els.input.focus();
        els.input.select();
        return;
      }
      case 'move': {
        app.state = moveCard(app.state, action.cardId, action.direction);
        app.lastMovedCardId = action.cardId;
        persist();
        render();
        return;
      }
      case 'remove': {
        app.state = removeCard(app.state, action.cardId);
        persist();
        render();
        els.input.focus();
        return;
      }
      default:
        return;
    }
  } catch (e) {
    showInlineError(e instanceof Error ? e.message : 'Something went wrong');
  }
}

function onBoardClick(e) {
  const target = e.target;
  if (!(target instanceof HTMLButtonElement)) return;
  const action = target.dataset.action;
  const cardId = target.dataset.cardId;
  if (!action || !cardId) return;

  if (action === 'remove') dispatch({ type: 'remove', cardId });
  if (action === 'move-forward') dispatch({ type: 'move', cardId, direction: 'forward' });
  if (action === 'move-backward') dispatch({ type: 'move', cardId, direction: 'backward' });
}

function hydrate() {
  try {
    app.state = loadFromStorage(window.localStorage);
    showStorageError('');
  } catch {
    app.state = createEmptyState();
    showStorageError('Could not read browser storage; starting with an empty board.');
  }
}

document.addEventListener('click', onBoardClick);
els.form.addEventListener('submit', (e) => {
  e.preventDefault();
  dispatch({ type: 'add', title: els.input.value });
});

hydrate();
render();

window.__RUN_BOARD_LANES__ = laneLabels;
