---
name: structuring-any-service
description: How to lay out a backend service the way the best-structured repos do — organise by domain, point dependencies inward, thin transport over a service over a repository over a domain model. Framework-agnostic; the "beautiful structure" library so the shipped code reads like Netflix Dispatch / the FastAPI conventions / a clean-arch Go repo, not a flat pile of scripts.
when_to_use: Read before you write the first file of a NEW service, or when reshaping a service whose layout has drifted. It decides WHERE code goes; the verifying-any-stack skill then proves it is clean. A service that passes its tests but is organised by file-type is still hard to extend.
---

# Structuring any service — organise by domain, point dependencies inward

The best-structured backend repos across every stack (the 16k-star FastAPI conventions, Netflix
Dispatch, NestJS feature modules, Go package-by-feature, the Cosmic Python / clean-architecture canon)
converge on the **same five rules**. None of them is a framework — they are how you decide where a line
of code lives. Follow them and the service reads like those repos; ignore them and it works but nobody
can extend it.

## 1. Organise by DOMAIN, not by file-type (the #1 rule)

One package per bounded context — `auth/`, `orders/`, `payments/` — each self-contained. NOT top-level
`routers/`, `models/`, `crud/` folders that scatter one feature across the tree.

```
# GOOD — by domain: a change to "orders" stays in one folder
src/orders/{router,schemas,service,repository,models,exceptions}.py
src/auth/{router,schemas,service,repository,models,exceptions}.py

# BAD — by file-type: touching "orders" edits five folders
src/routers/orders.py  src/models/orders.py  src/crud/orders.py  src/schemas/orders.py
```

Why: the file-type layout works for a 3-endpoint toy and collapses on anything real — every feature
change smears across the tree. Organise by the thing that changes together.

## 2. The standard fileset per module

Every domain package has the same predictable files — predictability *is* the readability. The names
bind per ecosystem; the roles are invariant:

| Role | Python | Node / Nest | Go | Java / Spring |
| --- | --- | --- | --- | --- |
| transport / entrypoint | `router.py` | `*.controller.ts` | `handler/` | `*Controller.java` |
| request/response DTOs | `schemas.py` | `dto/` | (request structs) | `*Dto.java` |
| use-case orchestration | `service.py` | `*.service.ts` | `usecase/` | `*Service.java` |
| data access | `repository.py` | `*.repository.ts` | `repository/` | `*Repository.java` |
| domain model + invariants | `models.py` / `domain.py` | `entities/` | `domain/` (entity) | `*.java` (entity) |
| domain-specific errors | `exceptions.py` | `*.exception.ts` | (error vars) | `*Exception.java` |
| wiring / DI | `dependencies.py` | (module providers) | (constructor wiring) | (`@Configuration`) |

## 3. Dependencies point INWARD — the domain is the centre

```
router / handler  →  service  →  repository  →  domain model
   (transport)        (use case)   (data access)   (pure, depends on NOTHING)
```

The domain model imports no framework, no ORM, no HTTP, no datastore driver. The service depends on an
**abstract** repository (a Protocol/ABC/interface), not a concrete SQL class. This is the shared spine
of Clean / Hexagonal / Onion / Cosmic-Python — one direction, domain innermost.

- **Business logic never lives in the router or the ORM model.** A router that runs a transaction, or a
  model class with a `charge_customer()` method, is the smell. Push it into the service / domain.
- Because the service depends on an abstraction, you test it with a `FakeRepository` in memory — no
  `mock.patch` of string paths (that is [[verifying-any-stack]]'s testability payoff, upstream).

## 4. Thin transport, fat-nowhere — one job per layer

- **Router / handler:** parse the request, call one service method, shape the response. No business
  logic, no SQL. Type the signature; validate at the boundary with a DTO (Pydantic / class-validator /
  struct tags).
- **Service:** orchestrate the use case — the *only* place a workflow lives. Owns the transaction.
- **Repository:** data access only. Takes/returns domain objects, hides the query/ORM.
- **Domain model:** the invariants; make illegal states unrepresentable; one source of truth.
- **Exceptions:** domain-specific per module (`OrderNotFound`, `NotOwner`) — never a bare `Exception`.

## 5. Scale the layering to the service — do NOT onion a trivial endpoint

Layers earn their place; they are not free. A 200-line single-endpoint service does not need a domain/
usecase/repository/handler quadrilogy — a `router` + `service` + `repository` split is plenty, and a
genuinely trivial one-file utility is fine as one well-named module. The Go community pushes back hard
on clean-architecture ceremony for exactly this reason. Match the structure to the blast radius: enough
seams to isolate what changes, no ritual for its own sake. When in doubt, start with router/service/
repository and split further only when a file grows a second reason to change.

## 6. Clean code inside the layers

(Moved here from the operating brief per docs/plans/2026-07-18-hooks-and-briefs-research.md §B —
the brief keeps the judgment, this skill keeps the craft.)

The dependency arrow runs transport/HTTP → service → data-access → domain model; keep tests in
their own place, and give each module **one reason to change**. Write native, idiomatic code for
the stack: fully **type every function signature**, keep functions small and single-purpose (split
anything past ~50 lines), name things well, and state each piece of knowledge once. Catch SPECIFIC
exceptions — never a bare `except` or `except Exception`; a handler that swallows everything hides
the failure you needed to see. Never silence a linter or type-checker finding with an ignore/noqa
comment or by relaxing the config — fix the code.

## Why this is a skill, not a hardcoded template

The rules are invariant; the bindings (which filename, which framework) are per-ecosystem data — the
same reason [[verifying-any-stack]] is a skill and the `code_quality` tool is stack-blind. Fork, don't
invent: adopt the layout the best repo in your stack already uses (FastAPI conventions, Netflix
Dispatch, a clean-arch Go/Nest starter) and diverge from it — never hand-roll a structure per beat.
