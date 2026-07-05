# Sprint 1 — run-drift: Login form drift/a11y audit + corrected spec

Scope: **LoginForm.tsx** only. Deliverable is a spec (no code changes).

---

## 1) Drift + accessibility audit (current `LoginForm.tsx`)

Source summary (current code): inline-styled `<form>` with two `<label>` elements not associated to their `<input>`s, two untyped inputs, always-visible red error text, and an inline-styled submit `<button>`.

### A. Design-system violations (with exact on-system fixes)

1) **Raw hex colors used (multiple)**
- Current:
  - form bg `#12151c`
  - input bg `#0d1017`
  - input border `#2b2b2b`
  - label text `#8f9bb3`
  - button bg `#3b7ce0`
  - error text `red`
- Why this is a violation: `DESIGN.md` requires **semantic tokens only** (“never raw hex in a surface”).
- On-system fixes (map to Nimbus tokens):
  - container background → `color.bg.surface`
  - container border (if present) → `color.border.subtle`
  - input surface/border → Nimbus `Input` (surface bg + `color.border.subtle`)
  - labels → `color.text.secondary`
  - primary action → Nimbus `Button(variant=primary)` (uses `color.accent.default` / `color.accent.hover`)
  - error text → `color.danger.default` (plus semantics; see a11y)

2) **Off-scale spacing: `padding: 18px`**
- Current: `18px`.
- Why: Nimbus spacing steps are `space.1=4`, `space.2=8`, `space.3=12`, `space.4=16`, `space.6=24`, `space.8=32`.
- Fix: container padding → `space.4`.

3) **Off-token radius: `borderRadius: 5px` (form + button)**
- Current: `5px`.
- Why: system defines `radius.md` 8px (documented on Button; use same token for this card).
- Fix:
  - Use `radius.md` for the container.
  - Use Nimbus `Button` which already applies `radius.md`.

4) **Off-system control sizing: inputs at 40px; button at 38px**
- Current: `height: 40px` inputs, `height: 38px` button.
- Why: Nimbus defines `Input` height **36px** and `Button` height **36px**.
- Fix: use Nimbus `Input` + Nimbus `Button` default size.

5) **Rebuilding system components via inline styles**
- Current: styles are hand-authored rather than using Nimbus components.
- Fix: implement with Nimbus components:
  - `Input`
  - `Button` variants as documented (`primary`, `secondary`, `ghost`, `danger`)

6) **Typography drift: label `fontSize: 13px`**
- Current: 13px.
- Why: type must use named scale steps; labels should be `text.sm` with weight 500.
- Fix: use Nimbus `Input` label pattern (label above field, `text.sm`, 500).

### B. Accessibility violations (with exact fixes)

1) **Labels are not programmatically associated to inputs**
- Current: `<label>Email</label>` followed by `<input />` without `htmlFor`/`id`.
- Impact: screen readers may not announce correct label; label click may not focus field.
- Fix: ensure each input has an accessible name via proper association:
  - `Input(label="Email", id="login-email")` renders `<label for="login-email">` and `<input id="login-email">`.

2) **Missing input types + autocomplete**
- Current: both inputs have no `type`, `name`, `autoComplete`.
- Impact: password is visible, autofill and virtual keyboards are suboptimal.
- Fix:
  - Email: `type="email"`, `name="email"`, `autoComplete="username"` (or `email`), `inputMode="email"`.
  - Password: `type="password"`, `name="password"`, `autoComplete="current-password"`.

3) **Error message always visible and not announced on change**
- Current: always rendered red text.
- Impact: confusing, and not reliably announced at the right time.
- Fix:
  - Render error only on failed submit.
  - Add `role="alert"` (or `aria-live="polite"`) so it’s announced.

4) **Error not tied to fields + color-only risk**
- Current: red text alone; no `aria-invalid` / `aria-describedby`.
- Fix:
  - Form-level error uses text prefixed with “Error:” (non-color cue) and `role="alert"`.
  - Mark relevant fields `aria-invalid="true"` when error shown.
  - Optionally connect fields to error via `aria-describedby="login-error"` (small, high-value change).

5) **Focus-visible not guaranteed**
- Risk: if global CSS removes outlines, current inline styles provide no replacement.
- Fix: require Nimbus focus behavior:
  - `Button` focus ring: 2px `color.accent.default` at 2px offset (per `DESIGN.md`).
  - `Input` must also show a visible focus indicator meeting 3:1 non-text contrast.

---

## 2) Corrected on-system design spec (buildable)

### Overview
A compact login form surface for signing into Nimbus. Primary task: enter credentials and submit. **Single primary action**: “Sign in”.

### Layout & structure
- Container: a surface card on the app canvas.
- Content order (top → bottom):
  1. Email field
  2. Password field
  3. Conditional form error message
  4. Primary submit button
- Spacing (all on Nimbus scale):
  - Container padding: `space.4`
  - Vertical gap between each block: `space.3`

### Visual tokens (use by name)
- Container
  - Background: `color.bg.surface`
  - Border: 1px `color.border.subtle` (optional; only if other surfaces use bordered cards)
  - Radius: `radius.md`
- Text
  - Body/inputs: `color.text.primary`
  - Labels/help: `color.text.secondary`
  - Error: `color.danger.default`
- Focus
  - Focus ring: 2px `color.accent.default` with 2px offset (explicitly documented for `Button`; apply same focus-visible standard to Inputs)

### Components (Nimbus)

#### Email
- Component: `Input`
- Label: `"Email"` (visible)
- Attributes:
  - `id="login-email"`
  - `type="email"`
  - `name="email"`
  - `autoComplete="username"` (allowed alternative: `email`)
  - `inputMode="email"`
  - `required`

#### Password
- Component: `Input`
- Label: `"Password"`
- Attributes:
  - `id="login-password"`
  - `type="password"`
  - `name="password"`
  - `autoComplete="current-password"`
  - `required`

#### Error (form-level)
Because `DESIGN.md` does not define an Alert/Callout component, implement as semantic text inside the form (do not invent a new component).
- Element: a block of text below password and above submit.
- Visuals:
  - Type: `text.sm`
  - Color: `color.danger.default`
- Semantics:
  - `id="login-error"`
  - `role="alert"`
- Copy (exact, invalid credentials): **“Error: Invalid email or password.”**
- Copy (exact, network/server): **“Error: Couldn’t sign in. Try again.”**

When error is present:
- Set on both fields (smallest consistent approach for ambiguous credential failures):
  - `aria-invalid="true"`
  - `aria-describedby="login-error"`

#### Submit
- Component: `Button(variant=primary)`
- Label: **“Sign in”**
- Attributes: `type="submit"`
- States:
  - Default
  - Hover (`color.accent.hover`)
  - Focus-visible: 2px ring `color.accent.default` at 2px offset
  - Disabled

### States

1) **Idle (default)**
- No error shown.
- Inputs enabled.
- Button enabled.

2) **Submitting (loading)**
- Inputs disabled.
- Button disabled.
- If the Nimbus `Button` supports a loading state, use it; otherwise label changes to **“Signing in…”** while preserving button width.

3) **Error**
- Show error block (`role="alert"`).
- Preserve email value.
- Apply `aria-invalid` + `aria-describedby` as above.

4) **Success**
- On success, proceed to the next surface (out of scope). Ensure no lingering error state.

### Interaction & keyboard
- Tab order follows DOM/visual order: Email → Password → Sign in.
- Enter submits from either field.
- No custom key bindings required (native form behavior).

### Accessibility requirements (WCAG AA)
- Contrast:
  - Normal text must be ≥ 4.5:1 vs `color.bg.surface`.
  - Focus ring / input borders that convey state must be ≥ 3:1.
- Programmatic names:
  - Inputs must be labeled via associated `<label for>` + `id` (handled by `Input` component).
- Error communication:
  - Error message is text + `role="alert"` (not color-only).
  - Fields are marked invalid and reference the error via `aria-describedby`.
- Focus visibility:
  - Do not remove outlines; ensure `:focus-visible` rings are present on all interactive controls.

### System gaps / escalation notes
- `DESIGN.md` documents `Button` focus ring but does not explicitly document `Input` focus styling; requirement above should be verified against the actual Nimbus Input implementation. If Input lacks a compliant focus indicator, escalate to design-system owner rather than inventing a one-off style.
