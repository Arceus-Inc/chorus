---
name: keyboard-and-focus
description: How to specify keyboard operability and focus management — tab order, focus-visible, focus trapping in overlays, skip links, and roving tabindex — so the UI is fully usable without a mouse.
when_to_use: Read for any interactive surface (forms, menus, dialogs, tabs, custom widgets) and during the accessibility audit. It is the keyboard half of wcag-conformance; color-contrast is the visual half.
---

# Keyboard & Focus

Mouse-first design silently strands keyboard and screen-reader users. Because a fluent model reasons in
terms of clicks, it forgets that every interaction must also work from the keyboard, in a predictable
order, with focus you can *see* and that never gets trapped. This is the craft of getting that right.

## The one rule

**Everything you can do with a pointer, you can do from the keyboard — and you can always see where
focus is.** No mouse-only actions, no invisible focus, no traps.

## Tab order & reachability

- Every interactive element is in the tab order (native elements are for free; custom widgets need
  `tabindex="0"`). Non-interactive things are *not* (`tabindex="-1"` or nothing).
- Tab order follows reading/visual order. If DOM order fights visual order, fix the DOM — don't paper
  over it with positive `tabindex` values (never use `tabindex > 0`).
- Provide a **skip link** to jump past repeated nav to main content.

## Visible focus

- Every focusable element has a **clearly visible focus indicator** meeting 3:1 non-text contrast.
- Use `:focus-visible` so pointer users don't see rings but keyboard users always do. Never
  `outline: none` without a stronger replacement — removing focus with no substitute is a hard failure.

## Composite widgets & overlays

- **Roving tabindex / arrow-key navigation** for radio groups, tabs, menus, toolbars, listboxes: one
  tab stop for the group, arrows move within it (follow the WAI-ARIA Authoring Practices for the role).
- **Modals/dialogs**: focus moves into the dialog on open, is **trapped** inside while open, `Esc`
  closes, and focus **returns** to the trigger on close.
- **Menus/popovers**: open on Enter/Space, navigate with arrows, close on `Esc`, restore focus.

## Before you finish

1. Tab through the whole spec in your head: is the order sensible, is every control reachable, is
   focus always visible?
2. For each overlay, specify open-focus, trap, `Esc`, and return-focus behavior explicitly.
3. For each custom widget, name its ARIA pattern and its key bindings.
4. Confirm nothing removes the focus outline without a compliant replacement.
