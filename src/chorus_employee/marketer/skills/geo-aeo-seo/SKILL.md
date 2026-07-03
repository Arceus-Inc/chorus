---
name: geo-aeo-seo
description: How to structure content so both search engines AND generative answer engines surface and CITE it — answer-first structure, schema, entity density, citation-readiness.
when_to_use: Read when drafting owned content meant to be discovered (blog posts, landing pages, docs), and whenever you run the content/GEO-refresh routine to re-score what shipped.
---

# GEO / AEO + SEO

Discovery has two audiences now: the classic search index (SEO) and the generative answer engines
that read your page and decide whether to *cite* it (GEO/AEO — Generative/Answer Engine
Optimization). The craft overlaps but the bar is higher: an answer engine won't cite a page it can't
quickly extract a clean, sourced claim from.

## The one rule

**Make the answer extractable.** If a machine skimming your page can't lift a clear, self-contained,
attributable statement that answers a real question, you will not be cited — however good the prose.

## Answer-first structure

- **Lead with the answer, then support it.** State the takeaway in the first sentence of a section;
  put the reasoning after. Buried conclusions don't get quoted.
- **One idea per section, with a descriptive heading that reads like a question or a claim** ("How
  Arceus governs AI usage across teams" beats "Overview").
- **Self-contained paragraphs** — each should make sense lifted out of context, because that's how
  answer engines quote it.
- **Direct question→answer blocks** for the queries you want to win. A crisp Q and a 2–3 sentence A
  is the most citation-ready shape there is.

## Entity density + schema

- **Name the entities** — products, companies, standards, people — explicitly and consistently.
  Answer engines resolve pages against a knowledge graph; vague "the platform" is invisible, "Arceus"
  is a node.
- **Structured data / schema markup** (Article, FAQ, HowTo, Organization) tells engines what the
  page *is* and surfaces rich results. Recommend it even when you can only draft the content.
- **Link claims to sources.** A cited statistic with its source is both more trustworthy to a reader
  and more quotable to an engine (it inherits your citation).

## SEO fundamentals that still matter

- Match search intent (informational vs. commercial); one primary intent per page.
- Descriptive title + meta description; logical heading hierarchy; internal links to related owned
  content.
- Freshness: content decays as the category moves — a page that was current last year may now omit
  the term everyone searches.

## Scoring decay (the GEO-refresh routine)

When re-scoring shipped content, ask per page:
1. **Answer-first?** Is the takeaway extractable in the first lines, or buried?
2. **Cited?** Are claims sourced, so an answer engine can quote with attribution?
3. **Current?** Does it still name the entities/terms the category now uses?
4. **Structured?** Headings/schema that make it machine-readable?

A page failing 1–2 of these is a refresh candidate — flag it, note why, and propose the fix. It
still stages for approval like any other go-live.
