# chorus chat — quickstart

Talk to an AI employee in your terminal. Each line you type runs one real "beat" as that employee —
it plans, edits code in its own isolated git branch, runs the tests, and replies.

## 1. One-time setup (from the repo root)

```bash
cd /path/to/chorus
uv pip install -e ../dream -e ".[dev]"      # chorus + the sibling `dream` SDK
```

Add your Azure OpenAI credentials to a gitignored `.env`. These three variables unlock `chat`:

```bash
cat > .env <<'EOF'
AZURE_OPENAI_API_KEY=<your-key>
AZURE_OPENAI_BASE_URL=https://<your-resource>.cognitiveservices.azure.com/...
AZURE_OPENAI_DEPLOYMENT=<your-deployment>     # e.g. gpt-5.2
EOF
```

> `.env` is **authoritative** — if you also have an `AZURE_OPENAI_*` exported in your shell or
> `.zshrc`, chorus uses `.env` and warns you. Cleanest is to keep keys only in `.env`, never in a
> shell profile.

## 2. Start the console

```bash
uv run chorus --db play.db --company acme
```

`--db` persists the ledger; `--company` namespaces the workspace (everything lives under
`./.chorus/work/acme/`). Use the same values to resume later.

## 3. In the `chorus>` console — set up the workspace + an engineer

```
company init            # create the company workspace (.chorus/work/acme/repo, branch main)
hire Ada engineer       # → "hired ada (engineer)"   (the id `ada` is what you chat with)
chat ada                # enter the conversational loop
```

## 4. In chat — each line is one real beat as Ada, on her own branch

```
Create calc.py with add(a, b) returning a + b, and test_calc.py with test_add asserting add(1, 2) == 3. Must pass pytest -q && ruff check .
```

Ada plans → writes the files in an isolated worktree (`chorus/ada`) → runs the done-gate
(`pytest -q && ruff check .`) → replies. Then use the slash commands:

| command | does |
|---|---|
| `/config` | Ada's full harness: tools, permission mode, sandbox tier, worktree + branch |
| `/task` | the current task with its runs + DoD status |
| `/merge` | integrate Ada's branch into the company `main` |
| `/info` | employee + recorded spend |
| `/transcript` | this session's lines |
| `/help` | the slash-command list |
| `/quit` (or `/exit`) | leave chat, back to the console |

## Two things that save headaches

- **Always ask for a test.** The done-gate is `pytest -q && ruff check .`. A task with no test
  (e.g. "write hello.py") fails the gate with *"no tests ran"*. Ask for the file **and** its test.
- **If a turn blocks with `planner parse error (transient)`, press ↑ and re-send.** Each send is a
  fresh beat; it also auto-retries internally.

## Work on a real repo (instead of greenfield)

Point the company at an existing codebase before launching, so the employee branches off real code:

```bash
export CHORUS_COMPANY_SEED=/path/to/your/repo     # a local path, a git clone URL, or a directory
# then `company init` seeds `main` from it.
```

## Other roles

```
hire Rob reviewer       # `/config` shows permission=plan + a read-only sandbox — Rob can't mutate files
chat rob
```

Two engineers (`hire Bob engineer`) work in separate worktrees (`chorus/ada`, `chorus/bob`), fully
isolated until each `/merge`s.

---

See [`src/chorus_cli/README.md`](src/chorus_cli/README.md) for the full command reference (budgets,
approvals, decompose, tick, export/import).
