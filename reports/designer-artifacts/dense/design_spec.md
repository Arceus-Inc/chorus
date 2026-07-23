# Nimbus — Events Screen (Dense Table) — design_spec

## Overview
The **Events** screen lets developers inspect webhook delivery attempts (event records), diagnose failures, and take bulk remediation actions (**Retry**/**Delete**). The primary task is **scan + filter + sort a dense list**, then **multi-select** a set of events and run a bulk action.

This spec defines the dense table layout, sorting/filtering model, selection + bulk actions, pagination, and all required states (loading/empty/error) with explicit keyboard/focus + ARIA guidance. All visual choices use Nimbus system tokens/components from `DESIGN.md`.

---

## Components used (Nimbus)
All components and constraints below are from `DESIGN.md` unless noted.

1. **Table**
   - Use Nimbus `Table` with **sticky header** and default **row hover**.
   - System sizing constraint: `Table` rows are **44px** and header uses `color.bg.raised` with hover rows also `color.bg.raised` (`DESIGN.md` “Table: 44px rows, sticky header bg.raised, row hover bg.raised”).
   - Density requirement: this screen is “dense”, but **must not invent a smaller row height**. We achieve perceived density via column choices + truncation + typography (`text.sm`/`text.xs`) and by keeping secondary details out of the row.
   - If product requires <44px rows later: **escalate to design system** to add `Table(density=compact)`; do not hardcode.

2. **Button**
   - Variants used: `primary`, `secondary`, `ghost`, `danger` (`DESIGN.md` Button variants).
   - Size/interaction constraints: height **36px**, `radius.md`, focus ring **2px** `color.accent.default` with **2px offset** (`DESIGN.md` Button rules).

3. **Input**
   - Used for “Search” and for optional filter values (if a text filter is included).
   - Constraint: height **36px**, surface background + subtle border (`DESIGN.md` Input rules).

4. **Checkbox**
   - Used for row selection and header select-all.
   - Note: `DESIGN.md` doesn’t detail checkbox sizing; rely on Nimbus Checkbox component defaults and apply the touch-target technique in **Accessibility → Touch targets**.

5. **Select / Menu**
   - `Select` used for Status filter and page-size (if options enabled).
   - `Menu` used for per-row “More actions” (optional) and must follow ARIA menu semantics (see Accessibility).

6. **Badge**
   - Use Nimbus `Badge` (pill, `text.xs`) for Status (`DESIGN.md` “Badge: pill, text.xs, semantic color roles”).

7. **Dialog/Modal**
   - Used for **Delete confirmation**.
   - Must trap focus and return focus to invoker (see Accessibility → Dialog focus mgmt).

---

## Tokens/System (every visual decision is tokenized)
All tokens referenced are defined in `DESIGN.md`.

### Color
- App/page background: `color.bg.canvas`
- Main surface (content panel): `color.bg.surface`
- Raised surfaces (sticky header, popovers/menus): `color.bg.raised`
- Borders/dividers: `color.border.subtle`
- Primary text: `color.text.primary`
- Secondary text: `color.text.secondary`
- Primary action/focus ring: `color.accent.default` (hover: `color.accent.hover`)
- Success: `color.success.default`
- Danger: `color.danger.default`

### Typography
- UI font: `Inter`
- Technical identifiers (IDs, endpoint IDs): `JetBrains Mono` (`DESIGN.md` Typography rules)
- Type tokens: `text.xs`, `text.sm`, `text.md`
- Weights: 400 body, 500 labels, 600 headings

### Spacing / layout
- Spacing scale: `space.1`, `space.2`, `space.3`, `space.4`, `space.6`, `space.8` (`DESIGN.md`)
- Grid: 12-column, max content width 1200px, gutter `space.6` (`DESIGN.md`)

### Radius / elevation
- `radius.md` for buttons and controls (`DESIGN.md`)
- `shadow.sm` for raised surfaces only (`DESIGN.md`)

### Contrast requirements (explicit)
- Text must meet **WCAG 2.1 AA 4.5:1** minimum.
- Non-text UI (borders, icons, focus indicators) must meet **3:1**.
- Use Nimbus semantic tokens above; do not introduce custom colors.

---

## Page layout
### Overall structure
- Page background: `color.bg.canvas`.
- Content region is a single `color.bg.surface` panel.
- Top of panel:
  1) Page title + short helper text.
  2) Filter/search row.
  3) Bulk action bar (appears only when selection > 0).
  4) Table.
  5) Pagination.

### Spacing
- Panel padding: `space.6`.
- Vertical gaps between regions: `space.4`.
- Within filter row: horizontal gap `space.3` between controls.

---

## Table: dense layout specification
### Table sizing (system constraint)
- Header row height: **44px** (same system row height; Nimbus table spec only defines 44px rows; header is sticky and raised).
- Body row height: **44px** (`DESIGN.md` Table rows).
- Cell padding: use Nimbus Table default padding; if Table exposes padding tokens, set to the **smallest supported** option. If Table does not expose padding variants, **do not override**.

### Table header styling
- Sticky header background: `color.bg.raised`.
- Header text style: `text.xs`, weight 500 (label weight), color `color.text.secondary`.
- Column dividers/bottom border: `color.border.subtle`.

### Table body styling
- Primary cell text: `text.sm`, weight 400, color `color.text.primary`.
- Secondary/meta within a cell (e.g., endpoint ID under endpoint name if used): `text.xs`, color `color.text.secondary`.
- Row hover: background `color.bg.raised` (system).

### Technical identifiers
- Any displayed IDs / endpoint identifiers use font family `JetBrains Mono` and size `text.sm` (or `text.xs` for secondary) for legibility and scanability.

### Truncation rules (required)
- Default: truncate long values with ellipsis in cells that can overflow.
- Provide full value via:
  - `title` attribute on the cell text **and/or** a Tooltip pattern if Nimbus has one (not specified in `DESIGN.md`; if no Tooltip component, use `title`).
- Columns with truncation:
  - Event type/name
  - Delivery / endpoint identifier

### Column set (single definitive set)
Order and behavior (left → right):

1. **Select** (checkbox)
   - Width: minimal to fit Checkbox.
   - Header contains the header checkbox (select-all).

2. **Event** (event type/name)
   - Content: event “type” or “name” (e.g., `invoice.paid`).
   - Typography: `text.sm`, `Inter`.
   - Truncation: ellipsis; full value on hover via `title`.
   - Sortable: **Yes** (optional; see sorting list below). If sortable, uses single-column sort.

3. **Status**
   - Content: `Badge` with status label.
   - Allowed labels (example set): `Delivered`, `Retrying`, `Failed`.
   - Badge color roles:
     - Delivered → uses `color.success.default` role
     - Failed → uses `color.danger.default` role
     - Retrying/Queued → uses neutral styling with `color.text.secondary` + `color.border.subtle` (within Badge system styling)
   - Sortable: **No** (status sorting is less useful than timestamp).

4. **Timestamp**
   - Content: absolute timestamp (e.g., `2026-07-04 13:41:02Z`) or localized UI format; choose one and keep consistent.
   - Typography: `text.sm`, `Inter`.
   - Sortable: **Yes** (default sort).
   - Width guidance: wide enough to avoid truncation in primary breakpoints.

5. **Endpoint** (delivery/endpoint identifier)
   - Content: endpoint display name (if available) + endpoint ID.
   - Format:
     - Line 1: endpoint name (Inter `text.sm`) OR, if no name exists, show the ID only.
     - Line 2 (secondary): endpoint ID in `JetBrains Mono` `text.xs` in `color.text.secondary`.
   - Truncation: line 1 truncates; line 2 truncates; full values via `title`.
   - Sortable: **No**.

6. **Actions** (optional)
   - An `IconButton` or `Button(variant=ghost)` labeled “More actions”. If Nimbus has no IconButton, use `Button(variant=ghost)` with icon.
   - Opens a `Menu` with row-level actions (e.g., View details, Retry single, Delete single). This is optional because bulk actions cover the primary needs.

Additional columns are intentionally avoided to preserve density and scanability. If a future requirement demands “Attempt count” or “Latency”, add only after validating it’s a primary diagnostic need.

---

## Sorting model
### Default sort
- Default sort is **Timestamp (descending)**.

### Sortable columns (exact list)
- **Timestamp** (sortable)
- **Event** (sortable)
- All other columns are not sortable.

### Single-column sort policy
- Only **one active sort** at a time.
- Sorting a column replaces the previous sort (no multi-sort, no secondary criteria).

### Sort interaction
- Clicking a sortable header toggles order: `descending → ascending → descending`.
- Visible sort indicator:
  - Placement: right side of header label.
  - Icon: up/down chevron (Nimbus icon set).
  - Inactive state: icon hidden OR displayed with `color.text.secondary` at reduced emphasis (prefer hidden to reduce noise).
  - Active state: icon displayed in `color.text.primary`.
  - Header hover affordance: header label and icon area use `color.text.primary` on hover; maintain contrast against `color.bg.raised`.

### Keyboard operability (sorting)
- Sortable header cells must be focusable controls (e.g., `button` inside `th`).
- Keys:
  - `Tab` moves focus through sortable headers (and other interactive header controls).
  - `Enter` / `Space` activates sort toggle.
- Announce state via `aria-sort` on the `th` (`none|ascending|descending`).

---

## Filtering model
### Filter controls present (grouped)
Filters sit above the table within a labeled region:

- **Search**: `Input` with label “Search events” (matches Event type/name and Endpoint ID/name).
- **Status**: `Select` labeled “Status” with options: `Any`, `Delivered`, `Retrying`, `Failed`.
- **Time range**: `Select` labeled “Time range” with options: `Last 15 minutes`, `Last hour`, `Last 24 hours`, `Last 7 days`, `Custom…`.
  - If `Custom…` is chosen and Nimbus lacks a DateRangePicker component in `DESIGN.md`, escalate; interim: open a modal with two `Input(type=date/time)` fields using system `Input`.

### Apply model (explicit)
- Filters are **not instant**; they apply only when the user clicks **Button(variant=primary) labeled “Apply filters”**.
- Provide **Button(variant=secondary) labeled “Clear filters”**.

### Enabled/disabled rules
- “Apply filters” is **disabled** when:
  - No filter value differs from the currently applied filter set.
- “Clear filters” is **disabled** when:
  - All filters are at defaults (Search empty, Status=Any, Time range=Last 24 hours).

### What “Clear filters” resets
- Resets Search to empty.
- Resets Status to `Any`.
- Resets Time range to `Last 24 hours`.
- Resets sort back to default (Timestamp desc) **only if** sort is treated as part of the “query”; otherwise keep sort. For Nimbus Events, treat sort as part of the query: **Clear filters also resets sort**.
- Resets pagination back to page 1.

### Filter persistence (required)
- Persist the applied filter set in **URL query parameters** so refresh/share works.
  - Example: `?q=invoice&status=failed&range=24h&sort=timestamp_desc&page=1`
- On navigation away and back via browser history, restore from URL.
- On hard refresh, restore from URL.
- If URL is absent, use defaults.

---

## Selection + bulk actions
### Row selection checkboxes
- Each row has a checkbox in column 1.
- Accessible name pattern:
  - Row checkbox `aria-label="Select event {eventType} at {timestamp}"`.

### Header checkbox (select-all)
- Header checkbox selects **all rows on the current page**.
- Indeterminate rules:
  - Checked: all rows on current page selected.
  - Unchecked: none selected.
  - Indeterminate: some selected.
- Accessible name: `aria-label="Select all events on this page"`.

### Selecting all filtered results (follow-up affordance)
When the user checks the header checkbox (selects current page) and total filtered results exceed the current page size:
- Show an inline callout directly above the table (or inside the bulk bar):
  - Copy: “All {pageSize} events on this page are selected.”
  - Action link/button (ghost): “Select all {totalCount} events matching these filters”
- If user activates it, selection scope becomes **all filtered results** (across pages).
- Provide an affordance to revert scope:
  - Copy: “Selecting all {totalCount} matching events.”
  - Action: “Clear selection” (ghost) clears all selection.

### Bulk action bar
Appears when selection count > 0, above the table.
- Surface: `color.bg.raised` with `shadow.sm` (raised layer rule).
- Border: `color.border.subtle`.
- Content:
  - Left: “{N} selected” (text `text.sm`, `color.text.primary`).
  - Actions:
    - `Button(variant=secondary)` “Retry”
    - `Button(variant=danger)` “Delete”
    - `Button(variant=ghost)` “Clear selection”
- Disabled states:
  - If selection empty, bulk bar is hidden; bulk actions are not shown elsewhere.
  - If a bulk operation is in progress, disable Retry/Delete and show inline progress (see States).

### Bulk actions behavior
1) **Retry**
- No confirmation dialog.
- On success, show toast/banner: “Retried {successCount} events.”
- On partial failure, show banner: “Retried {successCount} events. {failCount} failed.” with a “View failures” action that opens a modal or expands an inline panel.

2) **Delete**
- Requires confirmation dialog.
- On success, toast/banner: “Deleted {successCount} events.”
- On partial failure, banner: “Deleted {successCount} events. {failCount} failed.” with “View failures”.

### Delete confirmation dialog (required content)
- Title: “Delete events?”
- Body: “This permanently deletes the selected events. This can’t be undone.”
- If selection scope is “all matching”: add line “You’re deleting {totalCount} events matching the current filters.”
- Buttons:
  - Primary destructive: `Button(variant=danger)` label “Delete events”
  - Secondary: `Button(variant=secondary)` label “Cancel”
- Initial focus: the **Cancel** button (safer default).

### Partial-failure presentation (required)
When Retry or Delete returns mixed results:
- Present failures in a `Dialog/Modal` titled “Some events couldn’t be {retried|deleted}”.
- Modal content:
  - Summary line: “{failCount} of {selectedCount} failed.”
  - Table/list of failed items with fields:
    - Event (event type)
    - Timestamp
    - Endpoint (ID in `JetBrains Mono`)
    - Error message (truncated to one line with `title` for full text)
  - Actions:
    - `Button(variant=primary)` “Retry failed” (for Retry flow)
    - `Button(variant=secondary)` “Close”
- If user retries failed, only those failed IDs are re-submitted.

### Post-action updates + focus
- After a successful bulk action, keep the user’s context:
  - If selection was “current page”, remain on same page unless the page becomes empty; then go to previous page.
  - Clear selection after the operation completes.
- Focus management:
  - If bulk bar remains (selection still present due to failure), move focus to the failure banner’s “View failures” button.
  - If selection is cleared, return focus to the bulk bar trigger point: the header checkbox (if still present) or the table caption.

---

## Pagination
### Page size
- Default page size: **50**.
- If Nimbus supports page-size selection, offer options: 25 / 50 / 100 via `Select` labeled “Rows per page”.
- If Nimbus pagination component is fixed-size only, keep it fixed at 50 and omit the select.

### Range display
- Format: “Showing {start}–{end} of {total} events”.
  - Typography: `text.sm`, `color.text.secondary`.

### Prev/Next rules
- `Button(variant=secondary)` “Previous” disabled on first page.
- `Button(variant=secondary)` “Next” disabled when on last page (known total).

### Unknown total count
If backend cannot provide total count:
- Display: “Showing {start}–{end} events” (no “of {total}”).
- Next is disabled only when the returned page has < pageSize items.
- Do not show “Select all {totalCount} …” affordance; instead show “Select all events matching these filters” with no count.

### Keyboard interaction
- Tab order: “Rows per page” select (if present) → Previous → Next.
- Select:
  - `Alt+Down` (or platform default) opens options.
  - Arrow keys navigate options.
  - `Enter` selects.
- Buttons:
  - `Enter`/`Space` activate.

---

## States (required)
### 1) Loading
Two loading modes are required.

**Initial page load** (no prior data rendered)
- Show skeleton table within the surface panel:
  - Sticky header visible (labels), with 8–10 skeleton rows.
- Disable filter controls and pagination.
- Copy (top-right or above table): “Loading events…”

**In-table refresh** (filters/sort/page changes while table already shows prior data)
- Keep the existing rows visible.
- Show a linear loading indicator (or subtle overlay) at top of table area.
- Disable bulk action buttons during refresh to avoid acting on stale selection.

### 2) Empty (no events yet)
Condition: API returns 0 results with default filters.
- Body copy: “No events yet.”
- Helper: “When your webhook sends events, they’ll appear here.”
- Primary action: `Button(variant=primary)` “Send test event” (if product supports; otherwise omit and use Refresh).
- Secondary action: `Button(variant=secondary)` “Refresh” (re-fetches events).
- Filters remain enabled.

### 3) Fetch error
Condition: initial fetch fails.
- Message: “We couldn’t load events.”
- Helper: “Check your connection and try again.”
- Primary action: `Button(variant=primary)` “Retry” (re-fetch).
- Secondary action: `Button(variant=secondary)` “View docs” (opens webhook troubleshooting docs) OR “Contact support” depending on product.
- If error occurs during in-table refresh, keep old data and show inline banner above table with same copy and a “Retry” action.

---

## Accessibility (WCAG 2.1 AA)
### Semantics: table
- Use semantic HTML table (`<table>`, `<thead>`, `<tbody>`, `<th scope="col">`).
- Provide a `<caption>` (visually hidden if desired) with content:
  - “Webhook events. Use filters to narrow results. Sort by Timestamp or Event.”
- Do **not** use `role=grid` unless implementing full grid keyboard model.
- Selection is conveyed via checkboxes; do not rely on `aria-selected`.

### Semantics: filter region
- Wrap filters in a region with label:
  - `role="region" aria-label="Event filters"`.
- Each control has a visible label (Input label above per `DESIGN.md` Input rule).

### Checkboxes accessible names
- Header checkbox: `aria-label="Select all events on this page"`.
- Row checkbox: `aria-label="Select event {eventType} at {timestamp}"`.

### Menu semantics (if “More actions” is used)
- Trigger button must have `aria-haspopup="menu"` and `aria-expanded`.
- Menu uses `role="menu"` and items use `role="menuitem"`.
- `Escape` closes menu and returns focus to trigger.

### Dialog focus management
- Dialog must trap focus.
- Initial focus:
  - Delete confirmation → Cancel button.
  - Failures modal → Close button (or first actionable, but ensure a safe default).
- `Escape` closes dialog.
- Return focus to the invoker (Delete button in bulk bar).

### Keyboard support (explicit)
**Tab order** (top to bottom):
1) Filters: Search → Status → Time range → Apply filters → Clear filters
2) Bulk bar actions (only when visible): Retry → Delete → Clear selection
3) Table header interactive controls: sortable headers (Event, Timestamp) and header checkbox
4) Row checkboxes (then optional row “More actions”)
5) Pagination: Rows per page (if present) → Previous → Next

**Key bindings**
- Sorting headers: `Enter`/`Space` toggles sort.
- Checkboxes: `Space` toggles.
- Bulk bar buttons: `Enter`/`Space` activates.
- Dialog: `Tab` cycles within, `Escape` closes.

### Contrast + focus indicator tokens (explicit pairs)
- Primary text on surfaces: `color.text.primary` on `color.bg.surface` / `color.bg.raised`.
- Secondary text: `color.text.secondary` on `color.bg.surface` / `color.bg.raised`.
- Table borders: `color.border.subtle` against `color.bg.surface`.
- Sort indicator:
  - Active icon: `color.text.primary` on `color.bg.raised`.
  - Inactive (if shown): `color.text.secondary` on `color.bg.raised`.
- Buttons:
  - Primary: background `color.accent.default`, hover `color.accent.hover`, text `color.text.primary`.
  - Secondary: background `color.bg.surface`, border `color.border.subtle`, text `color.text.primary`.
  - Danger: background `color.danger.default`, text `color.text.primary`.
- Focus ring: 2px `color.accent.default` with 2px offset (system Button rule); apply same focus ring token behavior to other interactive elements.

### Touch targets
- Nimbus Button/Input are 36px high (system).
- For smaller controls (Checkbox, icon-only “More actions”): ensure a minimum hit area by wrapping in a clickable container with padding from the spacing scale (e.g., add `space.2` padding around the control) while keeping visual alignment.
- If Nimbus Checkbox already meets 44x44 CSS pixels, no wrapper needed; if not, wrapper is required.

---

## Content & microcopy (exact labels)
- Page title: “Events”
- Helper text: “Inspect webhook deliveries and retry or delete events.”

Filters:
- Search label: “Search events”
- Status label: “Status”
- Time range label: “Time range”
- Apply button: “Apply filters”
- Clear button: “Clear filters”

Bulk:
- Retry: “Retry”
- Delete: “Delete”
- Clear selection: “Clear selection”

Empty:
- Title: “No events yet.”
- Body: “When your webhook sends events, they’ll appear here.”
- Primary: “Send test event”
- Secondary: “Refresh”

Error:
- Title: “We couldn’t load events.”
- Body: “Check your connection and try again.”
- Primary: “Retry”

---

## design_lint expectations checklist
- [x] No raw hex values; colors use `color.*` tokens from `DESIGN.md`.
- [x] No raw spacing values; spacing uses `space.*` tokens from `DESIGN.md`.
- [x] Typography uses `text.*` tokens and system fonts (`Inter`, `JetBrains Mono`).
- [x] Interactive elements have visible labels or explicit `aria-label` (checkboxes, menu trigger).
- [x] Required headings present: “Tokens/System”, “Components used”, “States”, “Accessibility”.

---

## Open system gaps / escalations (documented, no invention)
1) **True compact table density**: Nimbus Table is specified as 44px rows; if product requires smaller, add a Table density variant in design system rather than overriding.
2) **Date range picker**: not defined in `DESIGN.md`; if “Custom…” time range is required, design system needs an approved DateRangePicker or a standard modal pattern.
3) **Checkbox sizing**: if current Nimbus Checkbox hit area is <44x44, standardize a wrapper/hit-area pattern in the system.
