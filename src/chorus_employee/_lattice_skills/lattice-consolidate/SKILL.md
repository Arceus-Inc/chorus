---
name: lattice-consolidate
description: Promote recurring beat evidence into lattice patterns (semantic facts). Use ONLY at beat end when the gate is open — never every beat.
when_to_use: Beat end ONLY, when the beat-end notice says "Lattice gate open". Skip when gate is closed.
---

# lattice consolidate — patterns only (gate-gated)

Turn **recurring episodic evidence** into **durable patterns** (key/value facts). Expensive — only when gate opens.

## Gate

1. **≥ N new beats** since last consolidation (default 5)
2. **Cluster** of ≥ K beats share file prefix or intent (default 2)

Silent beat-end notice → gate closed → do nothing.

## Workflow

### 1. Packet

```
lattice_packet()
```

### 2. Re-read evidence

Use packet `run_id`s and hints — **slim search first, full prose per cited beat**:

```
recall(query='retry')
get_run(run_id='run_a57d754d…')
```

`recall()` returns **slim hits** (summary, intent snippet, files). `get_run(run_id)` returns **full beat prose** — call it for every `source_run_id` you cite in the proposal.

### 3. Proposal JSON

```json
{
  "employee_id": "e_be_1",
  "patterns": [
    {
      "key": "api.retry",
      "claim": "The HTTP client in src/api/client.py automatically retries failed requests. It tries up to 3 times on 429 or 503 responses, with exponential backoff between attempts (0.2s base, 30s cap).",
      "source_run_ids": ["r_done_1", "r_done_2"],
      "supersedes": null
    }
  ]
}
```

| field | use |
|---|---|
| `key` | hierarchical lowercase `api.retry` |
| `claim` | 2–3 short sentences in plain English: what we decided, when it applies, where it lives (min ~20 chars) |
| `source_run_ids` | every cited beat — rendered at retrieval; drill down with `get_run(run_id)` |
| `supersedes` | set when replacing an active pattern key |

### Claim style — write like clear documentation

Claims land in `MEMORY.md` and `lattice_context`. Write them so a teammate can read them once and understand — not dense shorthand.

| Avoid (hard to read) | Prefer (clear prose) |
|---|---|
| `"In src/api/client.py, HttpClient retries failed GET requests up to max_retries (default 3). It retries on transient HTTP responses 429 and 503, sleeping with exponential backoff (base 0.2s) capped at 30s between attempts."` | `"The HTTP client in src/api/client.py automatically retries failed requests. It tries up to 3 times when the server returns 429 (rate limit) or 503 (service unavailable). Between retries it waits with exponential backoff, starting at 0.2 seconds and never longer than 30 seconds."` |
| `"exponential backoff"` | `"HTTP retries use exponential backoff capped at 30s; see src/api/client.py for the exact policy."` |

Rules:
- Use normal sentences, not semicolon chains or parenthetical dumps.
- Spell out status codes on first mention (e.g. "429 Too Many Requests").
- Name the file path once at the end, not as the opening clause.
- Keep under ~400 characters — episodic detail stays in chorus via `source_run_ids`.

Patterns stay small; episodic prose stays in chorus. Cite real `source_run_ids` so `lattice_context` can point the agent back to ground truth.

### 4. Apply

```
lattice_apply(proposal=<json>)
```

≤10 patterns per proposal. No verbatim episodic prose.

## After apply

Next beat: `lattice_context(query)` surfaces patterns with `src:` run ids — `get_run(run_id)` for full beat prose (or `recall(query)` to search first).
