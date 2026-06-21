# Issues — synthesis across 7 `--org` runs

Corpus: **grpo · dpo_tune · ppo_lite · tinyvec · tooldeck · streamparse · flowdag**
(`g d p t k s f`). Each issue is tagged with the runs it appeared in and a count.

- **COMMON ISSUES** — recurring in **≥ 4 of 7** runs (systemic; fix these first).
- **OTHER ISSUES** — appeared in fewer than 4 runs (shape-dependent or one-off).

Every run ended **`blocked`**, and every deliverable carried the split-brain.

---

## COMMON ISSUES (≥ 4/7)

### 7/7 — present in every run

| Issue | g | d | p | t | k | s | f |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| **Split-brain — a duplicate/rival module, symbol, or whole implementation** (2 Trainers · 2 datasets · 2 GAEs · impl-vs-test API · 2 registries · entry-vs-impl · Go+Python twin) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **No cross-child ownership of the public surface** — the root cause of the split-brain | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **The DoD passed over off-brief / insufficient work** — the "tests-pass" illusion | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Top goal ended `blocked`, not `done`** (BUG-007) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **A deliverable task was handed to a non-coding role → rejected** (BUG-006: analyst, once also pm) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **README is still the `# company repo` seed stub** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Stray `test_smoke.py` + leaked harness/build files** (docs/evals · exec-plans · committed `target/`) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

### 5/7

| Issue | g | d | p | t | k | s | f |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| **No / fake / broken packaging-or-manifest** (none · ruff-only · none · — · none · fictional `exports`+`name:"ada"` · —) — *tinyvec & flowdag had valid manifests* | ✓ | ✓ | ✓ | — | ✓ | ✓ | — |

### 4/7

| Issue | g | d | p | t | k | s | f |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| **Entry point exports the wrong / empty / placeholder API** (`__init__` empty · exports rivals · omits required · `index` exports `hello`) | ✓ | ✓ | ✓ | — | — | ✓ | — |
| **Orphaned / unreachable module** — real code imported by nothing, or living outside the package | ✓ | ✓ | ✓ | — | ✓ | — | — |
| **Build / typecheck / test broken in a clean environment** (import crash · `cargo test` fail · `tsc` fail · `go build` fail) | — | — | ✓ | ✓ | — | ✓ | ✓ |
| **`done` ≠ landed — an engineer's branch never merged** (BUG-005) | ✓ | ✓ | ✓ | — | — | ✓ | — |
| **A brief-required headline feature is missing** (real GRPO unreachable · KL unreachable · not-PPO · no ANN+persistence) | ✓ | ✓ | ✓ | ✓ | — | — | — |

---

## OTHER ISSUES (< 4/7)

### 3/7
- **Dead config** — a config object exported but unused by the implementation (`TrainerConfig`×2, dead `TrainerConfig`, dead `PPOConfig`). — `g d p`
- **A task stranded in `todo`** — created but never started before the goal closed. — `p t f`

### 2/7
- **Wrong-toolchain DoD** — the objective gate ran a *different language's* tests than the deliverable (`pytest` for a TypeScript package; `pytest` for a Go module) and passed trivially while the real build failed. *Low frequency but high severity — it only appears where the deliverable isn't Python, and it hit 2 of the 3 non-Python runs.* — `s f`

### 1/7 (notable singletons)
- **Cross-language twin** — the whole library implemented in two languages side by side (Go + Python). — `f` *(an extreme variant of split-brain)*
- **Package named after the engineer** — `package.json "name": "ada"` instead of the deliverable. — `s`
- **Committed build cache** — the entire `target/` directory (~1.4 MB of `.rmeta`/`dep-graph.bin`) checked in; no `.gitignore`. — `t`
- **Numeric-substrate split** — components written against three different substrates (torch / numpy / pure-Python) that don't compose. — `p`
- **Reversed API arguments between rivals** — `register(func, name)` vs `register(name, func)` across the two `ToolRegistry` copies. — `k`
- **Config-knob name mismatch** — `clip_coef` (config) vs `clip_range` (loss); `ref_kl_coeff` ignored. — `d p`
- **A Python file in a non-Python deliverable** — `test_smoke.py` / `test_*.py` committed inside a Rust crate and a TS package. — `t s` *(counted under the 7/7 stray-files issue, called out here for the cross-language angle)*

---

## Reading

- **Two root causes drive the COMMON list.** "No one owns the shared surface" → split-brain, wrong/empty exports, orphaned modules, the missing-feature gap. "The ledger trusts finish-state, not landed reality" → `blocked` tops, `done` ≠ landed, analyst mis-assignment.
- **The DoD is the amplifier.** A gate that checks "some command exits 0" — instead of "the declared deliverable builds, imports, and is exercised in its own toolchain" — let every one of these ship green at the leaf level while the integrated whole was incoherent.
- See the per-run dissections in [`index.html`](index.html) and the proposed fix in [`../../docs/specs/divo/15-cross-child-coherence.md`](../../docs/specs/divo/15-cross-child-coherence.md).
