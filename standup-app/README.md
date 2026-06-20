# standup-app — watch chorus stand up a repo, live

A tiny, terminal-runnable app that uses **chorus's public facade** (`from chorus import Chorus`) to
drive a company through a real task end to end — and **streams every step to stdout** so you can read
the exact flow:

```
operator → build → hire → submit → [ tick → wake → beat( plan · tools · evaluate ) → DoD → land ] → done
```

`dream` is the agent runtime underneath; this app only ever imports `chorus`. Nothing here spawns a
subprocess or scrapes text — every indented line it prints is a **typed event chorus published** on its
in-process event bus.

## Run it (from the chorus repo root)

```bash
# one-time: install chorus + the sibling dream SDK
uv pip install -e ../dream -e ".[dev]"

# put your model creds in the repo-root .env (the app reads it automatically):
#   AZURE_OPENAI_API_KEY=...
#   AZURE_OPENAI_BASE_URL=https://<resource>.cognitiveservices.azure.com/...
#   AZURE_OPENAI_DEPLOYMENT=<deployment>     # e.g. gpt-5.2

uv run python standup-app/run.py            # solo: one engineer stands up a small `greet` package
uv run python standup-app/run.py --team     # a manager decomposes the goal across two engineers
uv run python standup-app/run.py --org      # 3-level org: a director → 2 team leads → engineers
```

With **no creds set**, it prints the flow it *would* run and exits cleanly — so you can read the shape
first.

## Flags

| flag | effect |
|---|---|
| `--team` | delegate through a manager + 2 engineers (decompose → build → integrate) |
| `--org` | a **3-level** org: a director decomposes into two areas, each delegated to a *team lead* (a manager report) who decomposes again across two engineers; reviewer + pm + analyst round out the workforce. Exercises multi-level delegation and a subtree integrate at **both** manager tiers. Auto-writes a decomposition report at the end. |
| `--report` | write the decomposition report (org chart + task tree) even for `--team`/solo |
| `--task "<text>"` | override the goal text |
| `--pulses N` | max heartbeat pulses before giving up (solo mode; default 18) |
| `--timeout S` | per-beat wall-clock budget in seconds (default 240; the harness default of 90 is too tight to stand a repo up from scratch) |
| `--no-color` | plain ASCII output |

## The decomposition report (`report.py`)

Every run leaves a SQLite ledger (`company.db`) that is the single source of truth for who was hired,
how the goal was split, and how each beat landed. `report.py` reads **only that ledger** (it never
builds a company or calls a model) and renders the run as Markdown — an **org chart** and a
**status-coloured task-decomposition tree** (both as Mermaid graphs), plus an indented text tree, a
roster, a task table, and rollup totals:

```bash
# --org and --report runs auto-write report.md next to the ledger; regenerate it any time:
python standup-app/report.py --db <workdir>/company.db            # print to stdout
python standup-app/report.py --db <workdir>/company.db --out report.md
```

The run prints `ledger db : <path>` at the end so you know which `company.db` to point at.

## The done-gate

The solo task is submitted with an **explicit objective DoD** — `Verifier.command("pytest -q && ruff
check .")`. The kernel runs that command as a real subprocess (the "objective floor") and the task
only flips to `done` when it exits 0. This is deterministic and self-verifying. Submitting *without* a
DoD would instead inherit the engineer role's **reviewed** build, which additionally requires a second
LLM (a reviewer) to sign off — great for real work, but it makes a tiny demo non-deterministic, so the
app pins the objective gate.

## What you'll see

- **Operator actions** (`build` / `hire` / `submit`) printed as you call them.
- **The live event stream** during each heartbeat pulse:
  - `wake queued` / `beat dispatched` — the scheduler picking up ready work,
  - `BEAT STARTED` then the agent's reasoning (`·`), `TOOL …` calls and results, `EVALUATED` —
    chorus *witnessing* dream's typed engine stream,
  - `task todo → in_progress → done` transitions, DoD verdicts, and the merge to company main.
- **A final summary**: the git log and file tree of the company-main repo that now exists — the
  complete repo that was stood up.

Everything throwaway lives under a temp dir (printed at the end); your real repos are never touched.
