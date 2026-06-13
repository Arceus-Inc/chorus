# 09 — Extensibility & portability

Thin core, rich edges. chorus's equivalent of Paperclip's
[`09-extensibility`](../../paperclip-research/09-extensibility.md) + `company-portability` — the role
plugin model, skills, and the **slug-portable company/team package** (Paperclip's bet with the hard
parts already solved).

---

## 1. Role plugins — the primary extension point

The way you extend chorus is by adding **roles**, not by editing the kernel. A role plugin is the
triple (spec 06): `(RoleManifest, DoDGenerator, OutcomeKind)`. Registering one adds an employee type
the kernel never knew about:

```python
chorus.register_role(RolePlugin(
    name="designer",
    manifest=RoleManifest(system_prompt=..., tools=("read_file","write_file","figma"),
                          permission_mode="default", memory_scope="project"),
    dod_generator=lambda intent: AgentReview(reviewer_role="reviewer", rubric=...),
    outcome_kind="design_artifact",
))
```

No scheduler, ledger, or recovery change. This is "the org scales in roles without code changes"
(the M4 proof). The kernel stays ignorant of *what* roles do — it only schedules, checks out,
verifies, and lands.

---

## 2. Skills — playbooks (dream's, reused)

Skills are markdown capability packs (dream's `skills/`): frontmatter eager (a catalogue teaser),
body lazy (loaded on first `use_skill`), four-source layered (bundled/user/project/plugin). A role's
manifest names the skills it may use. chorus does not invent a skills system — it reuses dream's and
attaches skills to roles. (Paperclip's company-skills catalog is the same idea; chorus defers the
catalog/marketplace to Arceus.)

---

## 3. Portable companies/teams — the package format (the platform bet)

This is the artifact that makes chorus a *platform*, not a bespoke build: a **company/team is a
git-importable markdown package**. Transplanted directly from Paperclip's `company-portability.ts`,
which already solved the hard parts:

A **package** (`agentcompanies/v1`) is a directory tree:

```
company/
  README.md            # generated, incl. a Mermaid org chart
  employees/<slug>/role.md      # frontmatter: role, reports_to_slug, memory_scope, skills
  goals/<slug>.md
  projects/<slug>/PROJECT.md
  tasks/<slug>/TASK.md          # seed work
  routines/<slug>.md            # cron templates
  chorus.yaml                   # manifest + declared envInputs
```

The **three mechanisms that make it reusable** (Paperclip's, kept):

1. **Slug identity** — on export, IDs become slugs and `reports_to` becomes **`reports_to_slug`**, so
   the org survives re-import into a fresh workforce (new uuids, same structure).
2. **Portability filtering** — config pruned to defaults; **system-dependent values stripped**
   (absolute commands, non-portable repo URLs, absolute paths classified `system_dependent` and
   omitted with warnings). Only `portable` values ship.
3. **Secret externalization** — **secrets never leave.** Env values are extracted into declared
   `envInputs` (which keys are needed, required/optional, plain-vs-secret — *not the values*). On
   **import**, operator-supplied values re-materialize real secrets; bindings are rewritten to fresh
   refs. Instruction/prompt-template fields can be stripped in an `agent_safe` import mode.

```
chorus export ./acme-eng-team.tar     # serialize workforce -> portable package
chorus import ./acme-eng-team.tar      # re-materialize into a fresh ledger, prompts for envInputs
```

> This is the "portable git-markdown org" belief (B-portability) — and the assessment confirms
> Paperclip already did the slug-identity + env-input externalization + system-dependent stripping,
> so chorus transplants a *solved* design rather than inventing one.

---

## 4. The shared contract layer (the POSIX)

Everything binds to typed contracts, not concrete classes (B0.2). The roots:

- **`dream.contracts`** — `ExecPlanLedger`, `MemoryStore`/`MemoryWriter`, `Tool`, `Provider`, `Hook`,
  `Skill`. The POSIX both chorus and (later) horizon/lattice code against.
- **chorus's own contracts** — `RolePlugin`, `WakeQueue`, `RoutineStore`, `Verifier` (the DoD),
  `OutcomeLander` (role-specific landing), `Inspector` (read model). Each has a default impl + a
  swappable seam.

A consumer extends chorus by implementing a contract (a role plugin, a custom `OutcomeLander`, a
durable `WakeQueue`), never by forking the kernel — which is the OS test from
[00-architecture §5](00-architecture.md).

---

## 5. What stays out of the SDK (→ Arceus)

Paperclip's out-of-process **plugin worker system** (one Node worker per plugin, JSON-RPC, capability
gating, per-plugin DB namespaces, webhook delivery, UI slots) is **Arceus territory**, not the chorus
SDK. The SDK keeps a thin core: roles + skills + the portable package + the contract seams. Heavy,
sandboxed, multi-tenant extensibility belongs to the hosted distribution.
