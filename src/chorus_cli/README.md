# chorus CLI

An interactive console over the chorus durable ledger. It drives the parts of the kernel that work
end-to-end today — seed a workforce, submit and assign tasks, pass messages, set and enforce
**budgets**, open and resolve **approval gates**, inspect state, and (with provider keys) run a real
beat through dream and watch the budget gates fire.

Everything is one SQLite ledger. State persists across sessions when you point `--db` at a file.

---

## Setup

chorus depends on the sibling [`dream`](../../../dream) SDK. From the repo root, install both editable
with [`uv`](https://docs.astral.sh/uv/):

```bash
uv pip install -e ../dream -e .[dev]
```

Run the console (the `chorus` script is registered in `pyproject.toml`):

```bash
uv run chorus                       # opens ./chorus.db
uv run chorus --db /tmp/play.db     # a specific ledger
uv run chorus --db :memory:         # a throwaway ledger (nothing persists)
```

Equivalent: `uv run python -m chorus_cli`.

You'll get a prompt:

```
chorus console — type 'help' for commands, 'quit' to exit
chorus>
```

`help` lists everything; `help <command>` shows one command's usage. Multi-word values take quotes:
`submit t1 "ship the docs"`. A failing command prints an `error:` line and the loop keeps going.

---

## Two modes

| Mode | Needs | What works |
|------|-------|------------|
| **Keys-free** (default) | nothing | every command except `tick` / `chat` — manage and inspect the ledger, including budgets and approval gates |
| **Keyed** | Azure OpenAI creds | additionally `tick` and `chat`: run real beats through dream; spend is priced and the budget gates fire |

To enable `tick`, set three variables (export them, or drop them in a `.env` — see
[Credentials](#credentials)):

```
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_BASE_URL=https://<resource>.cognitiveservices.azure.com/openai/v1
AZURE_OPENAI_DEPLOYMENT=<deployment>
```

Without them, `tick` simply prints how to enable it.

---

## Commands

### Workforce & tasks

| Command | Does |
|---|---|
| `hire <name> <role> [reports_to]` | add an employee (id is the name's slug; enforces the org invariants) |
| `workforce` | list the org — every employee with role, manager, and status |
| `employee <id>` | show one employee |
| `terminate <id>` | irreversibly terminate an employee (cancels its runs + drops queued wakes) |
| `pause <id>` / `resume <id>` | hold / release an employee — the invokability gate skips a paused identity |
| `export <dir>` / `import <dir>` | serialize the org to / from a portable git-markdown tree (`<dir>/employees/<slug>/role.md`) |
| `company` / `company init [seed]` | show or create the company workspace (`.chorus/work/{company}/repo`, branch `main`) employees' worktrees branch from |
| `submit [--priority=LEVEL] <id> <intent…>` | create a backlog task (priority: `critical`/`high`/`medium`/`low`) |
| `task <id>` | show a task with its runs and DoD |
| `dod set <task_id> <command\|human_approval\|agent_review> [args…]` | attach a typed Definition of Done |
| `assign <task_id> <employee_id>` | assign a task (`backlog → todo`) and enqueue its wake |
| `decompose <parent_id> <child_intent…>` | manager fan-out: create a gated child; refused (parent `blocked` + recovery) past the delegation depth cap (default 5) |
| `eligible [limit]` | tasks ready to dispatch |

### Coordination & inspection

| Command | Does |
|---|---|
| `wakes` | queued wakes |
| `message <to_employee_id> <body…>` | deliver a message and wake the recipient |
| `inbox <employee_id>` | an employee's unread mailbox |
| `cost <employee_id>` | an employee's recorded spend (cents) |
| `schema` | the ledger schema version |

### Budgets (spec 04 §3)

| Command | Does |
|---|---|
| `budget` / `budgets` / `budget list` | dashboard: every cap with live spend, % used, window, and status |
| `budget set company <cents> [--warn=N] [--window=W]` | set/raise a company-wide cap |
| `budget set employee <id> <cents> [--warn=N] [--window=W]` | set/raise an employee cap (upsert) |
| `budget raise <policy_id> <cents>` | raise a cap above observed spend and **resume** a paused scope |
| `budget dismiss <incident_id>` | decline to resume — the scope stays paused |

- `--warn=N` — soft-warning threshold percent (default `80`).
- `--window=W` — `monthly` (default), `weekly`, `rolling_30d`, or `total`.
- **Status** in the dashboard: `ok` → `warn` (≥ warn%) → `over` (≥ cap) → `paused` (a hard incident
  is open; a human must `budget raise` to resume).

### Approvals & governance (spec 04 §5)

A pending **approval** is a human gate: open one on a task (it parks the task `blocked`), then
resolving it moves the task. An approval carries its **gate kind**:

| Command | Does |
|---|---|
| `approval` / `approvals` / `approval list` | list pending gates (subject, gate kind, reason) |
| `approval open <task_id> <acceptance\|authorization> <reason…>` | open a gate — parks the task `blocked` |
| `approval approve <approval_id>` | approve — moves the task per its gate |
| `approval deny <approval_id>` | deny — moves the task per its gate |

| Gate kind | approve | deny |
|---|---|---|
| **acceptance** — the approval *is* the task's done-ness (a HumanApproval DoD) | task → `done`, its dependents unblock | task stays `blocked` (DoD recorded `failed`) |
| **authorization** — sign off *before* the work proceeds | task → `todo` + the assignee is woken | task → `cancelled` |

Decisions are recorded as the `operator`. (Budget hard-stops also raise approvals — those are resolved
with `budget raise` / `budget dismiss`, not these verbs.)

### The kernel

| Command | Does |
|---|---|
| `tick` | one kernel pulse: recover → cron → monitors → dispatch, then await the beat (needs keys) |
| `chat <employee_id>` | converse with an employee — each line runs a real beat **as that employee** (needs keys); `/help` inside lists the slash commands. See [Chat](#chat--converse-with-an-employee) |
| `quit` / `exit` | leave |

---

## Chat — converse with an employee

`chat <employee_id>` is a conversational front door to a single employee (needs keys). Where the rest
of the console is verb-driven, chat is a back-and-forth: every line you type is recorded as a message,
auto-promoted into a task, and run through one real beat — the whole dream `run_task` loop
(planner → generator → evaluator) — **as that employee**. Its reply streams back live, and a one-line
verdict footer (task status, run status, spend) closes each turn.

### The employee *is* its config

An employee runs as a fully configured dream harness, materialized from its **role**. Every harness
knob comes from the role's config — the system prompt (its operating brief), the tool allow-list, the
permission posture, memory + a working-memory scratchpad, the model, the turn budget, MCP/plugins, and
the worktree isolation posture. The Engineer, for example, is defined one-module-per-component in
[`src/chorus_employee/engineer/`](../chorus_employee/engineer/) and ships file/bash/git tools under an
`acceptEdits` posture with a `pytest -q && ruff check .` Definition of Done. Run `/config` to see the
live spec:

```
ada> /config
  employee:    ada (engineer)
  model:       gpt-5.2
  max_turns:   12
  permission:  acceptEdits
  memory:      project +working-scratchpad
  isolation:   worktree → branch chorus/ada
  tools:       read_file, write_file, run_command, git
  skills:      (none)
  mcp:         off
  plugins:     off
  working_dir: .chorus/work/acme/worktrees/ada
```

### Branch-isolated worktrees

Employees of an org share one workspace under `.chorus/work/{org}/`, but each works **confined to its
own git worktree** on branch `chorus/{employee}` — so two employees never collide. (dream confines its
tools to the harness working dir, so making that dir a per-employee worktree is what isolates the
edits.) The **same** worktree backs an employee whether you reach it through `chat` or the kernel
dispatches it via `tick` — one identity, one workspace per employee.

```
.chorus/work/{company}/
  repo/                  canonical, branch main — the company source of truth
  worktrees/ada/         branch chorus/ada — Ada works here
  worktrees/bob/         branch chorus/bob — isolated from Ada
```

`/merge` integrates an employee's branch back into the company `main` (it snapshots any uncommitted
work first; a conflict is reported, not applied).

### Seed from a real repo

By default the company `main` starts empty. Point it at a **real codebase** so employees branch off
actual code — set `CHORUS_COMPANY_SEED` to a git repo path, a clone URL, or a plain directory:

```
CHORUS_COMPANY_SEED=/path/to/my-repo
```

Seeding happens once, when the company workspace is first created (clear `.chorus/work/{company}/` to
reseed).

`tick` / `chat` create the workspace lazily on the first beat, but you can also create it **explicitly**
up front with the `company` command — handy to seed it before anyone runs, or just to see where it is:

| Command | Does |
|---|---|
| `company` | show the company workspace: id, root path, whether it's created |
| `company init [seed]` | create `.chorus/work/{company}/repo` on branch `main` (idempotent); `seed` is a repo path / clone URL / directory, falling back to `CHORUS_COMPANY_SEED` |

### Slash commands

| Command | Does |
|---|---|
| `/help` | the slash list |
| `/info` | employee, model, working dir, active task |
| `/config` | the employee's full harness config (every component) |
| `/merge` | merge this employee's isolated worktree into company `main` |
| `/task` | the current/last task with its runs |
| `/transcript` | this session's lines |
| `/quit` · `/exit` | leave chat (back to the console) |

Anything else is sent to the employee as a turn.

### Walkthrough — an engineer edits real code, then merges (needs keys)

```
# point the company at a repo to work on (a path, a clone URL, or a directory)
export CHORUS_COMPANY_SEED=/path/to/my-repo

uv run chorus --db /tmp/play.db --company acme
company init                                     # create+seed the workspace up front (optional)
hire Ada engineer                                # the Engineer role = a complete harness config; id `ada`
chat ada
ada> /config                                     # the harness ada runs as
ada> add a subtract(a, b) function to calc.py    # one real beat, isolated on branch chorus/ada
ada> /merge                                      # integrate ada's branch into company main
ada> /quit
```

Continuity is the employee's **memory**: the harness is built with a stable per-employee working dir,
so it remembers earlier turns across a session.

---

## How the DoD enforces (spec 04 §1)

A task's `dod` is the typed gate its beat must clear — `done` is never self-report. **DoD at intake:**
a task with no explicit `dod set` inherits its **assignee role's** DoD when the beat is dispatched — so
a backend engineer (in `chat` or via `tick`) is always held to its declared build gate without you
setting one; a manual `dod set` always wins.

- **`command`** — the shell check rides into the beat as dream's verification (dream runs it and
  gates on it). `done` means the plan completed **and** the command exited 0.
- **`human_approval`** — when the beat completes, chorus opens an **acceptance approval** instead of
  finishing; the task sits `blocked` until someone runs `approval approve` (then it's `done`).
- **`agent_review`** — the built-in, read-only system verifier inspects the assignee's worktree and
  records an independent verdict without adding a Reviewer employee to the workforce.
- **`reviewed_build`** — combines independent system verification with the deterministic build check.

**Self-repair ladder** (Command DoD): a failed check re-wakes the same employee to retry (the task
stays `todo`), up to a bounded budget; once spent, the task goes `blocked` with a `recovery_action`
for a human.

---

## How budgets enforce

Budgets are derived state — no stored "paused" flag:

- **paused** = an open *hard* `budget_incident` (persists across window rollover).
- **over** = live spend ≥ the cap (recomputed from `cost_event` rows, never banked).

When you `tick` a real beat, dream meters its tokens, chorus prices them into `cost_cents`, the
scheduler records a `cost_event`, and the two gates run:

- **Gate 1 (pre-dispatch):** a paused or over scope is never dispatched — the wake is released and
  counted as `gated_by_budget` in the tick report.
- **Gate 2 (on spend):** crossing `warn%` raises a soft incident (notify); crossing the cap raises a
  **hard** incident, pairs an approval, pauses the scope, and kills its in-flight runs + queued wakes.

Resolution is human-only: `budget raise` (the new cap must exceed observed spend) resumes the scope;
`budget dismiss` denies the approval and leaves it paused.

### Pricing

So spend has a value, beats are priced with whole **cents per million tokens**, overridable via env:

```
CHORUS_PRICE_INPUT_CENTS_PER_MTOK=125     # default (illustrative GPT-5-class)
CHORUS_PRICE_OUTPUT_CENTS_PER_MTOK=1000   # default
```

Replace the defaults with your provider's authoritative numbers.

---

## Credentials

The console loads a `.env` from the working directory (override with `--env-file PATH`) before wiring
the beat service. Already-set environment variables win over the file. `.env` is gitignored.

```
# .env
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_BASE_URL=https://<resource>.cognitiveservices.azure.com/openai/v1
AZURE_OPENAI_DEPLOYMENT=gpt-5.2
CHORUS_PRICE_INPUT_CENTS_PER_MTOK=125
CHORUS_PRICE_OUTPUT_CENTS_PER_MTOK=1000
CHORUS_COMPANY_SEED=/path/to/my-repo      # optional: seed chat employees' worktrees from a real repo
```

`--company <id>` sets the scope id for company-wide budgets **and** the chat workspace root
(`.chorus/work/<id>/`); default `company`.

---

## Walkthroughs

### Manage an org and its budgets (keys-free)

```
hire alice Alice engineer
budget set employee alice 500 --warn=60
budget set company 100000
budget
submit t1 "ship the onboarding docs"
assign t1 alice
eligible
message alice "board is asking about the docs"
inbox alice
```

### Watch a budget gate fire (needs keys)

```
hire alice Alice engineer
budget set employee alice 1          # a 1-cent cap — any real beat blows it
submit t1 "Reply with the single word DONE."
assign t1 alice
tick                                 # runs the beat; its cost trips the hard stop
budget                               # alice now shows 'paused' with an open hard incident
task t1
tick                                 # the next dispatch is gated_by_budget
budget raise <policy_id> 100000      # resume
```

### Sign off a task with an approval gate (keys-free)

```
hire alice Alice engineer
submit t1 "write the launch spec"
assign t1 alice
approval open t1 acceptance "board signs off the spec"   # t1 is now blocked
approvals                                                # see the pending gate + its id
approval approve <approval_id>                           # t1 → done; dependents unblock
task t1
```

Use `authorization` instead of `acceptance` to gate *before* the work runs (approve → `todo`,
deny → `cancelled`).

---

## Architecture (for contributors)

Small, focused modules under `src/chorus_cli/`:

| Module | Role |
|---|---|
| `__main__.py` | argparse entry, `.env` loading, composition (ledger + optional beat service) |
| `_repl.py` | the read-eval loop + one-line `dispatch` (input/output injected for tests) |
| `_registry.py` | `Command` + `CommandRegistry` — the decorator-built verb table |
| `_commands.py` | every command handler (registered via `@REGISTRY.command`) |
| `_context.py` | `CliSession`, `CommandContext`, the `LoopSignal` enum, the `BeatService` protocol |
| `_render.py` | `Console` — lines / key-value / tables, TTY-gated colour |
| `_env.py` | the `.env` loader |
| `_beats.py` | wires the `tick` beat service (scheduler over the org harness factory) + pricing/enforcer; reads `CHORUS_COMPANY_SEED` |
| `_chat.py` | the conversational `chat` loop — render bus, auto-promote, slash commands (`/config`, `/merge`, …) |
| `_role_chat.py` | builds the chat beat service over the shared harness factory |

`tick` and `chat` materialize beats through the *same* role-faithful harness factory —
[`chorus_harness.EmployeeHarnessFactory`](../chorus_harness/) (the one place that imports dream). The
employee config + isolation live in core (dream-free): an employee's harness identity is its **role**
([`src/chorus_employee/`](../chorus_employee/) — projected through `chorus.roles.RoleBeatConfig`), and
branch-isolated worktrees are [`chorus.workspace.CompanyWorkspace`](../chorus/workspace/).

Clean-code conventions: enum-driven (no stringly-typed status), frozen dataclasses, no
getattr/setattr dispatch, conversions at the boundary. Tests live in `tests/cli/`.
