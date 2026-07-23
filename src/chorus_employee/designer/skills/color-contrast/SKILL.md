---
name: color-contrast
description: How to hit WCAG contrast ratios in practice — the 4.5:1 / 3:1 thresholds, what they apply to, and the common gray-on-white and brand-color traps — using tokens that are known to pass.
when_to_use: Read whenever a spec sets text, icon, border, or state color, and during the accessibility audit. It is the visual half of wcag-conformance; keyboard-and-focus is the interaction half.
---

# Color Contrast

Low contrast is the single most common accessibility failure, and the most seductive: light-gray text
and subtle borders look *elegant* and are unreadable for many users. A fluent model reaches for them by
default. This skill makes the thresholds concrete so you design to them instead of discovering the
failure later.

## The one rule

**Meet the ratio or don't ship the color.** Contrast is a hard threshold, not a matter of taste — if a
token pair fails, it fails, however good it looks on your monitor.

## The thresholds

- **Normal text**: ≥ **4.5:1** against its background.
- **Large text** (≥ 24px, or ≥ 18.66px/14pt **bold**): ≥ **3:1**.
- **Non-text essentials** — icons that carry meaning, input borders, control outlines, focus rings,
  chart segments you must tell apart: ≥ **3:1**. (WCAG 1.4.11)
- Pure decoration and disabled controls are exempt — but don't hide *real* information in a disabled-
  looking style.

## The traps

- **Gray-on-white body text**: `#999` on white is ~2.8:1 — fails. Placeholder-gray as real text is the
  classic offender.
- **Brand color on white**: many brand blues/greens fail at body size. Use them for large text or
  darken to a token that passes.
- **Color-only state**: contrast doesn't rescue color-only meaning — you still need a second signal
  (icon/label). See `wcag-conformance`.
- **State variants**: hover/disabled/placeholder shades often quietly drop below the floor — check each
  state, not just the resting one.
- **Text over images/gradients**: contrast must hold over the *worst* pixel behind the text — add a
  scrim/overlay.

## Before you finish

1. For each text token pair, name the ratio (or the known-passing token) — don't eyeball it.
2. Check hover, disabled, and placeholder states, not just default.
3. Verify meaningful icons, borders, and focus rings clear 3:1.
4. Prefer picking a `DESIGN.md` token documented as accessible over hand-tuning a hex.
