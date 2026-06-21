# 15 — Cross-child coherence via AGENTS.md

> Kills the integrate-time **split-brain** — the #1 deliverable defect across the
> live `--org` runs — by making `AGENTS.md` the canonical public-surface contract
> and gating the manager's integrate on a deliverable-coherence DoD reconciled to
> it. Wires up dream's **dormant** orientation + session-guard stack.

Paperclip counterpart: the `llm-wiki` *Wiki Maintainer* + `wiki-lint` + canonical
`AGENTS.md`. Siblings: [04 — Outcomes, DoD & governance](04-outcomes-and-governance.md)
(the DoD vocabulary), [05 — The dream seam](05-dream-seam.md) (orientation + the
session gate), [02 — Lifecycle & recovery](02-lifecycle-and-recovery.md) (the
parked-manager integrate beat + iteration cap).

---

## 1. The bug it fixes

Three live `Chorus.build --org` runs (`grpo`, `dpo_tune`, `ppo_lite`) each shipped
the same family of defects — **3 of 3**:

- **duplicate / rival modules** — two `Trainer`s, two `PreferenceDataset`s, two GAEs;
- **orphaned modules** — a polished `loss.py` / `buffer.py` imported by nothing;
- **wrong/empty public API** — `__init__` exporting nothing, both rival types, or
  omitting the brief's required surfaces;
- **dead config** — a hyperparameter config exported but unused by the trainer;
- **not installable / importable** — no packaging, ruff-config-as-packaging, or a
  top-level `import numpy` with no manifest (`import ppo_lite` raises).

### 1.1 Root cause (code-level)

The manager's "done" is the **Mechanical DoD: every child terminal**
([`chorus_employee/manager/_lander.py`](../../../src/chorus_employee/manager/_lander.py)
— *"When the integrate beat passes (the kernel's Mechanical DoD: every child
terminal), this lander records a `subtree` artifact"*). The manager ships when its
children **finish**, and never inspects whether what they merged is **one coherent
thing**. There is no owner of, and no gate on, the integrated public surface.

The real DoD vocabulary
([`chorus/outcomes/_verifier.py`](../../../src/chorus/outcomes/_verifier.py):
`Command`, `AgentReview`, `HumanApproval`, `ReviewedBuild`) is applied to leaf
engineer tasks, never to the integrated subtree.

## 2. The dormant machinery in dream

dream already ships the whole "canonical surface + gate + orientation" pipeline —
with **zero callers**, and chorus never writes an `AGENTS.md`:

| dream symbol | role | callers |
|---|---|---|
| `config/paths.py::DreamPaths.agents_md` → `repo/AGENTS.md` | contract location | (path only) |
| `services/repo_validator.py::validate_repo()` | session-start structural lint (AGENTS.md present + within caps, required tree, valid `docs.json`, no stale plans); **blocking = "do not start"** | none |
| `services/session_guard.py::session_start_findings()` | one gate = `validate_repo` + `threat_scan` | none |
| `engine/_orientation.py::run_orientation()` | reads AGENTS.md + findings + recent progress; prepends an orientation brief | none |

This spec **wires that up** and reconciles chorus's deliverable to the contract.

## 3. Decisions

1. **catch + cure now, prevent via AGENTS.md.** The coherence lint *defines*
   "coherent"; the integrate reconciliation beat *runs until* it passes.
2. **Coherence home — split.** dream owns the *generic* "repo is structurally
   valid" gate + AGENTS.md + orientation; chorus owns the *deliverable*-coherence
   DoD reconciled to AGENTS.md, gating the manager's integrate.
3. **`AGENTS.md` is the single contract object** for all three layers. It declares
   the deliverable's public surface: module map, the API `__init__`/`index` must
   export, and which child owns which file. **Authored by the manager at decompose**,
   re-written to current truth on re-decompose (never appended).
4. **Reuse the manager** as the reconciler — the integrate beat already exists,
   runs after children land, and is bounded by the integrate-iteration cap. No new
   role, no new lifecycle state.

## 4. Architecture

### 4.1 The contract — `repo/AGENTS.md`

Written by the manager during decompose
([`chorus/lifecycle/_decompose.py`](../../../src/chorus/lifecycle/_decompose.py)),
within dream's existing length caps. Declares:

- **Module map** — the files the package will contain and their purpose;
- **Public API** — the exact symbols `__init__`/`index`/`lib.rs` must export;
- **Ownership** — which child task owns which file (one owner per file).

### 4.2 dream side — wire the dormant stack (generic)

- **Prevent:** invoke `run_orientation` at the session `starting → orienting`
  boundary so every engineer beat reads `AGENTS.md` before writing.
- **Catch (generic):** invoke `session_start_findings` (= `validate_repo` +
  `threat_scan`) as the start gate; a blocking finding (AGENTS.md missing/oversized,
  broken tree) aborts before tokens are spent.
- **Wiring point:** both called through chorus's `EmployeeHarnessFactory` /
  `BeatRunner` — the one place chorus materializes the dream harness (see
  [05 — dream seam](05-dream-seam.md)). dream change = a *caller* for two functions
  that already exist; expose them on the surface chorus imports.

### 4.3 chorus side — coherence DoD (catch) + reconciliation (cure)

**Coherence DoD** — reconciled to `AGENTS.md`, the manager's integrate beat must pass:

1. every declared module exists, and **no public module/symbol is defined twice**
   (kills dup datasets / dup GAEs / two Trainers);
2. **`__init__`/`index` exports exactly the declared public API** (kills empty/wrong
   exports + omitted surfaces);
3. **no source file is imported by nothing** (kills orphaned `loss.py`/`buffer.py`);
4. the package **installs and imports / builds and tests in a clean env** (kills
   ppo's undeclared-numpy break, grpo's unreachable real code, and — per tinyvec —
   a deliverable that `cargo build`s but `cargo test` fails).

**Form:** a `Verifier` on the manager's integrate task. Default = `Command` (a
deterministic `chorus-coherence` check the kernel runs against company-main), with
`ReviewedBuild` as the richer option. It **replaces** the implicit Mechanical
"every child terminal" gate: `ManagerLander` lands the `subtree` artifact only when
**children terminal AND coherence-green**.

**Reconciliation loop (cure):** on failure the integrate beat is re-dispatched with
the findings as its packet; the manager reconciles the merged tree *to* `AGENTS.md`
(dedup, wire `__init__`, delete dead config, fix packaging), bounded by the existing
`max_integrate_iterations` cap. Cap hit while red ⇒ goal ends `blocked` **with a
precise coherence reason** — strictly better than today's silent split-brain `done`.

### 4.4 Data flow

```
decompose ─► manager writes repo/AGENTS.md (module map · public API · ownership)
   │
   ├─► each engineer beat: dream run_orientation reads AGENTS.md  (PREVENT)
   │                       dream session_guard gates a broken tree (CATCH/generic)
   │
   └─► children land ─► manager integrate beat
                          ├─ coherence DoD vs AGENTS.md green? ─► ManagerLander → subtree done
                          └─ red ─► re-dispatch w/ findings ─► reconcile ─► (loop ≤ cap)
                                     └─ cap hit & red ─► blocked(coherence reason)
```

## 5. Touchpoints

**dream** (`/Users/divyansh/Harness/src/dream`):
- `engine/_orientation.py` — add the caller at `starting → orienting`.
- `services/session_guard.py` — add the caller (abort-on-blocking before orientation).
- `config/paths.py` — `agents_md` exists; no change.
- public surface — export the two entry points chorus calls.

**chorus** (`/Users/divyansh/chorus/src`):
- `chorus/lifecycle/_decompose.py` — manager writes `AGENTS.md`.
- `chorus_harness/…` (`EmployeeHarnessFactory` / `BeatRunner`) — call dream's
  `run_orientation` + `session_guard` at beat start.
- `chorus/outcomes/_verifier.py` — add the coherence verifier (new `DoDKind` or a
  `Verifier.coherence(...)` `Command` factory).
- `chorus_employee/manager/_lander.py` + the integrate/Mechanical-DoD site — gate
  the `subtree` landing on coherence, not "every child terminal".
- `chorus_tools/` (or a `chorus-coherence` entrypoint) — the deterministic checker
  that reads `AGENTS.md` + the tree and exits non-zero on a violation.

## 6. Test plan (TDD)

**Unit (deterministic):**
- `AGENTS.md` codec — write/parse module-map + public-API + ownership.
- Coherence checker, one test per check on a fixture tree: dup public symbol → fail;
  `__init__` missing a declared export → fail; orphan file → fail; clean importable
  tree → pass.
- Manager integrate DoD — children-terminal + coherence-green → lands;
  + coherence-red → re-dispatch; cap hit + red → `blocked` with coherence reason
  (extend the existing adaptive-loop tests in [02](02-lifecycle-and-recovery.md)).
- dream — `session_guard` blocks on missing AGENTS.md; `run_orientation` brief
  contains the AGENTS.md contents.

**Keyed e2e (live model):** re-run `dpo_tune` with the feature on; assert the landed
tree is single-surface **or** the goal ends `blocked` with a coherence reason —
never a silent split-brain `done`.

**Gate:** `uv run ruff check .` · `uv run mypy --strict src` · `uv run pytest -q`
(chorus) + dream's gate for the wiring.

## 7. Out of scope (YAGNI)

- A dedicated integrator/architect *role* (reuse the manager).
- Hard ownership enforcement at write time (file-locking) — orientation + the
  integrate gate are enough to start.
- Semantic dedup of behaviourally-identical, differently-named modules (two GAEs in
  `gae.py` vs `buffer.py`); the orphan + declared-module checks catch the *symptom*.
- Cross-language coherence beyond "build + test in a clean env".

## 8. Success criteria

A `--org` build of a multi-module library either lands a **single coherent public
surface** (declared modules present, no duplicates, `__init__` exports the declared
API, installs + imports / builds + tests clean) **or** ends `blocked` with a
specific coherence reason. The silent split-brain `done` — 3 of 3 runs — becomes
impossible.
