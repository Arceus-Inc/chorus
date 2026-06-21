# Cross-child coherence via AGENTS.md — design

Status: Draft (brainstorm → spec)
Date: 2026-06-21
Author: divo + Claude
Topic: kill the integrate-time "split-brain" by wiring dream's dormant AGENTS.md
stack as a canonical surface contract, and gating the manager's integrate on a
deliverable-coherence DoD reconciled to that contract.

---

## 1. Problem

Across three live `Chorus.build --org` runs (`grpo`, `dpo_tune`, `ppo_lite`) the
**#1 deliverable defect is split-brain**: parallel engineers each author a slice,
and `integrate` merges the fragments without anyone owning the shared public
surface. Concretely, the same family of bugs recurred in 3 of 3 runs:

- **Duplicate / rival modules** — two `Trainer`s (grpo), two `PreferenceDataset`
  classes (dpo_tune), two GAE implementations (ppo_lite).
- **Orphaned modules** — a polished `loss.py` / `buffer.py` imported by nothing;
  the real implementation living outside the importable package.
- **Wrong/empty public API** — `__init__` exporting nothing (grpo), exporting
  both rival types (dpo_tune), or omitting the brief's required surfaces (ppo_lite).
- **Dead config** — a hyperparameter config exported but unused by the trainer.
- **Not installable / not importable** — no packaging, ruff-config-as-packaging,
  or a top-level `import numpy` with no manifest (`import ppo_lite` raises).

### 1.1 Root cause (grounded in the code)

The manager's "done" is decided by the **Mechanical DoD: every child terminal**
(`src/chorus_employee/manager/_lander.py` — *"When the integrate beat passes (the
kernel's Mechanical DoD: every child terminal), this lander records a `subtree`
artifact"*). The manager ships when its children *finish*, and **never inspects
whether what they merged is one coherent thing.** That is the entire bug: there is
no owner of, and no gate on, the integrated public surface.

The DoD vocabulary that *does* exist (`src/chorus/outcomes/_verifier.py`:
`Command`, `AgentReview`, `HumanApproval`, `ReviewedBuild`) is applied to leaf
engineer tasks, not to the integrated subtree.

## 2. Reference: how paperclip and dream already frame this

**paperclip** (`paperclipai/paperclip`, a near-exact analog — *"If OpenClaw is an
employee, Paperclip is the company"*) kills split-brain at three points:

- **Prevent** — a canonical `AGENTS.md` + `wiki/index.md` that *every* agent reads
  before working ("the source of truth for page layout… conventions").
- **Cure** — a dedicated *Wiki Maintainer* agent that owns reconciling new work
  into the canonical surface, and *rewrites to current truth instead of appending*.
- **Catch** — a `wiki-lint` pass: "read-only audit for contradictions, orphans,
  weak provenance, missing concept pages." A literal split-brain detector.

Code lands as **PRs through review/CI** (with a workspace-diff "Changes" view),
never blind fragment-merge.

**dream** already ships this machinery — *fully dormant*:

| dream symbol | what it does | callers today |
|---|---|---|
| `DreamPaths.agents_md` → `repo/AGENTS.md` | canonical contract location | (path only) |
| `repo_validator.validate_repo()` | session-start structural lint: AGENTS.md present + within caps, required tree, valid `docs.json`, no stale plans; **blocking = "do not start"** | **none** |
| `session_guard.session_start_findings()` | one gate = `validate_repo` + `threat_scan` | **none** |
| `engine/_orientation.run_orientation()` | reads AGENTS.md + findings + recent progress, prepends an orientation brief to the conversation | **none** |

The whole "canonical surface + gate + orientation" pipeline was built and never
wired into dream's session lifecycle, and **chorus never writes an `AGENTS.md`**.

## 3. Design decisions (from the brainstorm)

1. **Intervention point: catch + cure now, prevent via AGENTS.md.** The
   coherence lint *defines* "coherent"; the integrate reconciliation beat is what
   *runs until* it passes.
2. **Coherence home — split:** dream owns the *generic* "repo is structurally
   valid" gate + AGENTS.md + orientation; chorus owns the *deliverable*-coherence
   DoD reconciled to AGENTS.md, gating the manager's integrate.
3. **`AGENTS.md` is the single contract object** binding all three layers
   (prevent / catch / cure). It declares the deliverable's intended public
   surface: module map, the public API `__init__`/`index` must export, and which
   child owns which file. **Authored by the manager at decompose.**
4. **Reuse the manager** as the reconciler — the integrate beat already exists,
   already runs after children land, already bounded by the integrate-iteration
   cap. No new role, no new lifecycle state.

## 4. Architecture

### 4.1 The contract — `repo/AGENTS.md`

Written by the manager during decompose (`src/chorus/lifecycle/_decompose.py`).
Minimal, declarative, within dream's existing length caps. Declares:

- **Module map** — the files the package will contain and their purpose.
- **Public API** — the exact symbols `__init__`/`index`/`lib.rs` must export.
- **Ownership** — which child task owns which file (one owner per file).

This is the artifact every layer reads and reconciles to. It is *re-written to
current truth* on re-decompose (paperclip's standup.md discipline), never appended.

### 4.2 dream side — wire the dormant stack (generic)

- **Prevent:** invoke `run_orientation` at the session `starting → orienting`
  boundary so every engineer beat reads `AGENTS.md` before writing. Shared model
  of the package shape ⇒ no divergence at the source.
- **Catch (generic):** invoke `session_guard.session_start_findings`
  (= `validate_repo` + `threat_scan`) as the start gate; a blocking finding
  (AGENTS.md missing/oversized, broken required tree) aborts the session before
  any tokens are spent.
- **Wiring point:** both are called through chorus's `EmployeeHarnessFactory` /
  `BeatRunner` (`src/chorus_harness/…`) — the one place chorus materializes the
  dream harness. dream changes are minimal: ensure `run_session` (or the harness
  entry chorus uses) calls these existing functions; expose them on the public
  surface chorus imports. **No new dream behaviour — only a caller.**

### 4.3 chorus side — the deliverable-coherence DoD (catch) + reconciliation (cure)

**Coherence DoD** — a new check the manager's integrate beat must pass, reconciled
to `AGENTS.md`:

1. every module declared in `AGENTS.md` exists, and **no public module/symbol is
   defined in two places** (kills dup datasets / dup GAEs / two Trainers);
2. **`__init__`/`index` exports exactly the public API `AGENTS.md` declares**
   (kills empty/wrong exports + omitted surfaces);
3. **no source file is imported by nothing** (kills orphaned `loss.py`/`buffer.py`);
4. the package **installs and imports/builds and tests in a clean env** (kills
   ppo's undeclared-numpy break, grpo's unreachable real code, and — per the
   tinyvec run — a deliverable that `cargo build`s but `cargo test` fails).

**Form:** a `Verifier` on the manager's integrate task. Default = `Command`
(a deterministic `chorus-coherence` check the kernel runs against company-main),
with `ReviewedBuild` as the richer option (a reviewer discovers + judges, kernel
runs the command floor). It **replaces** the implicit Mechanical "every child
terminal" gate: `ManagerLander` lands the `subtree` artifact only when
**children terminal AND coherence-green**.

**Reconciliation loop (cure):** when the coherence DoD fails, the integrate beat
is re-dispatched with the failures as its packet; the manager reconciles the
merged tree *to* `AGENTS.md` — dedup, wire `__init__`, delete dead config, fix
packaging — bounded by the **existing integrate-iteration cap**
(`max_integrate_iterations`). If the cap is hit while still red, the goal ends
`blocked` **with a precise coherence reason** — strictly better than today's
silent split-brain `done`.

### 4.4 Data flow

```
decompose ─► manager writes repo/AGENTS.md (module map · public API · ownership)
   │
   ├─► each engineer beat: dream run_orientation reads AGENTS.md  (PREVENT)
   │                       dream session_guard gates a broken tree (CATCH/generic)
   │
   └─► children land ─► manager integrate beat
                          │
                          ├─ coherence DoD vs AGENTS.md green? ──► ManagerLander → subtree done
                          └─ red ──► re-dispatch integrate w/ findings ──► reconcile ──► (loop ≤ cap)
                                       └─ cap hit & red ──► blocked(coherence reason)
```

## 5. Touchpoints (implementation map)

**dream** (`/Users/divyansh/Harness/src/dream`):
- `engine/_orientation.py` — already has `run_orientation`; add the caller in the
  session orchestrator (`starting → orienting`).
- `services/session_guard.py` — already has `session_start_findings`; add the
  caller (abort-on-blocking before orientation).
- `config/paths.py` — `agents_md` exists; no change.
- Public surface (`dream/__init__` or the harness entry) — export the two entry
  points chorus needs to call.

**chorus** (`/Users/divyansh/chorus/src`):
- `chorus/lifecycle/_decompose.py` — manager writes `AGENTS.md` (the declared
  surface) at decompose.
- `chorus_harness/…` (`EmployeeHarnessFactory` / `BeatRunner`) — call dream's
  `run_orientation` + `session_guard` at beat start.
- `chorus/outcomes/_verifier.py` — add the coherence verifier (new `DoDKind` or a
  `Command` factory `Verifier.coherence(...)`).
- `chorus_employee/manager/_lander.py` + the integrate/Mechanical-DoD site — gate
  the `subtree` landing on the coherence DoD instead of "every child terminal".
- `chorus_tools/` (or a small `chorus-coherence` entrypoint) — the deterministic
  checker that reads `AGENTS.md` + the tree and exits non-zero on a violation.

## 6. Test plan (TDD)

**Unit (deterministic, no model):**
- `AGENTS.md` codec: write/parse the module-map + public-API + ownership block.
- Coherence checker, one test per check, each seeded with a fixture tree:
  - dup public symbol in two files → fail;
  - `__init__` missing a declared export → fail;
  - orphan source file (imported by nothing) → fail;
  - clean tree that imports/installs → pass.
- Manager integrate DoD: children-terminal + coherence-green → `subtree` lands;
  children-terminal + coherence-red → re-dispatch; cap hit + red → `blocked` with
  coherence reason (extend the existing adaptive-loop deterministic tests).
- dream: `validate_repo`/`session_guard` blocking on a missing AGENTS.md;
  `run_orientation` brief contains the AGENTS.md contents.

**Keyed e2e (live model):**
- Re-run one of the three failing goals (e.g. `dpo_tune`) end-to-end with the
  feature on; assert the landed tree is single-surface (no dup module, `__init__`
  exports the declared API, package imports) **or** the goal ends `blocked` with a
  coherence reason — never a silent split-brain `done`.

**Gate:** `uv run ruff check .` · `uv run mypy --strict src` · `uv run pytest -q`
in chorus; dream's own gate for the wiring change.

## 7. Out of scope (YAGNI)

- A dedicated integrator/architect *role* (reuse the manager).
- Prevent-at-decompose enforcement beyond AGENTS.md (no file-locking / no
  hard ownership enforcement at write time — orientation + the integrate gate are
  enough to start).
- Semantic dedup of behaviourally-identical-but-differently-named modules (e.g.
  two GAEs in `gae.py` vs `buffer.py`); the orphan + declared-module checks catch
  the *symptom* (one of them is imported by nothing / not in the map). True
  semantic dedup is a later enhancement.
- Cross-language coherence beyond "build + test in a clean env" for non-Python
  deliverables.

## 8. Success criteria

A `--org` build of a multi-module library either lands a **single coherent public
surface** (declared modules present, no duplicates, `__init__` exports the declared
API, installs + imports/builds + tests in a clean env) **or** ends `blocked` with a
specific coherence reason. The silent split-brain `done` — seen in 3 of 3 runs —
becomes impossible.
