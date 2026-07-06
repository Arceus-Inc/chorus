---
name: keyboard-and-focus
description: How to make an interface fully operable from the keyboard in code — tab order, a visible focus ring, focus management for overlays (trap, Esc, restore), and arrow-key navigation for composite widgets.
when_to_use: Read for any interactive surface, especially menus, dialogs, tabs, and custom widgets. It is the interaction half of accessibility; semantic-html-and-aria is the structural half.
---

# Keyboard & Focus

Mouse-first code silently strands keyboard and screen-reader users. Because it's easy to test with a
pointer, it's easy to forget that every interaction must also work from the keyboard, in a predictable
order, with focus you can *see* and that never gets trapped. This is the craft of getting that right in
real code.

## The one rule

**Everything you can do with a pointer works from the keyboard, and focus is always visible and never
trapped.**

## Tab order & reachability

- Native interactive elements are focusable for free. Custom widgets need `tabindex="0"`; things that
  aren't interactive get nothing (or `tabindex="-1"` to be focusable only programmatically).
- Tab order follows visual order. If the DOM fights the layout, fix the DOM — never use a positive
  `tabindex` (`tabindex > 0` is an anti-pattern that breaks the natural order).
- Provide a **skip link** as the first focusable element to jump past repeated nav to `<main>`.

## Visible focus

- Every focusable element has a clearly visible focus indicator meeting 3:1 contrast against its
  background.
- Use `:focus-visible` so pointer clicks don't show a ring but keyboard users always do. **Never**
  `outline: none` without a stronger replacement — removing the ring with no substitute is a hard fail.

## Overlays & composite widgets

- **Dialog/modal**: move focus into the dialog on open, **trap** it inside while open, close on `Esc`,
  and **restore** focus to the trigger on close.
- **Menu/listbox/tabs/radiogroup**: one tab stop for the group, **arrow keys** move within it (roving
  tabindex), `Enter`/`Space` activate, `Esc` closes. Follow the WAI-ARIA pattern for the role.
- Wire these with real `keydown` handlers and test them in the e2e with `page.keyboard`.

## Before you finish

1. Tab through the whole app: is every control reachable, in a sensible order, with a visible ring?
2. For each overlay: does focus enter, trap, `Esc`-close, and return to the trigger?
3. For each custom widget: are the arrow-key bindings implemented and its ARIA state kept in sync?
4. Did you avoid `outline: none` without a replacement and any positive `tabindex`?
