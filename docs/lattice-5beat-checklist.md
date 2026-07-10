# Lattice 5-beat probe checklist (P1 patterns-only)

Run on **chorus** `feat/lattice-integration` + **lattice** `feat/patterns-only`. Do not merge PRs.

## Phase 0 — Branch prep

- [ ] `feat/episodic-storage-engine` rebased onto `feat/lattice-integration`
- [ ] `feat/lattice-integration` fast-forwarded to include episodic commits
- [ ] Lattice skills transported to `chorus_employee/_lattice_skills/` (not lattice package)

## Phase 1 — Unit tests (deterministic)

### Chorus

- [ ] `uv run pytest tests/harness/test_lattice_*.py tests/tools/test_lattice_tool.py -q`
- [ ] `uv run pytest tests/harness/ tests/memory/test_recall_*.py -q` (episodic + harness)
- [ ] Lattice skills materialize into `.harness/skills/lattice-{context,consolidate}/`

### Lattice

- [ ] `uv run pytest -q` (53 tests, incl. E2E-01 five-beat golden path)

## Phase 2 — Infrastructure (per beat, deterministic)

| # | Check | Beat 1–4 | Beat 5 |
|---|-------|----------|--------|
| 1 | Episodic record appended for `bex` | ✓ each beat | ✓ |
| 2 | `lattice_context` / `lattice_packet` / `lattice_apply` in registry | ✓ | ✓ |
| 3 | Lattice skills in worktree `.harness/skills/` | ✓ | ✓ |
| 4 | Gate closed (`lattice-beat-end.json` absent) | ✓ | — |
| 5 | Gate open + teaser file written | — | ✓ |
| 6 | `recall` + `get_run` wired (episodic v2) | ✓ | ✓ |

## Phase 3 — Gate + consolidation (beat 5+)

- [ ] ≥5 episodic records with shared `src/api/` cluster
- [ ] Beat-start reads `lattice-beat-end.json` and injects consolidation push into `system_prompt`
- [ ] `lattice_packet()` returns engrams (harness or agent)
- [ ] Valid `Proposal` → `lattice_apply` succeeds
- [ ] `lattice_context(query='retry')` returns pattern with `src:` run ids
- [ ] `get_run(run_id)` retrieves full prose for cited beats (`recall(query)` for slim search)

## Phase 4 — Agent behavior (live probe)

- [ ] Backend engineer completes 5 heartbeat ticks without harness crash
- [ ] Beat never fails because lattice threw (E2E-14)
- [ ] After gate opens, next beat-start includes lattice consolidation push
- [ ] Agent calls `lattice_packet` + `get_run` + `lattice_apply` (may occur on beat 5; t6 only if gate still open)

**v3 result (beat-start injection):** gate opened on t4 tick 2; agent consolidated on **t5** (`lattice_packet`, `get_run` ×2, `lattice_apply`). Semantic atoms written under `lattice/bex/semantic/`. Dedicated t6 skipped because gate closed after agent apply.

## Commands

```bash
# Unit tests
cd chorus && uv run pytest tests/harness/test_lattice_factory_wiring.py tests/harness/test_lattice_wiring.py tests/tools/test_lattice_tool.py -q
cd lattice && uv run pytest -q

# Live 5-beat probe (requires AZURE_OPENAI_* in chorus/.env)
cd chorus
CHORUS_PROBE_BEAT_TIMEOUT_S=120 CHORUS_PROBE_MAX_TICKS=6 \
  uv run python examples/backend_engineer_lattice_5beat_probe.py
```

## Pass criteria

**Hard pass:** Phases 0–1 + Phase 2 + Phase 3 (≥5 records, gate/teaser lifecycle, consolidation via agent **or** programmatic fallback).

**Agent consolidation counts on any beat** — not only dedicated t6. If the agent calls `lattice_apply` before t6, programmatic fallback is skipped and t6 is not required.
