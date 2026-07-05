# Relay first-run onboarding — design_spec

## 0) Overview
This spec defines Relay’s first-run onboarding flow with **exactly three steps**:
1) **Connect a source** → 2) **Send a test event** → 3) **See it arrive**.

Design is built strictly on the Relay design system in `DESIGN.md` (tokens + components). All values below reference those token/component names.

---

## Tokens & components used

### Tokens (by namespace)
- Color: `color.bg.app`, `color.bg.surface`, `color.bg.raised`, `color.bg.code`, `color.text.primary`, `color.text.secondary`, `color.text.muted`, `color.border.subtle`, `color.border.strong`, `color.accent.bg`, `color.accent.hover`, `color.accent.fg`, `color.success.fg`, `color.success.bg`, `color.danger.fg`, `color.danger.bg`, `color.warning.fg`, `color.warning.bg`, `color.info.fg`, `color.info.bg`, `color.focus.ring`
- Type: `type.family.sans`, `type.family.mono`, `type.size.12`, `type.size.14`, `type.size.16`, `type.size.18`, `type.size.20`, `type.size.24`, `type.line.16`, `type.line.20`, `type.line.24`, `type.line.28`, `type.line.32`, `type.weight.regular`, `type.weight.medium`, `type.weight.semibold`
- Space: `space.2`, `space.3`, `space.4`, `space.6`, `space.8`, `space.10`, `space.12`
- Radius: `radius.2`, `radius.round`
- Elevation: `elevation.1`, `elevation.2`, `elevation.3`
- Size: `size.control.md`, `size.control.lg`, `size.icon.sm`, `size.icon.md`
- Motion: `motion.duration.fast`, `motion.duration.normal`, `motion.easing.standard`
- Z: `z.popover`, `z.modal`

### Components
- `Stepper(steps, currentStepId, onStepChange, orientation)`
- `Panel(title?, description?, children, footer?)`
- `TextInput(id, label, value, onChange, placeholder?, helpText?, errorText?, required?, disabled?)`
- `Combobox(id, label, value, onChange, options, placeholder?, helpText?, errorText?, required?)`
- `RadioGroup(id, label, value, onChange, options, helpText?, errorText?)`
- `Button(label, onPress, variant, size, leadingIcon?, trailingIcon?, disabled?, loading?)`
- `Alert(variant, title?, description, actionLabel?, onAction?)`
- `CodeBlock(code, language?, copyActionLabel?)`
- `Link(label, href)`

---

## 1) Screen structure (all steps)

### Page layout
- Background: `color.bg.app`.
- Main content container on `color.bg.surface` with page padding `space.6` (wide) / `space.4` (narrow).
- Top-of-page: Page title “Get started” using `type.size.20` + `type.line.28` + `type.weight.semibold` with `color.text.primary`.
- Below title: `Stepper`.
- Step content lives inside a `Panel` using `color.bg.raised`, border `color.border.subtle`, radius `radius.2`, elevation `elevation.1`, padding `space.6`.

### Navigation + Stepper behavior

#### Chosen pattern (unambiguous, conventional)
Implement `Stepper` using the **WAI-ARIA Tabs pattern** so keyboard behavior is predictable.
- Stepper acts as `role="tablist"`.
- Steps are `role="tab"`.
- Step panels are `role="tabpanel"`.

#### Stepper states (gating)
- Each step has status: `complete | current | locked`.
- `complete` and `current` steps are operable.
- `locked` steps are not operable until prerequisites are met.

#### ARIA requirements
- Stepper container: `role="tablist"` and `aria-label="Onboarding steps"`.
- Each step tab:
  - `role="tab"`
  - `aria-selected=true` on the current step
  - `aria-controls` referencing its `tabpanel`
  - `id` referenced by the `tabpanel`’s `aria-labelledby`
  - Accessible name includes step number/total + label + status (e.g., “Step 2 of 3: Send test event — locked”).
- Each step panel:
  - `role="tabpanel"`
  - `aria-labelledby` referencing its tab

#### Keyboard interaction (Tabs pattern)
- Tab/Shift+Tab: moves focus into/out of the tablist and through the active tabpanel’s controls.
- Within the tablist (roving tabindex):
  - ArrowLeft/ArrowRight moves focus between **enabled** tabs.
  - Home/End moves to first/last **enabled** tab.
  - Enter/Space activates the focused tab (sets it selected).
- Disabled/locked steps:
  - Use native `disabled` if tabs are rendered as `button`.
  - If using non-native tab elements, use `aria-disabled="true"` and ensure locked tabs are **not reachable** via arrow navigation and are removed from roving sequence.

#### Focus management
- On tab activation (step change): programmatically move focus to the step panel title (H2) via `tabindex="-1"` to announce context.

#### Back/Continue controls
- Back: `Button(variant=secondary, size=md, label="Back")` (hidden/disabled on first step)
- Continue: `Button(variant=primary, size=md, label="Continue")`

#### “Blocked” (can’t continue) pattern
When Continue is disabled, show a persistent requirements list above the footer:
- `Alert(variant=info, title="To continue", description=...)` with bullets of unmet requirements.

---

## 2) Step 1 — Connect a source

### Purpose
User selects a source type and provides connection details.

### UI content (within `Panel`)
- Panel title (H2): “Connect your source” (`type.size.18` + `type.line.28` + `type.weight.semibold`).
- Description (`type.size.14` + `type.line.20`, `color.text.secondary`): “Choose how you’ll send events to Relay. You can change this later.”

#### Fields
1) `Combobox(id="sourceType", label="Source type", required=true, placeholder="Select a source type")`
2) `TextInput(id="sourceName", label="Source name", required=true, placeholder="e.g., Payments webhook")`
3) `RadioGroup(id="authMethod", label="Authentication", options=["No auth", "Shared secret"], value=...)`
   - If “Shared secret”: `TextInput(id="sharedSecret", label="Shared secret", required=true, placeholder="Paste or generate a secret")`

#### Actions
- Primary: `Button(variant=primary, label="Continue", size=md)`
- Secondary: `Button(variant=ghost, label="Skip for now", size=md)`

### States (loading/empty/success/error)
**Empty (initial):**
- `Alert(variant=info, title="To continue", description="• Select a source type\n• Enter a source name")`.
- Continue disabled.

**Loading:**
- If source types are fetched: combobox container sets `aria-busy=true`.
- On save: Continue shows `loading=true`.

**Success:**
- `Alert(variant=success, title="Source connected", description="Next, send a test event.")`.
- Mark Step 1 `complete` and unlock Step 2.

**Error:**
- Save fails: `Alert(variant=danger, title="Couldn’t save source", description="Check your connection and try again.")`.
- Error microcopy example (field-level):
  - `TextInput(id="sourceName").errorText = "Enter a source name to continue."`

---

## 3) Step 2 — Send a test event

### Purpose
User sends a test event and Relay confirms receipt.

### UI content
- Panel title (H2): “Send a test event”
- Description (`color.text.secondary`): “Copy the sample payload and send it to your Relay endpoint.”

#### Sections
1) Endpoint: `CodeBlock(language="text", copyActionLabel="Copy endpoint")`
2) Payload: `CodeBlock(language="json", copyActionLabel="Copy payload")`
3) Method selector: `RadioGroup(id="sendMethod", label="Send using", options=["curl", "Your code"], value=...)`
   - If “curl”: `CodeBlock(language="bash", copyActionLabel="Copy curl command")`

#### Actions
- Primary: `Button(variant=primary, label="I sent the event", size=md)`
- Secondary: `Button(variant=secondary, label="Regenerate payload", size=md)`

### States (loading/empty/success/error)
**Empty (initial):**
- `Alert(variant=info, title="Waiting for your test event", description="Send the event, then click “I sent the event”.")`.

**Loading:**
- After clicking “I sent the event”, poll for receipt:
  - Results region uses `aria-busy=true`.
  - Primary button shows `loading=true`.

**Success:**
- `Alert(variant=success, title="Test event received", description="Nice — Relay is receiving events from this source.")`.
- Mark Step 2 `complete` and unlock Step 3.

**Error:**
- Polling timeout (microcopy): `Alert(variant=danger, title="No event received yet", description="We didn’t see an event. Check the endpoint URL and try again.")`.

---

## 4) Step 3 — See it arrive

### Purpose
User inspects the received event payload.

### UI content
- Panel title (H2): “See it arrive”
- Description (`color.text.secondary`): “Verify the event shows up and inspect the payload.”

#### Event view
- Summary row: “Event received” with icon + text.
- `CodeBlock(language="json", copyActionLabel="Copy event JSON")`.
- Exit: `Link(label="View in Events", href=...)`.

#### Actions
- Primary: `Button(variant=primary, label="Finish setup", size=md)`
- Secondary: `Button(variant=secondary, label="Send another test event", size=md)`

### States (loading/empty/success/error)
**Empty (initial):**
- `Alert(variant=info, title="No event to show", description="Send a test event to see it appear here.")`.
- Primary action becomes: `Button(variant=primary, label="Go to “Send test event”", size=md)`.

**Loading:**
- Event fetch in progress: event region `aria-busy=true` and show a code placeholder.

**Success:**
- `Alert(variant=success, title="You’re all set", description="Relay is receiving events and you can inspect them anytime.")`.

**Error:**
- Fetch fails (microcopy): `Alert(variant=danger, title="Couldn’t load the event", description="Try again, or send another test event.")`.

---

## Responsive layout

### Narrow breakpoint (≤ 640px)
- Stepper: `orientation=vertical`.
- Panel padding: `space.4`.
- Code blocks: horizontal scroll **inside code area only** (`overflow-x:auto`); the page must not horizontally scroll.
- Footer buttons stack vertically with gap `space.3`.

### Wide breakpoint (≥ 1024px)
- Stepper: `orientation=horizontal`.
- Optional two-column inside Step 2: left column instructions/code, right column status; gap `space.6`.

---

## Accessibility (ARIA/keyboard/focus/contrast)

### Landmarks & headings
- One H1: “Get started”. Step titles are H2.
- Main container uses `role="main"`.

### Stepper/navigation controls (ARIA + keyboard)
- Use Tabs ARIA pattern:
  - Container `role="tablist"` + `aria-label="Onboarding steps"`.
  - Step triggers `role="tab"` + `aria-controls`.
  - Panels `role="tabpanel"` + `aria-labelledby`.
- Locked steps use native `disabled` (or `aria-disabled=true`) and are removed from the roving sequence.

### Form fields (labels, descriptions, errors)
- Visible labels for all fields.
- Required fields use native `required`.
- On error:
  - `aria-invalid=true` on the field.
  - Error text wired with `aria-describedby`.
- Alerts:
  - `role="status"` for info/success.
  - `role="alert"` for danger.

### Combobox ARIA pattern
- Input: `role="combobox"`, `aria-expanded`, `aria-controls`.
- Popup: `role="listbox"`; options: `role="option"`.
- Active option: `aria-activedescendant`.

### CodeBlock copy button
- Copy action is a named `button` (from `copyActionLabel`).
- After copy, announce via `role="status"`: “Copied to clipboard”.

### Focus management between steps
- On step change (tab activation/back/continue): move focus to the destination step H2 (`tabindex="-1"`).

### Contrast ensured via tokens
- Normal text uses `color.text.primary`/`color.text.secondary` on `color.bg.surface`/`color.bg.raised` and meets **≥ 4.5:1**.
- Focus indicator uses `color.focus.ring` and meets **≥ 3:1**.
- Use `color.border.strong` where borders are the only control boundary to meet **≥ 3:1**.

### Accessibility checklist
- Touch targets: **44×44px minimum**; use `size.control.lg` where needed.
- Focus-visible: visible ring using `color.focus.ring`.
- Keyboard: operable without traps; no `tabindex>0`.
- Reduced motion: honor `prefers-reduced-motion: reduce`.
- Dialogs: none required; if added later, must trap focus, close on Esc, restore focus.

---

## Open system gap (explicit)
- v0 `DESIGN.md` does not define a separate `Tabs` component. This onboarding uses the `Stepper` component (implemented with the Tabs ARIA pattern) for step navigation, and uses `RadioGroup` for “Send using”.
