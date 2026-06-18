# chorus — quickstart

Put an AI employee to work from your terminal. You assign a task in plain English; the employee works
**in the background** (a heartbeat ticks it), editing code on its own isolated git branch and running
the tests until the done-gate passes. You watch with `check`.

## 1. One-time setup (from the repo root)

```bash
cd /path/to/chorus
uv pip install -e ../dream -e ".[dev]"      # chorus + the sibling `dream` SDK
```

Add your Azure OpenAI credentials to a gitignored `.env` — these three unlock the employee:

```bash
cat > .env <<'EOF'
AZURE_OPENAI_API_KEY=<your-key>
AZURE_OPENAI_BASE_URL=https://<your-resource>.cognitiveservices.azure.com/...
AZURE_OPENAI_DEPLOYMENT=<your-deployment>     # e.g. gpt-5.2
EOF
```

> `.env` is **authoritative** — if you also have an `AZURE_OPENAI_*` exported in your shell/`.zshrc`,
> chorus uses `.env` and warns. Keep keys in `.env` only, never in a shell profile.

## 2. Start the console

```bash
uv run chorus
```

That's it — no setup commands. The console opens in **minimal mode** with exactly four commands:

| command | does |
|---|---|
| `assign-task <employee> <task…>` | give an employee a task (in plain English) and start it working |
| `check memory \| check ledger \| check <employee>` | watch progress: memory, the ledger, or an employee's latest actions |
| `help` | the command list |
| `quit` | stop the background worker and exit |

On your **first** `assign-task` / `check`, chorus auto-creates one employee — an **`engineer`** named
`employee` — so there's nothing to hire.

## 3. Assign a task and watch it land

```
assign-task employee Add a function add(a, b) to calc.py returning a + b, and a test test_add in test_calc.py asserting add(1, 2) == 3. Must pass pytest -q && ruff check .
```

You'll see something like `assigned task_… -> employee; queued wake_…; heartbeat running`. The
employee now works **on its own** — a background heartbeat dispatches the beat every ~0.5s. Watch it:

```
check ledger          # employees / eligible tasks / queued wakes / running + recent activity
check employee        # the engineer's latest-task actions + its profile
check memory          # where each employee's workspace lives on disk
quit                  # stops the heartbeat and exits
```

You can refer to the employee by name (`employee`) or by role (`engineer`) — role works while there's
exactly one of them.

## 4. Delegate through a manager (one manager + two engineers)

A **manager** doesn't write code — it breaks a goal into subtasks and hands them to its reports, then
integrates the finished work. Give it a one-line goal and watch a whole team move.

**Launch with a file DB and a seeded workspace** (the manager loop runs several beats, so it wants a
persistent ledger + a repo whose tests pass):

```bash
# a tiny seed repo with a passing test, so each engineer's `pytest -q && ruff check .` gate goes green
mkdir -p ~/chorus-seed && cd ~/chorus-seed && git init -q -b main
printf 'def test_smoke():\n    assert True\n' > test_smoke.py
git add -A && git -c user.name=demo -c user.email=demo@x commit -qm seed

cd /path/to/chorus
export CHORUS_COMPANY_SEED=~/chorus-seed
uv run chorus --company team --db team.db        # file DB → the heartbeat ticks on its own
```

**Hire the team and delegate** (at the console; `hire <name> <role> [reports_to]` is a direct verb):

```
hire moe manager
hire ada engineer moe
hire bob engineer moe
assign-task moe Build a small Python math utilities library with add and subtract.
```

That one line is enough — the manager's brief does the planning: it splits the goal into subtasks,
assigns each to a report, and stops. Watch the team work:

```
check ledger          # tasks appearing: the manager's goal + the children it created
check employee moe    # the manager's latest actions
```

Re-run `check ledger` over a minute or two and you'll see the lifecycle:

| stage | what you see |
|---|---|
| manager beat | `moe`'s goal → **blocked** — it delegated (the "parked" state) |
| fan-out | two child tasks appear, assigned to `ada` / `bob` |
| engineers | children go `todo → in_progress → done` (each ships + merges a PR) |
| integrate | once every child is `done`, the kernel marks `moe`'s goal **done** |

The manager decomposes **once**, parks while its reports build and merge, then the completed subtree is
integrated mechanically — no extra prompting. (Requires the M3 manager role; if `hire moe manager`
errors with *"not a registered role"*, you're on a build without it.)

## What's happening under the hood

- **Auto-born employee** — minimal mode hires one `engineer` the first time you act, so you never run
  `hire`.
- **Background heartbeat** — once you assign a task, a daemon thread keeps ticking the kernel, so the
  employee makes progress while you're typing `check`. `quit` stops it cleanly.
- **Works on your current repo** — the company workspace seeds from the directory you launched chorus
  from (override with `CHORUS_COMPANY_SEED=/path/to/repo`). The employee branches off real code on
  `chorus/{employee}` and its edits are isolated there.
- **Done-gate** — a coding task is "done" only when its tests + lint pass (`pytest -q && ruff check .`).

## Two things that save headaches

- **Always ask for a test.** The done-gate runs `pytest`; a task with no test (e.g. "write hello.py")
  fails with *"no tests ran."* Ask for the file **and** its test.
- **A transient `planner parse error` self-retries** — if a task still stalls, just `assign-task`
  again.

## Power-user commands (hidden, still available)

Minimal mode only *lists* four verbs, but the full org console is still there — type the verb
directly. Highlights:

- `chat <employee>` — a conversational loop (one beat per line) instead of fire-and-forget.
- `company init [seed]` — create/seed the company workspace explicitly.
- `hire <name> <role>` · `workforce` · `task <id>` · `budget` · `approval` · `decompose` · …

See [`src/chorus_cli/README.md`](src/chorus_cli/README.md) for the full reference.

## Opt the engineer into extra capabilities

```bash
# before launching: enable Dream skills / MCP / plugins surfaces for the engineer
export CHORUS_ENGINEER_SURFACES=skills,mcp,plugins
```
