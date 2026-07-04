---
name: semantic-html-and-aria
description: How to build accessibility in from the first line — semantic elements first, an accessible name for every control, landmarks for structure, and ARIA only as a last resort when no native element fits.
when_to_use: Read while writing markup for any surface. It is the structural half of accessibility (keyboard-and-focus is the interaction half); forms-and-validation specializes it for inputs.
---

# Semantic HTML & ARIA

Accessibility is a requirement, not a cleanup pass. The cheapest, most robust way to get it is to reach
for the right HTML element, because native elements come with roles, keyboard behavior, and focus for
free. ARIA is a patch for when the platform has no element for what you need — and the first rule of
ARIA is: don't use ARIA if a native element will do.

## The one rule

**Every control has an accessible name and a correct role — and you get both from a native element
before you reach for a single ARIA attribute.**

## Semantic elements first

- Actions are `<button>`; navigation is `<a href>`. Never a `<div onclick>` — it has no role, no
  keyboard, no focus, and screen readers skip it.
- Use structural landmarks: `<header>`, `<nav>`, `<main>` (exactly one), `<footer>`, `<section>` with a
  heading. One `<h1>` per page; heading levels descend without skipping.
- Group form controls with `<fieldset>`/`<legend>`; associate every input with a `<label for>`.
- Lists are `<ul>`/`<ol>`/`<li>`; tabular data is a `<table>` with `<th scope>`. Structure carries
  meaning to assistive tech.

## Accessible names

- Every interactive element must have a name: visible text, a `<label>`, `aria-label`, or
  `aria-labelledby`. An icon-only button needs `aria-label`.
- Images that convey meaning need `alt`; decorative images take empty `alt=""`.

## ARIA — only when native can't

- If you must build a custom widget (tabs, combobox, dialog), follow the WAI-ARIA Authoring Practices
  pattern for that role exactly: the right `role`, the required states (`aria-expanded`, `aria-selected`,
  `aria-checked`), and the keyboard interactions that role implies.
- Reflect state in ARIA as it changes in JS (`aria-expanded="true"` when open). Stale ARIA lies to
  screen readers. Never put a `role` on an element that already has that role natively.

## Before you finish

1. Is every action a `button` and every navigation an `a href` — zero clickable `div`s?
2. Does every control have an accessible name you can state out loud?
3. Are there landmarks (`main`, `nav`) and a sensible heading outline?
4. If you used ARIA, could a native element have done it instead? If so, switch.
