---
name: react-doctor
description: How to avoid the React footguns that ship subtle bugs — the Rules of Hooks, correct effect dependencies and cleanup, stable keys in lists, colocating and lifting state correctly, and taming needless re-renders.
when_to_use: Read when you have chosen React (or a React meta-framework). It is the correctness checklist for hooks, effects, keys, and state; pair it with frontend-patterns for the component/hook/state patterns themselves, component-testing to prove the behavior, and scaffolding-with-vite to set the project up.
---

# React Doctor

React is easy to write and easy to write *subtly wrong*. The bugs rarely throw — they show up as stale
values, double-fetches, lost input focus, or lists that scramble on update. This is the checklist that
catches them before they ship.

## The one rule

**Hooks run unconditionally at the top level; effects declare every dependency and clean up; lists use
stable identity keys; state lives at the lowest common owner. Break one and you ship a quiet bug.**

## Rules of Hooks

- Call hooks only at the **top level** of a component or a custom hook — never inside conditionals,
  loops, or nested functions. The call order must be identical on every render.
- Custom hooks are named `useX` and follow the same rules. Don't call hooks from event handlers or
  plain functions.

## Effects: dependencies and cleanup

- List **every** value from component scope that the effect reads in its dependency array. A missing
  dep gives you a stale closure; lying to the linter hides a real bug.
- If an effect subscribes, opens a timer, or starts a fetch, **return a cleanup** that tears it down —
  otherwise you leak and double-fire (especially under Strict Mode's intentional double-invoke in dev).
- Don't put derived data in an effect that just `setState`s — compute it during render (optionally
  `useMemo`) instead of syncing state to state.
- Effects are for *synchronizing with the outside world*, not for reacting to user events — do that in
  the event handler.

## Keys and lists

- Give each list item a **stable, unique key** tied to the data's identity (an id), not the array
  index. Index keys corrupt state and DOM when the list reorders, inserts, or deletes.
- Never generate a fresh key each render (`key={Math.random()}`) — it remounts the item every time.

## State: colocate, lift, derive

- Put state at the **lowest common ancestor** that needs it; colocated state re-renders less and reads
  simpler. Lift it only as far as the sharing requires.
- Don't duplicate derived values into state — derive them during render so they can't drift.
- Keep controlled inputs controlled (always pass `value` + `onChange`); don't flip between controlled
  and uncontrolled.

## Taming re-renders (only when it matters)

- Reach for `useMemo`/`useCallback`/`memo` when a measured cost or an identity-sensitive dependency
  demands it — not reflexively. Premature memoization is noise that hides real problems.
- A component re-renders when its state/props change; lifting state too high re-renders whole subtrees.
  Fix the tree, not the symptom.

## Before you finish

1. Are all hooks unconditional and top-level, in stable order?
2. Does every effect list all its deps and clean up what it starts?
3. Do lists use stable identity keys (never the index for mutable lists)?
4. Is state colocated at the lowest owner, with derived values computed, not stored?
5. Did you prove the behavior with `component-testing` and the real flow with Playwright?
