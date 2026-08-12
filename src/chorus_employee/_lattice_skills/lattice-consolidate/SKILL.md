---
name: lattice-consolidate
description: Promote recurring beat evidence into lattice patterns (facts) and skill_manage procedures. Use ONLY at beat end when the gate is open — never every beat.
when_to_use: Beat end ONLY, when the beat-end notice or Task context Lattice wake says the gate is open. Do not run on every beat — consolidation is expensive. Skip entirely when the gate is closed.
---

# lattice consolidate — patterns + skill_manage (gate-gated)

Consolidation turns **recurring episodic evidence** into:

- **Patterns** — declarative facts (`api.retry`) → `lattice_apply` → `lattice_context`
- **Procedures** — playbooks → **`skill_manage(evolve|patch)`** on an existing role skill (default); `create` only for new class-level umbrellas

## When Task context shows Lattice wake

If the pushed Task context includes `### Lattice wake` (prior beat opened the gate), load **this skill first** before other task work, then run the workflow below.

## Gate

1. **≥ N new beats** since last consolidation (default N = 5)
2. **A cluster** of ≥ K beats share the same file prefix or intent (default K = 2)

Silent beat-end notice → gate **closed** → do nothing.

## Preference order (Hermes-aligned)

1. **`patterns[]` via `lattice_apply`** — sticky-note facts ("client retries 429/503")
2. **`skill_manage(evolve)`** — patch a section of an existing role skill
3. **`skill_manage(create)`** — rare; class-level playbook with When to Use / Procedure / Pitfalls / Verification
4. **Nothing to save** — one-off narratives, diary entries, transient env failures

**Do NOT** put procedures in `lattice_apply` (`habits[]` is rejected). **Do NOT** capture session diaries as skills.

## Workflow (gate open only)

### 1. Packet

```
lattice_packet()
```

Habit hints suggest `suggested_action: evolve` — use `skill_manage`, not a CREATE micro-slug.

### 2. Re-read evidence

```
recall(query='retry')
get_run(run_id='run_a57d754d…')
```

Call `get_run` for every `source_run_id` you cite.

### 3. Facts → lattice_apply

```json
{
  "employee_id": "e_be_1",
  "patterns": [
    {
      "key": "api.retry",
      "claim": "The HTTP client in src/api/client.py retries 429 and 503 responses up to 3 times with exponential backoff from 0.2s to 30s.",
      "source_run_ids": ["r_done_1", "r_done_2"],
      "supersedes": null
    }
  ]
}
```

```
lattice_apply(proposal=<patterns only>)
```

### 4. Procedures → skill_manage

```
skill_manage(
  action='evolve',
  name='structuring-any-service',
  section='Before patching HTTP clients',
  content='## Before patching HTTP clients\n\n1. …\n\n## Pitfalls\n- …\n\n## Verification\n- …',
  source_run_ids=['r_done_1', 'r_done_2']
)
```

Prefer ≤10 patterns; prefer `evolve`/`patch` over `create`.

## When NOT to consolidate

- Gate closed (most beats)
- Mid-beat
- One-off / diary content — leave in episodic memory
- Sticky-note facts as skills — use `patterns[]` instead

## Tools

| Tool | Memory |
|------|--------|
| `lattice_apply` | Semantic patterns only |
| `skill_manage` | Procedural skills (versioned) |
| `lattice_context` / `skill` | Read facts / load playbooks |
