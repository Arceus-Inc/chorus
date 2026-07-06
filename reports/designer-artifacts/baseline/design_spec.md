# Account Settings — Design Spec (Nimbus)

## Overview
Account Settings lets a signed-in user view and update their account details. It contains three sections:
1) **Profile** (identity + contact), 2) **Password** (credential change), and 3) **Danger Zone** (delete account).

Primary tasks:
- Update profile details with clear validation and save feedback.
- Change password with strong, explicit requirements.
- Delete the account via a deliberate, confirmed destructive flow.

Primary action per section (not per page):
- Profile: **Save changes**
- Password: **Update password**
- Danger Zone: **Delete account** (destructive)

---

## Tokens
Use Nimbus semantic tokens only (no raw hex/px in this spec). When a visual detail is only defined inside a component style rule (e.g., button height, focus ring), the implementation must rely on the component’s built-in styling from `DESIGN.md` rather than re-specifying raw values.

**Color** (from `DESIGN.md`)
- Page background: `color.bg.canvas`
- Section surfaces (cards/panels): `color.bg.surface`
- Raised surfaces (dialogs/menus): `color.bg.raised`
- Dividers / borders: `color.border.subtle`
- Primary text: `color.text.primary`
- Secondary/help text: `color.text.secondary`
- Primary action emphasis: `color.accent.default`, hover `color.accent.hover`
- Destructive emphasis: `color.danger.default`
- Success feedback: `color.success.default`

**Spacing** (from `DESIGN.md`)
- Use `space.1`, `space.2`, `space.3`, `space.4`, `space.6`, `space.8` for all padding, gaps, and section separation.
- Grid and gutters follow system layout rules (12-column grid; gutter `space.6`).

**Typography** (from `DESIGN.md`)
- Type scale: `text.xs`, `text.sm`, `text.md`, `text.lg`, `text.xl`
- Font family: Inter for UI text.

**Notes / guardrails**
- Do not introduce non-existent tokens like `shadow.*` or `radius.*` in this spec. Depth/elevation and radii are provided by Nimbus components.
- Do not hardcode raw pixel values. Where a 1px/2px line or ring exists, it is part of the component styling rules and must not be specified as a raw value here.

---

## Components
All UI is composed from Nimbus system components as named in `DESIGN.md`. Variants listed are restricted to those defined by the system.

### Page structure
- **Page container**: use app default page layout on `color.bg.canvas`.
- **Section panels**: use surface containers styled with `color.bg.surface` and `color.border.subtle` (implementation: whichever Nimbus surface/panel pattern the app uses; no new container component is introduced).
- **Section headings**: text styled with `color.text.primary` using `text.lg` or `text.xl` per hierarchy.
- **Section descriptions/help text**: `color.text.secondary` with `text.sm`.

### Forms
- **Input** (system component)
  - Usage: all text/email/password fields.
  - Label: visible label above input (Nimbus Input rule).
  - States: default, focus, disabled, error.
- **Button** (system component)
  - Variants: `primary`, `secondary`, `ghost`, `danger`.
  - Usage rules:
    - Form primary submission uses `Button(variant=primary)`.
    - Safe cancel uses `Button(variant=secondary)`.
    - Destructive action uses `Button(variant=danger)`.
    - Tertiary links (if any) use `Button(variant=ghost)`.
- **Badge** (system component)
  - Usage: small inline status indicators (e.g., “Saved”, “Error”) when needed.
  - Semantic color roles only.

### Dialogs
Nimbus `DESIGN.md` does not explicitly enumerate a Dialog/Modal component. Use the product’s existing dialog implementation styled as a **raised surface** with `color.bg.raised` and Nimbus focus/keyboard requirements (see **Accessibility**). If the codebase has a named `Dialog`/`Modal` component, use it; do not invent a new component API.

---

## Layout & content
### Navigation context
Account Settings appears within the standard Nimbus app shell (left nav present above breakpoint `md`; collapses below `md` per `DESIGN.md`).

### Content hierarchy
Within the main content column:
1) Profile
2) Password
3) Danger Zone (visually separated and clearly labeled)

Use `space.*` tokens to separate sections; keep one primary action per section.

---

## Profile section
### Fields
Use `Input` components with visible labels:
- **Name**
  - Label: “Name”
  - Placeholder: “Your name”
  - Required.
- **Email**
  - Label: “Email”
  - Placeholder: “name@company.com”
  - Required.
  - Input type: email.

### Actions
- Default state (no changes):
  - Show `Button(variant=primary)` label “Save changes” disabled until form becomes dirty.
  - Show `Button(variant=secondary)` label “Cancel” disabled until form becomes dirty.
- Dirty state (user changed something):
  - Enable “Save changes” and “Cancel”.
- Cancel behavior:
  - Revert fields to last saved values.
  - Clear validation errors.
  - Return focus to the first field (“Name”).

### Validation (inline)
Validate on blur and on submit.
- Name:
  - Required.
  - Error copy: “Enter your name.”
- Email:
  - Required.
  - Must be a valid email format.
  - Error copy (required): “Enter your email address.”
  - Error copy (format): “Enter a valid email address.”

### Save behavior
- Clicking “Save changes” submits the profile form.
- On submit, disable inputs and buttons and show in-progress state per **States**.

---

## Password section
### Fields
All fields use `Input` with password type and visible labels:
- **Current password**
  - Label: “Current password”
  - Required.
- **New password**
  - Label: “New password”
  - Required.
- **Confirm new password**
  - Label: “Confirm new password”
  - Required.

### Actions
- `Button(variant=primary)` label “Update password”
- `Button(variant=secondary)` label “Cancel”
  - Cancel clears the three password fields.
  - Cancel clears validation errors.
  - Return focus to “Current password”.

### Validation rules (inline)
Validate on blur and on submit:
- All fields required.
  - Error copy: “This field is required.”
- New password minimum requirements (product rule; if backend enforces additional rules, surface backend message):
  - At least 8 characters.
  - Error copy: “Password must be at least 8 characters.”
- Confirm password must match new password:
  - Error copy: “Passwords do not match.”
- If current password is incorrect (backend response):
  - Error copy (field-level if possible on current password): “Current password is incorrect.”

### Success messaging
On successful password update:
- Clear all password fields.
- Show a success confirmation in the section (e.g., `Badge` using success semantic role) with copy: “Password updated.”

---

## Danger Zone section (Delete account)
### Section presentation
- Title: “Danger Zone”
- Description text in `color.text.secondary`:
  - “Deleting your account is permanent. Your data will be removed and you will be signed out.”
- Primary action in this section is the destructive action:
  - `Button(variant=danger)` label “Delete account”

### Delete flow (confirmation dialog)
On click “Delete account”, open a confirmation dialog (raised surface on `color.bg.raised`).

**Dialog content**
- Title: “Delete account?”
- Body copy:
  - “This can’t be undone. This will permanently delete your account.”
- Actions:
  - Primary (destructive): `Button(variant=danger)` label “Delete account”
  - Secondary (safe): `Button(variant=secondary)` label “Cancel”

**Optional extra guard (allowed without new components):**
If product requires extra confirmation, add a single `Input` inside the dialog:
- Label: “Type DELETE to confirm”
- Validation:
  - Must equal “DELETE”.
  - Error copy: “Type DELETE to confirm.”
- Disable destructive button until the confirmation input is valid.

**After confirm**
- On destructive confirm, start deletion request.
- Dialog stays open in submitting state until success/error.

---

## States
Define states for (1) page data load, (2) profile update, (3) password update, (4) delete account.

### 1) Page-level (initial load)
- **Loading**
  - Show section panels in loading state (implementation may use skeletons consistent with Nimbus; do not invent new tokens).
  - Inputs disabled.
  - Buttons disabled.
- **Loaded (happy path)**
  - Profile inputs pre-filled from current user.
  - Password fields empty.
- **Error (failed to load account)**
  - Show inline error message at top of content area:
    - Title: “Couldn’t load account settings.”
    - Body: “Check your connection and try again.”
  - Provide `Button(variant=secondary)` label “Retry”.

### 2) Profile form
- **Initial/unchanged**
  - Save/Cancel disabled.
- **Dirty**
  - Save/Cancel enabled.
- **Saving/submitting**
  - Disable `Input`s and buttons in the Profile section.
  - “Save changes” shows in-progress affordance (use Nimbus button loading styling if available).
- **Success**
  - Show inline success status: “Saved.” (use `Badge` with success semantic role if implemented; otherwise plain text in `color.success.default`).
  - Keep Save/Cancel disabled (not dirty).
- **Error (save failed)**
  - Keep user-entered values.
  - Show inline section error text: “Couldn’t save changes. Try again.”
  - If backend provides field-specific errors (e.g., email already in use), show them inline on the relevant field.

### 3) Password form
- **Initial/empty**
  - Fields empty.
  - “Update password” disabled until all required fields are non-empty.
- **Submitting**
  - Disable password inputs and buttons.
  - Button shows in-progress affordance.
- **Success**
  - Clear all fields.
  - Show “Password updated.”
- **Error (submit failed)**
  - If current password incorrect: show on Current password field.
  - Otherwise show section-level error: “Couldn’t update password. Try again.”

### 4) Delete account
- **Dialog open (idle)**
  - Cancel enabled.
  - Destructive confirm enabled only if optional confirmation input (if present) is valid.
- **Dialog submitting**
  - Disable dialog inputs and both buttons.
  - Keep focus trapped in the dialog.
- **Dialog error**
  - Keep dialog open.
  - Show error copy inside dialog: “Couldn’t delete your account. Try again.”
  - Re-enable Cancel and Delete.
- **Success**
  - Close dialog.
  - Proceed to sign-out / redirect flow handled by app (out of scope for this page UI), but the initiating UI must not leave the user on a stale settings screen.

---

## Accessibility
All requirements target WCAG 2.1 AA.

### Keyboard & focus (page)
- Tab order follows visual order:
  1) Profile: Name → Email → Save changes → Cancel
  2) Password: Current password → New password → Confirm new password → Update password → Cancel
  3) Danger Zone: Delete account
- When a section enters a submitting state, focus remains on the initiating button; do not move focus unexpectedly.
- When validation fails on submit:
  - Move focus to the first invalid field in that section.
  - Ensure an error summary is not required; field-level errors are sufficient, but must be announced (see ARIA).

### Keyboard & focus (delete confirmation dialog)
- The dialog must trap focus while open.
- Initial focus:
  - If the optional confirmation `Input` is present, initial focus is that input.
  - Otherwise initial focus is the safe action: “Cancel” (`Button(variant=secondary)`), so users don’t accidentally confirm.
- Escape key closes the dialog and returns focus to the “Delete account” button.
- Closing via Cancel returns focus to the “Delete account” button.

### ARIA, roles, names, and descriptions
- Each `Input` must have a programmatic label matching the visible label.
- Inline error text must be associated to the field using `aria-describedby` (or equivalent) and the field must reflect invalid state (e.g., `aria-invalid=true`).
- The delete confirmation dialog must use:
  - `role="dialog"` (or `alertdialog` only if it blocks and demands immediate attention)
  - `aria-modal="true"`
  - An accessible name via `aria-labelledby` referencing the dialog title.
  - `aria-describedby` referencing the dialog body copy and any inline error message.

### Contrast & non-color state cues
- Text must use Nimbus text tokens on Nimbus background tokens:
  - Primary content: `color.text.primary` on `color.bg.canvas` / `color.bg.surface`.
  - Secondary/help text: `color.text.secondary` on `color.bg.canvas` / `color.bg.surface`.
- Interactive focus indication relies on Nimbus component focus ring (defined in `DESIGN.md` as accent focus treatment); ensure it remains visible on `color.bg.surface` and `color.bg.raised`.
- Error states must not rely on color alone:
  - Always show an explicit error message string (e.g., “Enter a valid email address.”).
  - Mark fields as invalid via component error state and ARIA.
- Destructive actions must be communicated by both:
  - `Button(variant=danger)` styling, and
  - explicit copy (“Delete account”, “This can’t be undone.”).

### Touch targets
- Use Nimbus `Button` and `Input` components which enforce minimum touch target sizing through component styling rules.

### Reduced motion
- No motion is required. If the dialog animates, it must respect user reduced-motion preferences (implementation detail; do not add custom animation).
