---
name: web-research
description: How to research a question on the open web and produce a claim set every fact of which is traceable to a source. Covers query strategy, reading a source in full, triangulating across independent sources, distinguishing primary from secondary, checking recency, and citing exact URLs. Use whenever the answer is not in local data.
when_to_use: Use when a question needs current or external information you don't have locally — market/landscape questions, "what is the state of the art", facts about tools/companies/events. Skip when the answer is fully derivable from local data.
---

# Web research

The output of good web research is a set of claims, each traceable to a source you actually read. The
failure mode is asserting from memory and decorating it with a plausible-looking link. This skill is
the discipline that prevents that.

## When NOT to use this
- The answer is in local data — use `sql-investigation` / `exploratory-data-analysis`.
- The question is a matter of reasoning, not fact-finding.

## Method

### 1. Decompose into factual sub-questions
Break the ask into the specific facts you must establish. Research each; don't try to answer the whole
thing from one search.

### 2. Search broad, then narrow
Start with a broad query, read what comes back, then issue sharper follow-ups using the vocabulary the
good sources used. Prefer authoritative and primary sources (official docs, the project/company
itself, the original paper, filings) over aggregators and SEO content.

### 3. Read the source, don't skim the snippet
A search snippet is a lead, not evidence. Open the promising source and read it in full. When a tool
result says the output was truncated and saved to a file, read that full payload with `read_offloaded`
(not `read_file`) — never re-run the same search/extract to recover content you already fetched.

### 4. Triangulate
Confirm every load-bearing fact from **at least two independent sources**. If two credible sources
disagree, report the disagreement rather than silently picking one. A single source is a single point
of failure.

### 5. Primary vs secondary, and recency
Distinguish what a source *originated* from what it *repeats*. Trace a claim to its origin when it
matters. Check the date — a "current" claim from a stale page is not current; note the as-of date and
never assert a date you didn't verify (and never a future one).

### 6. Cite exactly
Attach the exact source URL to every fact — a number or name with no source is not acceptable. Judge a
citation by whether it *supports the claim*, not by its format (an API endpoint, a raw file, a docs
page, and an HTML page are all valid if they contain the fact).

## Common failure modes
- Asserting from prior knowledge and attaching a link that doesn't actually contain the claim.
- Trusting a snippet without opening the page.
- Re-running the same extract instead of reading the offloaded full output.
- One-source claims presented as settled fact.
- Quoting a stale page as current, or inventing an as-of date.

## Cross-references
- `findings-communication` — structure the cited claims answer-first.
- `statistical-rigor` — external numbers still need `n` and context before you trust them.
- `metric-definition-and-benchmarks` — a benchmark you found describes a population, not a target.
