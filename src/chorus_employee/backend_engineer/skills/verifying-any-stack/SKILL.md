---
name: verifying-any-stack
description: How to discover and run a stack's format/lint/type/coverage quality gate — the framework-agnostic know-how behind the code_quality tool, so "the code is clean" is proven per-stack, not assumed.
when_to_use: Read before you report done on any build, right after the tests are green. Use it to discover the quality commands for whatever stack you are in, then run them through code_quality. A build that passes its tests but not its linter/type-checker is not done.
---

# Verifying any stack — discover the quality gate, don't assume it

A green test suite proves behaviour; it does not prove the code is clean, typed, or maintainable — the
§09 *Maintainable* dimension. That dimension is checkable, and you make it checkable the same way you
found the test command: **discover it from the repo, bind to what you find.** The `code_quality` tool is
stack-blind on purpose — it runs the checks *you* hand it. This skill is how you decide what to hand it.

## 1. Discover the repo's own quality gate first (single source of truth)

Before reaching for a default, look for what the repo already declares — a project that ships a lint
command means to be linted that way. Use `glob`/`grep`/`read_file`:

- A **task runner** target: `Makefile` / `justfile` / `Taskfile.yml` with a `lint`, `typecheck`,
  `check`, `fmt`, or `ci` target → run that target (`make check`, `just lint`).
- **`package.json` `scripts`**: `lint`, `typecheck`, `format:check` → `npm run lint`, etc.
- **Declared tool config**: `pyproject.toml` `[tool.ruff]`/`[tool.mypy]`, `setup.cfg`, `.golangci.yml`,
  `.eslintrc*`, `tsconfig.json`, `rustfmt.toml`, `.rubocop.yml` → the tool it configures is the gate.
- The **CI file** (`.github/workflows/*.yml`, `.gitlab-ci.yml`): the lint/type step it runs is the
  contract you must not regress — mirror it.

If the repo declares its gate, that is the single source of truth — run it, don't invent a parallel one.

## 2. If nothing is declared, apply the ecosystem default (reference, not law)

For a cold-start or a repo with no quality config, use the ecosystem's conventional gate. This table is
*reference* — adapt to what is actually installed/available:

| Stack | format (check) | lint | type-check |
| --- | --- | --- | --- |
| Python | `ruff format --check .` | `ruff check .` | `mypy .` (or `pyright`) |
| Go | `gofmt -l .` (empty output = ok) | `go vet ./...` | (compiler; optionally `golangci-lint run`) |
| TypeScript / Node | `npx prettier --check .` | `npx eslint .` | `npx tsc --noEmit` |
| Rust | `cargo fmt --check` | `cargo clippy -- -D warnings` | (compiler) |
| Ruby | — | `rubocop` | `srb tc` (if Sorbet) |
| Java | `mvn -q spotless:check` | `mvn -q checkstyle:check` | (compiler) |

**Cold-start rule:** if the repo has no quality config at all, ADD a minimal one for the stack (e.g. a
tiny `[tool.ruff]` + `[tool.mypy]` in `pyproject.toml`) so the gate is real, repeatable, and re-runnable
by anyone — then run it. A service with no quality gate is not done.

**Install the tool if it is missing — never fake the gate.** The worktree may not ship ruff/mypy/tsc
preinstalled. The sandbox is UNRESTRICTED, so install them (`pip install ruff mypy`, `npm i -D`, …) and
run the real thing. A command that always passes without checking anything — a byte-compiler
(`python -m compileall`, `py_compile`), `true`, `:`, or a bare `echo` — is NOT a formatter, linter, or
type-checker; it proves nothing and `code_quality` rejects it. Passing a gate you declawed is worse
than a red gate: it is a false "clean" on disk.

## 3. Run all three through `code_quality`, and treat red as a blocker

Hand the discovered commands to the tool, tagging each with its **`kind`** — `format`, `lint`, or
`types`. The tool runs each, writes a durable `code_quality/report.json`, and gives you a recovery
contract when something fails:

```
code_quality(checks=[
  {"name": "format", "kind": "format", "command": "ruff format --check ."},
  {"name": "lint",   "kind": "lint",   "command": "ruff check ."},
  {"name": "types",  "kind": "types",  "command": "mypy ."},
])
```

**Cover all three kinds — the tool refuses a partial report.** A green report must mean *format AND
lint AND types* passed, never "only the type-checker ran". Map every stack to the trio:

- **Compiled languages** (Go, Rust, Java, C++): the **build/compiler is your `types` gate** — tag your
  `go build ./...` / `cargo check` / `mvn -q compile` as `kind: "types"`.
- **One tool covering two kinds** (e.g. `ruff` formats *and* lints, `golangci-lint` lints broadly):
  list it under each kind it covers — the check is about the gate KIND proven, not distinct commands.
- **A stack that genuinely lacks a separate formatter or linter:** use the nearest equivalent (e.g.
  `gofmt -l` as format, `go vet` as lint) so all three kinds are honestly represented.

- A red check is a **blocker, not a nit** — fix the flagged files and re-run until clean.
- **Never weaken the gate to pass.** Do not sprinkle `# type: ignore`, `# noqa`, `eslint-disable`, or
  `//nolint` to silence a real finding — a type error is a design flaw; fix the code. Do not relax the
  config to make a red check green.
- Run `code_quality` **before you report done**, alongside `test_evidence` (tests/build) and
  `secret_scan` (safety). Together they are the §09 floor: clean, tested, safe, proven — all on disk.

## Why the tool is stack-blind and this is a skill

The knowledge of *which* commands a stack uses is know-how that changes per ecosystem and per repo —
exactly the thing that must NOT be frozen into a Python `if python … elif go …` table (that is the §03
discover-not-assume violation, in code). So it lives here, as a skill you load on demand, while the tool
stays a pure, stable executor. Discover per repo; the tool just runs and proves.
