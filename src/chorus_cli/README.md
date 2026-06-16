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
| **Keys-free** (default) | nothing | every command except `tick` — manage and inspect the ledger, including budgets and approval gates |
| **Keyed** | Azure OpenAI creds | additionally `tick`: run a real beat through dream; spend is priced and the budget gates fire |

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
| `hire <id> <name> <role> [reports_to]` | add an employee |
| `employee <id>` | show one employee |
| `submit [--priority=LEVEL] <id> <intent…>` | create a backlog task (priority: `critical`/`high`/`medium`/`low`) |
| `task <id>` | show a task with its runs and DoD |
| `assign <task_id> <employee_id>` | assign a task (`backlog → todo`) and enqueue its wake |
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
| `quit` / `exit` | leave |

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
```

`--company <id>` sets the scope id for company-wide budgets (default `company`).

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
| `_beats.py` | **the only module that imports dream** — wires the harness, pricing, enforcer, and the sync→async tick bridge (imported lazily, only when keys are present) |

Clean-code conventions: enum-driven (no stringly-typed status), frozen dataclasses, no
getattr/setattr dispatch, conversions at the boundary. Tests live in `tests/cli/`.
