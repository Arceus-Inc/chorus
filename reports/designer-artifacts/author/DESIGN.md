# Theme

Relay is a developer-facing product for getting events from a source into Relay, then verifying they arrive as expected. The UI should feel **precise, calm, and technical**: clear hierarchy, restrained color, and strong affordances.

**House style (exemplar fit):** closest to **Linear + Vercel**: dense-but-legible layouts, neutral surfaces, one clear primary action per step, and a single accent used sparingly for progress and success. The intent is to reduce anxiety during first-run setup—users should always know “what step am I on” and “what do I do next”.

**Design principles**
- **Guided, not gated:** users can move forward when ready, but each step shows what is required.
- **Explain, then act:** instructions appear above controls; code samples are copyable.
- **Status is explicit:** state is shown with labels + icons, not color alone.

---

# Foundations/Tokens

Tokens are the single source of truth. Specs reference token names (never raw hex/px) unless explicitly documented as an exception.

## Token namespaces
- `color.*` — semantic colors
- `type.*` — typography ramp
- `space.*` — spacing scale
- `radius.*` — corner rounding
- `elevation.*` — shadows
- `size.*` — control heights / icon sizes
- `motion.*` — durations + easing
- `z.*` — layering

## Spacing tokens (`space.*`) — explicit scale
Base unit is 4px; use only the steps below.
- `space.0` = 0
- `space.1` = 4
- `space.2` = 8
- `space.3` = 12
- `space.4` = 16
- `space.5` = 20
- `space.6` = 24
- `space.8` = 32
- `space.10` = 40
- `space.12` = 48
- `space.16` = 64

## Radius tokens (`radius.*`)
- `radius.1` (subtle)
- `radius.2` (default)
- `radius.3` (emphasized)
- `radius.round` (pill)

## Elevation tokens (`elevation.*`)
- `elevation.0` (none)
- `elevation.1` (raised panel)
- `elevation.2` (popover)
- `elevation.3` (modal)

## Size tokens (`size.*`)
- `size.control.sm` (32px height)
- `size.control.md` (40px height, default)
- `size.control.lg` (48px height)
- `size.icon.sm` (16)
- `size.icon.md` (20)

## Motion tokens (`motion.*`)
- `motion.duration.fast` (120ms)
- `motion.duration.normal` (180ms)
- `motion.duration.slow` (240ms)
- `motion.easing.standard` (ease-out)

## Z-index tokens (`z.*`)
- `z.base`
- `z.sticky`
- `z.popover`
- `z.modal`

---

# Typography

## Type tokens (`type.*`) — explicit ramp
Use the ramp steps below; do not set ad-hoc font sizes.
- `type.family.sans` (UI)
- `type.family.mono` (code)

- `type.size.12` / `type.line.16` (metadata)
- `type.size.14` / `type.line.20` (body default)
- `type.size.16` / `type.line.24` (dense body / form)
- `type.size.18` / `type.line.28` (section title)
- `type.size.20` / `type.line.28` (page title)
- `type.size.24` / `type.line.32` (hero, rare)

- `type.weight.regular` (400)
- `type.weight.medium` (500)
- `type.weight.semibold` (600)

## Typographic usage
- Default UI text: `type.size.14` + `type.line.20` with `type.weight.regular`.
- Page title: `type.size.20` + `type.line.28` with `type.weight.semibold`.
- Code: `type.family.mono` at `type.size.12`–`type.size.14` depending on density.

---

# Spacing & Layout

## Layout grid
- Page padding: `space.6` (desktop), `space.4` (narrow)
- Max content width: 960px (tokenized conceptually; implementation may use a layout container)
- Column gap: `space.6`

## Common patterns
- Between major sections: `space.8`
- Card/panel padding: `space.6`
- Form row gap: `space.4`
- Inline icon/text gap: `space.2`

---

# Color

All colors below are semantic tokens. Implementation may map them to a primitive palette; specs reference only these semantic names.

## Surface & text
- `color.bg.app` — app background
- `color.bg.surface` — default surface
- `color.bg.raised` — raised card/panel surface
- `color.bg.code` — code block surface

- `color.text.primary`
- `color.text.secondary`
- `color.text.muted`
- `color.text.inverse`

## Borders & dividers
- `color.border.subtle`
- `color.border.strong`

## Interactive
- `color.accent.fg` — accent text/icon
- `color.accent.bg` — accent background (buttons)
- `color.accent.hover`
- `color.focus.ring` — focus outline color (must meet 3:1 against adjacent colors)

## Status
- `color.success.fg` / `color.success.bg`
- `color.warning.fg` / `color.warning.bg`
- `color.danger.fg` / `color.danger.bg`
- `color.info.fg` / `color.info.bg`

## Color usage rules (checkable)
- Body text uses `color.text.primary` on `color.bg.surface` and must meet **≥ 4.5:1**.
- Secondary/muted text must also meet **≥ 4.5:1** for normal text; if used only for non-essential metadata, ensure it is still readable and never the only carrier of meaning.
- Focus ring uses `color.focus.ring` and must meet **≥ 3:1** (non-text contrast) against the surrounding surface.
- Borders indicating control boundaries must meet **≥ 3:1** (non-text contrast) against adjacent background.
- Status color is never the only signal: include icon + text (e.g., “Error”, “Connected”).

---

# Components

Core components required to build onboarding. Component names are normative; props/variants below form the v0 API.

## Button
`Button(label, onPress, variant, size, leadingIcon?, trailingIcon?, disabled?, loading?)`
- `variant`: `primary | secondary | ghost | danger`
- `size`: `sm | md | lg` (maps to `size.control.*`)
- Loading shows spinner + sets `aria-busy=true` and disables repeat submits.

## TextInput
`TextInput(id, label, value, onChange, placeholder?, helpText?, errorText?, required?, disabled?)`
- Always has a visible `label`.
- Error state renders `errorText` and sets `aria-invalid=true` + `aria-describedby`.

## Select / Combobox
`Combobox(id, label, value, onChange, options, placeholder?, helpText?, errorText?, required?)`
- Supports type-ahead.
- Uses listbox pattern (see Accessibility + Interaction).

## RadioGroup
`RadioGroup(id, label, value, onChange, options, helpText?, errorText?)`
- For small sets (≤6) when all options should be visible.

## Tabs / Stepper
`Stepper(steps, currentStepId, onStepChange, orientation)`
- `orientation`: `horizontal | vertical`
- Steps show: number, label, and status: `complete | current | upcoming`.
- Changing step is allowed but guarded by validation messaging (no silent loss).

## Alert
`Alert(variant, title?, description, actionLabel?, onAction?)`
- `variant`: `info | success | warning | danger`

## CodeBlock
`CodeBlock(code, language?, copyActionLabel?)`
- Copy button is required for onboarding.

## Card / Panel
`Panel(title?, description?, children, footer?)`
- Default uses `color.bg.raised` + `color.border.subtle` + `radius.2` + `elevation.1`.

## Other primitives (assumed)
- `Link(label, href)`
- `Icon(name, ariaHidden?)`
- `Divider()`

---

# Interaction

## Defaults
- One primary action per step. Secondary actions are `Button(variant=secondary|ghost)`.
- Inline validation occurs on blur; blocking validation occurs on submit.

## Keyboard interaction (normative)
- Buttons: Enter/Space activates.
- Stepper: Tab focuses the current step; Left/Right (or Up/Down in vertical) moves between steps; Enter activates the focused step.
- Combobox: follows ARIA combobox with listbox; ArrowDown opens; Arrow keys move; Enter selects; Esc closes.
- CodeBlock copy: copy button is reachable by Tab; Enter activates; announces “Copied”.

## Motion
- Transitions are subtle (use `motion.duration.normal` + `motion.easing.standard`).
- Motion must not be required to understand state; see Accessibility.

---

# Accessibility

This system targets **WCAG 2.1 AA**.

## Contrast (checkable)
- Normal text contrast: **≥ 4.5:1**.
- Large text (≥ 24px regular or ≥ 19px bold): **≥ 3:1**.
- Non-text UI (focus indicators, meaningful icons, input borders): **≥ 3:1**.

## Focus-visible (checkable)
- All focusable elements show a visible focus indicator using `color.focus.ring`.
- Use `:focus-visible` to avoid always-on outlines for pointer interaction.
- Do not remove outlines unless replaced with a ring that meets the 3:1 rule.

## Keyboard operability (checkable)
- Everything interactive is reachable via Tab and operable by keyboard.
- No keyboard traps.
- DOM order matches visual order; do not use `tabindex>0`.

## Reduced motion (checkable)
- Honor `prefers-reduced-motion: reduce`: remove non-essential transitions and disable animated progress indicators.

## Forms (checkable)
- Visible labels for all fields (no placeholder-only labeling).
- Errors are announced: `aria-invalid`, `aria-describedby`, and an error summary region when appropriate.

---

# Governance

## Change policy
- Add/rename tokens only via design review; keep semantic names stable.
- New components require documented API (props/variants) + a11y notes.

## Quality gates
- Specs must reference tokens by name.
- New UI must pass WCAG checks above.
- If the system lacks a needed pattern, the spec must flag the gap rather than inventing silently.
