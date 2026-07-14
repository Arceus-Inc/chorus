# Four-repo integration & E2E checklist — dream · chorus · lattice · horizon

**As of:** 2026-07-14 · dream `83a5f9f` · chorus `Chorus-employees @ df3de8a` · lattice `1132f4d` · horizon `29051f2`

The system spine: **horizon** decides what the company does (Decision → Goal → intake) →
**chorus** runs the org that ships it (employees, beats, landers, episodic memory) →
**lattice** consolidates what mattered (patterns, skills) → **dream** is the shared harness +
the only cross-repo contract surface (`dream.contracts`: strategy + governance Protocols).

---

## 1. What the latest reports already prove (green)

| Seam | Evidence | Verdict |
|---|---|---|
| chorus ↔ dream (harness core) | factory/scheduler suites; every live employee probe rides `dream.build_harness` | ✅ proven |
| chorus ↔ lattice, live | `reports/backend-engineer-lattice-5beat.json`: 12/13 checks, t7 retrieval 6/6 (fails: soft `get_run` drill-down count; one strict-match assertion quirk) | ✅ core loop proven |
| chorus ↔ lattice, procedural | `reports/backend-engineer-lattice-habit-live.json`: gate open → `lattice_apply` + `skill_manage(evolve)` live | ✅ evolve proven; create/patch live-unproven |
| Episodic recall rerank | `reports/episodic-rerank-probe.json`: 4/4 deterministic | ✅ |
| chorus CEO ↔ horizon via `GovernancePort` | horizon `reports/ceo-capstone/data.json`: passed=true, DoD 0.92, 8 gov calls / 0 hard errors; `ceo_governance_probe` 8/8 live | ✅ proven (pre-sync SHAs — see §2.1) |
| horizon ↔ chorus intake (IntakePort/GoalStore/OutcomeFeed) | horizon `test_m1_seam` (4), `test_m2_integration` (3), `test_m2_live` (1) | ✅ seam-level |
| lattice offline lifecycle | 28-file suite (unit/components/integration) + `examples/demo_offline.py`; covers E2E-01…E2E-10 of `lattice/docs/plans/e2e-scenarios.md` | ✅ |
| Ledger governance (§5 chorus-internal) | `reports/m3-governance.html` — 4 governed actions e2e on real SqliteLedger | ✅ |

## 2. Integration checklist (gaps, ordered by risk)

### 2.1 Re-verify live seams at the **synced** SHAs — ✅ DONE 2026-07-14
- [x] 5beat probe re-run at synced SHAs: all core checks + t7 6/6 + `get_run` drill-down (3 calls) pass; the one residual FAIL was a probe bug (literal `api.retry` key match — the agent authored `api.client.retry_policy`); assertion made key-agnostic and verified against the run's real atoms
- [x] `ceo_governance_probe` re-run: PASS — 0 hard errors, 1 *recovered* refusal. Two fixes landed: chorus governance-tool input schemas now spell out id shapes (`goal_…` vs `dec_…`/`prop_…`); probe now classifies a `refused:` result the agent recovers from as the error contract working, not a seam defect
- [ ] `ceo_live_baseline.py` (chorus) — not re-run (superseded by the full-spine CEO leg)

### 2.2 Cross-repo drift gate — ✅ script landed 2026-07-14
- [x] `chorus/scripts/workspace_gate.sh` — prints the 4 SHAs, runs dream → lattice → chorus → horizon fast suites, deselects the 3 known chorus env-only failures. Ran green at dream `83a5f9f` / lattice `1132f4d` / chorus `df3de8a`+fixes / horizon `29051f2`
- [ ] chorus: a unit test asserting `from dream.contracts import GovernancePort` and the exact lattice symbols chorus imports (`build_default`, `EpisodicReader`, directive exports) — so contract drift fails in chorus's own gate, not at e2e time

### 2.3 dream contract coverage — #76 shipped with **zero tests in dream**
`GovernancePort`/`GovernanceView` and the #75 strategy Protocols are tested only downstream
(horizon fakes + live probe). Contract drift would surface two repos away.
- [ ] dream: structural tests — a minimal fake implements each Protocol, `isinstance` passes (`runtime_checkable`), DTO field-set snapshot per contract version
- [ ] dream: bump-detection — changing a Protocol method without bumping the contract version string fails a test

### 2.4 lattice L2 seam against the **real** chorus store (E2E-11)
`test_chorus_seam`/`test_chorus_bridge` currently use fakes; the real-store variant
needs chorus as a dev extra.
- [ ] lattice: `uv sync --extra dev` (chorus editable) and run the seam test against a real `EpisodicStore` with 5 `SprintDelta`s — asserts the adapter round-trips fields (esp. `recorded_at`, tuples) exactly

### 2.5 The missing e2e: **full spine, one run** — ✅ BUILT + PASSING 2026-07-14
- [x] `horizon/examples/full_spine_e2e.py` — Decision → goals → bridge intake (priority from strategy score, idempotent) → 2 live backend_engineer beats on the real heartbeat (`Chorus.build` front door, explicit command DoD) → OutcomeFeed → health `on_track` + score decay + task reprioritised → CEO governance beat (approve/reject/directive/DoD) → 16 self-verified checks + `reports/full-spine/data.json`; skips cleanly without keys
- [x] **First run (15/16) caught a real front-door bug:** `Chorus.build` never passed `memory_writer` to the Scheduler — every facade-built org ran beats with ZERO episodic capture (all prior probes hand-wired the scheduler, so none could see it). Fixed in `chorus/src/chorus/facade.py` + pinned by `tests/test_facade_build_landers.py::test_build_threads_the_memory_writer_into_the_scheduler` (TDD). Re-run: **16/16 PASS**, episodic count=2

### 2.6 Smaller known gaps
- [ ] `skill_manage` `create`/`patch` verbs: never exercised live (only `evolve`). One targeted live beat or explicitly accept as unit-covered
- [ ] Multi-employee lattice isolation **live**: 5beat probe is single-employee; run a 2-employee org and assert separate `lattice/<employee_id>/` dirs, no cross-citation (unit-covered by lattice E2E-06 only)
- [ ] Stale-DB drift: `MigrationDriftError` on old `episodic.db` files cost debugging time — add a friendlier error (message names the file to delete) or an auto-quarantine of mismatched dev DBs
- [ ] CEO memory decision: CEO manifest has `memory_search/get` but not `recall` (not in `_RECALL_ROLES`). Confirm deliberate or add — the CEO is the one role whose past directives are pure gold for the next beat
- [ ] CI: only dream has `.github/workflows/ci.yml`. Add the same fast-suite workflow to chorus, lattice, horizon (each repo's own gate: ruff + mypy --strict + pytest -m "not live")

## 3. Docker — needed for the experimental run?

**No — not for correctness.** The whole stack is local Python: uv-managed venvs, SQLite +
JSON-file stores, git worktrees. The only external dependency for live runs is Azure OpenAI
env vars from `.env`. Nothing listens on a port except the optional Strapi CMS (marketer
delivery path only — not part of this integration surface).

**The real reproducibility risk is editable-dep drift, and Docker is the heavy fix for it.**
The lazy fix that gives ~all the benefit:

- [ ] `experiment/setup.sh`: clone the 4 repos at **pinned SHAs** into an isolated dir, one
  `uv sync` each, fresh `.chorus` work root, record the SHA manifest into the run report.
  Every experimental run becomes reproducible and immune to whatever main moves under it.

**When Docker *does* become worth it** (add then, not before):
1. Parallel experiments needing hard isolation (ports, env, temp state) on one machine
2. Long unattended org runs where a host upgrade/env change mid-run would poison results
3. Strapi (or any future service: Postgres brain, HydraDB) joins the loop — then a
   `docker-compose.yml` for the *services only*, agents still on the host
4. CI runners for the live-probe suite

## 4. Suggested execution order

1. §2.2 workspace-gate script (30 min, kills the recurring breakage class)
2. §2.1 re-run the three live probes at synced SHAs (keys + ~20 min wall clock)
3. §2.5 full-spine e2e (the one genuinely new artifact; ~a day)
4. §2.3 dream contract tests + §2.4 lattice L2 (small, parallelizable)
5. §3 pinned-SHA experiment script — before starting the next long experimental run
6. §2.6 as background cleanup
