# Handoff — 2026-06-17

What landed today, in order, with the folders it created. Everything below is on `main` and green
(ruff + mypy `--strict` + full pytest, 771 passing at end of day).

---

## The arc of the day

The day turned **spec 06 (roles & workforce)** and the **engineer** from a static model into a
*running, role-faithful* employee you can talk to — then chased two real CLI bugs to ground.

### 1. Spec 06 substrate → live org store

- `97f7d56` split `chorus/workforce/__init__.py` into `_models` / `_protocol` / `_git`.
- `49661b5` made the **ledger the single live org store** (`LedgerWorkforce`).
- `b79a326` wired **`GitWorkforce`** as the org-as-data export/import codec (spec 09 §3).
- `47d1ce6` added **workforce lifecycle verbs** (hire/terminate/pause/resume) routed through the
  live store (spec 06 §3).
- `8528574` + `af1d658` wrote and then re-scoped **`06.5`** as the cross-spec deferral backlog (04–06).

### 2. The employee becomes a configured dream harness

- `e57726e` (#26) — an **org-native `chat` interface**: converse with an employee.
- `776820e` (#27) — **role-aware chat**: an employee *is* a configured dream harness (tools, brief,
  permission, memory) resolved from its role.
- `a9a4215` (#28) — **full-fledged employee**: every `build_harness` knob carried from the role
  manifest, plus **branch-isolated worktrees** (`.chorus/work/{org}/worktrees/{employee}`).
- `4be22f0` (#29) — **DoD-at-intake**: a chat task inherits the assignee role's DoD (the engineer to
  its `pytest && ruff` gate) at dispatch.

### 3. The converged, role-faithful kernel

- `81469ef` (#30) — **tick + chat run every beat as its employee** through one
  `EmployeeHarnessFactory` (the `BeatRunnerFor` seam). One identity, one worktree, two front ends.

### 4. Completing the engineer's outcome (spec 04 §2)

- `8642b69` (#31) — **outcome landing**: the `LanderRegistry` seam + `EngineerLander` (a passed beat
  snapshots the worktree → records a `pr` artifact on the ledger).
- `5f5cfb1` — **completed the §2 outcome**: PR → CI → **merge** (the lander integrates
  `chorus/{employee}` into the company `main`) + a **host-safe** artifact ref (relative worktree
  pointer, no host-absolute path). Conflicts are recorded, never raised.
- `9b35aff` (earlier, merged via #31) — **role-configurable trust posture**: `SandboxTier` on the
  manifest → `.harness/sandbox.toml`; the engineer is `unrestricted` *within its worktree* so it can
  run tests/builds (the reviewer is `read-only`).

### 5. Operability + two real bug fixes

- `8d5e409` — the **`company` console command**: show or create the company workspace up front
  (`company init [seed]`), idempotent, instead of relying on lazy creation. Extracted the
  `.chorus/work/{company}` convention into a dream-free `default_work_root()` so the command and the
  harness factory can't drift.
- `8ef7f25` — **auto-retry transient beat faults + surface the reason in chat**. A `*HeadParseError`
  (the model emitting unparseable structured output) is now flagged `retryable`; the scheduler
  re-runs it up to `transient_retries` (default 2) before stranding. Chat no longer shows a silent
  `cost=0c` — the footer names the cause (`planner parse error (transient …)`, `errored (…)`,
  `DoD not met`).
- `234c964` — **`.env` made authoritative over stale shell vars** (the day's headline bug). A
  hardcoded `AZURE_OPENAI_API_KEY` in `~/.zshrc` was shadowing `.env` (the loader let the ambient
  value win), so every beat hit the wrong endpoint and failed with an opaque `PlannerHeadParseError`.
  The CLI now loads `.env` with `override=True` and **warns** on each real conflict.

> **Debugging note for the next session:** "works for me, fails in your terminal, every time" was
> *not* a transient model issue — it was env-var precedence (`.zshrc` key ≠ `.env` key). A bad key
> surfaces as a planner *parse* error (the harness swallows the auth failure into an empty
> completion) — a dream-side robustness gap worth a follow-up. **Action still owed:** delete the
> hardcoded key from `~/.zshrc` and **rotate it** (it was exposed in plaintext).

---

## Folders created today

| Folder | What it holds |
|---|---|
| `src/chorus/roles/` | `RoleManifest` / `Role` / `RolePlugin` / overlay / `RoleRegistry` / `RoleBeatConfig` — the role machinery |
| `src/chorus/workforce/` | `Employee` / `Workforce` / `LedgerWorkforce` / `GitWorkforce` — the org store + codec |
| `src/chorus/workspace/` | `CompanyWorkspace` — branch-isolated git worktrees + merge + `default_work_root` |
| `src/chorus/outcomes/` | `Verifier` / `Artifact` / `OutcomeLander` / `LanderRegistry` — the DoD + landing seam |
| `src/chorus/adapters/` | `DreamBeatRunner` / `DreamObserverBridge` / `_failure` — the dream seam (the one import boundary) |
| `src/chorus/heartbeat/` | `Scheduler` / `BeatRunner` / `BeatRunnerFor` — the kernel tick + beat |
| `src/chorus_employee/` | concrete employees; `src/chorus_employee/engineer/` — the engineer's complete config (brief, harness, dod, lander) |
| `src/chorus_harness/` | `EmployeeHarnessFactory` — the one role→harness materializer (owns the `dream` import) |
| `docs/specs/engineer-full/` | **this folder** — the handoff + the engineer spec |
| tests | `tests/{roles,workforce,workspace,outcomes,adapters,heartbeat,employee,harness,cli,lifecycle,examples}/` |
| examples | `engineer_full_run.py` (keyed e2e), `role_chat_smoke.py`, `tick_role_faithful_smoke.py`, `worktree_merge_smoke.py`, `depth_cap_smoke.py` |

---

## State at end of day

- **Engineer**: fully wired end-to-end — chat or tick → role-faithful harness in an isolated
  worktree → `pytest && ruff` DoD → PR artifact → merge to company `main`. Proven with live keyed
  runs.
- **Open follow-ups** — engineer skills/plugins/MCP/hooks are wired as **off** toggles (no playbooks
  yet) and observability is consumed live by `chat` only. The build plan for finishing all of these
  is **[`spec.md`](spec.md)** (6 sections: hooks · skill files · plugins · MCP · event log ·
  inspector). Other open items: the non-engineer landers, the reviewer/AgentReview verdict path, and
  the `06.5` backlog.
