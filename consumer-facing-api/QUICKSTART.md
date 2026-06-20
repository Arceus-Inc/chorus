# Quickstart

From nothing to a running company in five minutes.

## 1. Install

`chorus` is a Python 3.11+ workspace. From this repo:

```bash
uv sync
```

The offline examples (03–08) need only this. The live examples (01, 02) also need a model.

## 2. Credentials (live examples only)

`chorus` itself is model-free; the **execution layer** (`chorus_harness`) brings the model. Any
OpenAI-compatible chat endpoint works (OpenAI, Azure's `/openai/v1` path, vLLM, gateways). The examples
read three environment variables:

```bash
export AZURE_OPENAI_API_KEY="..."
export AZURE_OPENAI_BASE_URL="https://your-endpoint/openai/v1"
export AZURE_OPENAI_DEPLOYMENT="gpt-5.2"      # the model / deployment name
```

Or keep them in a `KEY=VALUE` file and point `CHORUS_ENV_FILE` at it (defaults to `./.env`):

```bash
export CHORUS_ENV_FILE=.env
```

Missing creds? The live examples print a one-line skip and exit 0 — they never crash.

## 3. Run an offline concept (no keys)

```bash
uv run python consumer-facing-api/examples/03_approvals.py
```

```
submitted task_…: todo
opened gate ap_… → task is now blocked
open inbox: ['ap_…']
approved by ceo → task is now todo
open inbox: []
```

## 4. Run the smallest live company

```bash
set -a; eval "$(grep -E '^AZURE_OPENAI_(API_KEY|BASE_URL|DEPLOYMENT)=' .env)"; set +a
uv run python consumer-facing-api/examples/01_hire_and_submit.py
```

One engineer, one task; the heartbeat single-steps it to `done` and the engineer's build lands on
company main.

## 5. Run the whole team

```bash
uv run python consumer-facing-api/examples/02_team_goal.py
```

A goal handed to the manager: it decomposes, two engineers build in parallel where the work is
independent and in order where it depends, a reviewer reviews, the manager integrates — all under
`org.start()`.

## The shape of your own code

```python
from chorus import Chorus
from chorus_harness import EmployeeHarnessFactory
import dream

factory = EmployeeHarnessFactory(api_key=..., base_url=..., deployment=..., company_id="acme", ...)
org = Chorus.build(ledger=ledger, org_repo="./org", memory_repo="./memory", dream=dream,
                   beat_runner_for=factory, landers=factory.landers)

org.hire(name="moe", role="manager")
task = org.submit("ship the feature", assignee="moe")
org.start()
...                 # do other things; the org works in the background
await org.stop()
```

`examples/_common.py` (`live_org` / `offline_org`) does this wiring for the examples — read it to see
the full `Chorus.build` call, then lift it into your app.

## Concurrency

`org.start()` runs up to `Caps.max_concurrent_runs` beats at once (default 4). Bump it at build time:

```python
from chorus import Caps
org = Chorus.build(..., caps=Caps(max_concurrent_runs=8))
```
