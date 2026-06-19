# §4 Trust presets — `standard` / `low_trust_review`, fail-closed

Status: **implemented** on `dev/m1-trust-presets` (Slices 1–6, branched off `main`). Gate green — ruff +
mypy `--strict` + full pytest. Suite: `examples/trust_presets_suite.py` →
`reports/m1-trust-presets.html`. Closes the §4 deferral in
[06.5-deferred-from-spec04.md](../divo/06.5-deferred-from-spec04.md). Pure-chorus: the resolved preset
rides the **existing per-beat materialize boundary** (the factory already writes `sandbox.toml` +
`permission_mode` + env every beat), so **no dream change** is needed.

## The goal

Two trust presets. `standard` is the role's normal posture. `low_trust_review` is **containment for
hostile / prompt-injected input** (external PRs, untrusted tickets, dependency diffs): the beat runs
read-only, plan-mode, no-net, with secrets scrubbed to approved refs. The effective preset is resolved
by **intersecting employee ∩ task ∩ run — narrower wins** — and *anything* ambiguous (a low-trust layer
with no concrete boundary, a layer conflict, an unsupported preset) → **denied, fail-closed**.

Invariant: **containment ≠ privacy** — low-trust limits what the agent may *do*; it never hides work
from the board (the ledger/artifacts are unaffected).

## 1. Models (`chorus/trust/`)

```python
class TrustPreset(StrEnum):
    STANDARD = "standard"
    LOW_TRUST_REVIEW = "low_trust_review"

@dataclass(frozen=True)
class TrustProfile:                 # what a preset clamps to (a ceiling, never a widening)
    max_sandbox: SandboxTier        # standard → UNRESTRICTED; low_trust → READ_ONLY
    permission_mode: PermissionMode # standard → DEFAULT;      low_trust → PLAN
    net_allowed: bool               # low_trust → False
    requires_boundary: bool         # low_trust → True

_PROFILES: dict[TrustPreset, TrustProfile] = { STANDARD: …, LOW_TRUST_REVIEW: … }

@dataclass(frozen=True)
class TrustBoundary:                # the concrete scope a low-trust beat is confined to
    secret_ref_allowlist: frozenset[str]   # the secret *refs* it may use (no raw values, ever)

@dataclass(frozen=True)
class TrustPolicy:                  # like §5's GovernancePolicy — derive a preset from task origin
    low_trust_origins: frozenset[OriginKind] = frozenset()
    def preset_for(self, *, origin: OriginKind, explicit: TrustPreset | None) -> TrustPreset:
        return explicit if explicit is not None else (
            LOW_TRUST_REVIEW if origin in self.low_trust_origins else STANDARD)
```

`SandboxTier` is ordered by capability (`READ_ONLY < REPO_WRITE < REPO_WRITE_NET < UNRESTRICTED`) via a
fixed rank table — "narrower wins" = the lowest rank. `PermissionMode` clamps to the more restrictive of
`{PLAN ≺ DEFAULT}` (low-trust forces `PLAN`).

> Note: `OriginKind` has no `external_pr`/`untrusted_ticket` today (those land with spec 10 intake), so
> the policy keys off existing origins and the **explicit `task.trust_preset` override is the primary
> path**; the policy auto-derive is wired and extensible for when external origins arrive.

## 2. Resolver (`chorus/trust/_resolver.py`) — fail-closed

```python
@dataclass(frozen=True)
class ResolvedTrust:
    sandbox: SandboxTier
    permission_mode: PermissionMode
    net_allowed: bool
    preset: TrustPreset
    boundary: TrustBoundary | None

class TrustDenied(RuntimeError): ...    # fail-closed: the beat must not run

def resolve_trust(*, role_sandbox, task_preset, run_preset=STANDARD, boundary) -> ResolvedTrust:
    # intersect the three layers; the narrowest wins on every axis.
    profiles = [_PROFILES[task_preset], _PROFILES[run_preset]]
    sandbox = min(role_sandbox, *(p.max_sandbox for p in profiles), key=_RANK.__getitem__)
    mode    = _most_restrictive_mode(p.permission_mode for p in profiles)
    net     = all(p.net_allowed for p in profiles)
    preset  = _narrower_preset(task_preset, run_preset)
    if _PROFILES[preset].requires_boundary and not (boundary and boundary.secret_ref_allowlist is not None):
        raise TrustDenied("low_trust_review requires a concrete boundary")
    return ResolvedTrust(sandbox, mode, net, preset, boundary)
```

## 3. Containment (`chorus/trust/_containment.py`) — the five fail-closed conditions

`assert_contained(resolved, *, isolation, env)` raises `TrustDenied` unless **all** hold for a low-trust
beat: sandbox-driver execution (a real sandbox tier, not None), **isolated workspace** (`isolation ==
worktree`), task-in-boundary (the worktree *is* the boundary — guaranteed by isolation), **secret refs in
the allow-list**, and **no inline secrets** (an env value that looks like a raw secret, not an approved
`ref:` handle, is rejected). `standard` short-circuits to ok.

## 4. Data model

```sql
-- migration 0017 (rename-rebuild parity)
ALTER TABLE task ADD trust_preset   TEXT     -- 'standard' | 'low_trust_review' | NULL (→ policy derives)
ALTER TABLE task ADD trust_boundary TEXT     -- JSON {secret_ref_allowlist:[…]} | NULL
```

`Task.trust_preset: TrustPreset | None`, `Task.trust_boundary: dict | None`; repo round-trip. The run
layer is passed in-memory (default `standard`) — no `run` column in this slice.

## 5. Apply-at-materialize (`chorus_harness/_factory.py`)

`materialize` gains a `TrustPolicy` (injected, default empty = no low-trust). Per beat it: resolves the
task's preset (policy/explicit) + boundary → `resolve_trust`; `assert_contained`; **clamps**
`config.sandbox`/`permission_mode` to the resolved ceiling and **scrubs `env`** to the allow-listed refs;
writes the narrowed `sandbox.toml`/overlay. A `TrustDenied` → the beat is **not materialized** (the kernel
blocks the task + opens a recovery card — never runs an uncontained beat).

## 6. Build order (TDD; e2e at each checkpoint)

1. **Models** — `TrustPreset`/`TrustProfile`/`TrustBoundary`/`TrustPolicy` + `_PROFILES` + sandbox rank. *(unit)*
2. **Resolver** — `resolve_trust` intersect + narrower-wins + fail-closed (no-boundary / unsupported /
   conflict → `TrustDenied`). *(unit)*
3. **Containment** — `assert_contained`: no-inline-secrets, secret-ref allow-list, isolated workspace,
   sandbox driver. *(unit)*
4. **Data model** — migration 0017 (`task.trust_preset` + `task.trust_boundary`) + `Task` fields + repo
   round-trip + parity. *(integration)*
5. **Apply-at-materialize** — factory resolves + clamps + scrubs env per beat; `TrustDenied` → no
   materialize. *(e2e: a low_trust task materializes read-only/plan/no-net/scrubbed; a low_trust task with
   no boundary is denied; a standard task is untouched)*
6. **Final e2e + HTML report** — scenario suite → `reports/m1-trust-presets.html`; final gate; update
   06.5 §4. *(e2e)*

Each checkpoint runs ruff + mypy --strict + full pytest.

## Out of scope

`external_pr`/`untrusted_ticket` origins (spec 10 intake), a per-`run` trust column (passed in-memory),
and any dream-side change (the resolved trust applies at chorus's existing materialize boundary).
