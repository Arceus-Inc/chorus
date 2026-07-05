# Vendored exemplar DESIGN.md library

This directory vendors the **[awesome-design-md](https://github.com/VoltAgent/awesome-design-md)**
collection by **VoltAgent** — 58 real-world `DESIGN.md` design-system documents extracted from
developer-facing product websites (Stripe, Linear, Vercel, Notion, Figma, Apple, …).

The Designer employee uses these as **reference exemplars**: worked examples of the canonical
[Stitch `DESIGN.md` format](https://stitch.withgoogle.com/docs/design-md/format/) that show, in
concrete detail, how top product teams codify color, type, components, spacing, elevation, and
do/don't guardrails into a single markdown file an agent can read. The `design-md-exemplars` skill
indexes them and explains how to consult one when authoring or extending a project's own `DESIGN.md`.

## What was vendored

- Only the `DESIGN.md` files (one per company, under `<company>/DESIGN.md`). The upstream
  `preview.html` / `preview-dark.html` catalogs and per-company `README.md` files were **not**
  vendored — they aren't needed for the Designer's reference use and would bloat the package.

## Provenance & license

- **Source**: https://github.com/VoltAgent/awesome-design-md
- **Copyright**: © 2026 VoltAgent
- **License**: MIT (see [`LICENSE`](LICENSE) in this directory).

These files are **exemplars to learn from, not assets to copy verbatim**. When the Designer authors a
project's `DESIGN.md`, it borrows the *structure* and *rigor* of these examples and adapts the specifics
to the project's real brand and system — it never lifts another company's palette, type, or voice.
