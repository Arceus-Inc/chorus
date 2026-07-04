---
name: design-md-exemplars
description: "A vendored library of 58 real-world DESIGN.md files (Stripe, Linear, Vercel, Notion, Figma, Apple, …) plus the canonical Stitch DESIGN.md format — worked examples to learn structure and rigor from when authoring or extending a project's own design system."
when_to_use: "Read when a project has no DESIGN.md and you must author one, when you're extending a thin DESIGN.md, or when someone asks for a specific feel ('make it like Linear / Stripe / Notion'). Pairs with design-system-authoring (reuse-first) and token-scale-discipline."
---

# DESIGN.md Exemplars

`DESIGN.md` is a plain-markdown design-system document that a design agent reads to generate consistent
UI — the visual counterpart to `AGENTS.md`. This skill gives you two things: the **canonical format**
every good `DESIGN.md` follows, and a **vendored library of 58 real-world exemplars** to learn from.

## The one rule

**Learn the structure, adapt the specifics — never copy an exemplar verbatim.** These files show *how*
top teams codify a system (the sections, the rigor, the level of detail). You borrow that shape and
fill it with the project's *own* brand, palette, type, and voice. Lifting Stripe's purple or Linear's
type ramp into an unrelated product is theft, not design — and it fails the moment it meets the real
brand. And when the project already has a `DESIGN.md`, that file wins; exemplars never override it.

## The canonical DESIGN.md format (9 sections)

Every exemplar follows the [Stitch `DESIGN.md` format](https://stitch.withgoogle.com/docs/design-md/format/).
When you author or extend one, produce these sections:

| # | Section | What it captures |
|---|---------|------------------|
| 1 | **Visual Theme & Atmosphere** | Mood, density, design philosophy — the feel in prose. |
| 2 | **Color Palette & Roles** | Each color: semantic name + hex + functional role (bg, text, CTA, border, state). |
| 3 | **Typography Rules** | Font families + a full hierarchy table (role · size · weight · line-height · tracking). |
| 4 | **Component Stylings** | Buttons, cards, inputs, nav — with every state (default/hover/focus/active/disabled). |
| 5 | **Layout Principles** | Spacing scale, grid, whitespace philosophy. |
| 6 | **Depth & Elevation** | Shadow system, surface hierarchy. |
| 7 | **Do's and Don'ts** | Concrete guardrails and named anti-patterns. |
| 8 | **Responsive Behavior** | Breakpoints, touch targets, collapse/reflow strategy. |
| 9 | **Agent Prompt Guide** | Quick color reference + ready-to-use prompts for generating UI. |

This maps directly onto the rest of the Designer's craft: §2–3 are `token-scale-discipline`, §4 is
`component-api-design` + `states-empty-loading-error`, §5 is `visual-hierarchy` + `information-density`,
§7 folds in the accessibility floor (`wcag-conformance`), §8 is `responsive-layout`.

## The exemplar library

The full files are vendored (MIT, © VoltAgent — see the reference `NOTICE.md`) at:

```
chorus_employee/designer/references/awesome-design-md/<company>/DESIGN.md
```

If that reference tree is reachable in your workspace, `read_file` the specific exemplar for concrete
detail. If it isn't (sandboxed run), you still have the inline catalog below, and you have `web_search`
/ `web_extract` to study the live site — or spawn the `ux_researcher` subagent. The upstream workflow
is also valid: an operator can copy a chosen exemplar into the project root as a starting `DESIGN.md`,
which you then read and adapt like any project design system.

### Catalog (58 exemplars, grouped by feel)

Pick the closest starting point to the desired atmosphere, read that file, then adapt.

- **Developer-tool / precise-minimal (often dark-first):** `linear.app`, `vercel`, `cursor`, `warp`,
  `raycast`, `sentry`, `supabase`, `clickhouse`, `mintlify`, `resend`, `opencode.ai`, `posthog`,
  `replicate`, `ollama`, `hashicorp`, `expo`, `composio`, `sanity`, `voltagent`.
- **AI / research-lab (calm, editorial, restrained accent):** `claude`, `cohere`, `mistral.ai`, `x.ai`,
  `elevenlabs`, `runwayml`, `minimax`, `together.ai`, `nvidia`, `lovable`.
- **Fintech / crypto (premium, trustworthy, dense data):** `stripe`, `coinbase`, `kraken`, `revolut`,
  `wise`.
- **Productivity / SaaS (friendly, structured, content-dense):** `notion`, `airtable`, `figma`,
  `framer`, `cal`, `intercom`, `zapier`, `superhuman`, `miro`, `webflow`, `mongodb`, `ibm`.
- **Consumer / marketplace (warm, photographic, human):** `airbnb`, `uber`, `pinterest`, `spotify`.
- **Automotive / industrial / bold-brand (dramatic, high-contrast, motion-forward):** `apple`, `tesla`,
  `bmw`, `ferrari`, `lamborghini`, `renault`, `spacex`, `clay`.

## How to use an exemplar

1. **Match the feel, not the brand.** Choose the exemplar whose *atmosphere* fits the project's goal
   (e.g. a developer tool → study `linear.app`/`vercel`; a fintech dashboard → `stripe`/`wise`).
2. **Read it for structure and rigor.** Notice how it names colors semantically, tables its type ramp,
   enumerates component states, and writes concrete do/don't rules — that's the bar for your output.
3. **Adapt, don't transplant.** Re-derive every value from the project's real brand. Keep the *shape*
   (9 sections, semantic tokens, stateful components); replace the *content*.
4. **Hold the accessibility floor regardless.** Some exemplars ship contrast that fails AA — you do not
   inherit their misses. Re-check against `wcag-conformance` and `color-contrast`.

## Before you finish

1. If you authored/extended a `DESIGN.md`, confirm all 9 sections are present and concrete (semantic
   tokens, a full type table, stateful components, real do/don't rules).
2. Confirm nothing was lifted verbatim from an exemplar — every value ties back to *this* project.
3. Confirm the result clears the accessibility floor even if the exemplar you studied didn't.
