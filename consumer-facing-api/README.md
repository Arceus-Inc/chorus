# chorus — consumer-facing API

Everything you need to operate a company of agents on `chorus`, in one place.

| File | What it is |
|---|---|
| [QUICKSTART.md](QUICKSTART.md) | Zero to a running company in five minutes. |
| [CONCEPTS.md](CONCEPTS.md) | The concept map: every idea (employee, task, DoD, decompose, reviewer, budget, approval, trust, routine, the heartbeat) and the one verb that drives it. |
| [examples/](examples/) | One runnable script per concept, plus the full team-goal demo. |

## The 10-second version

```python
from chorus import Chorus
from chorus_harness import EmployeeHarnessFactory   # the execution layer (owns dream + creds)
import dream

factory = EmployeeHarnessFactory(api_key=..., base_url=..., deployment=..., company_id="acme", ...)
org = Chorus.build(
    ledger=ledger, org_repo="./org", memory_repo="./memory", dream=dream,
    beat_runner_for=factory,       # how a beat runs
    landers=factory.landers,       # how its work lands
)

org.hire(name="moe", role="manager")
org.hire(name="eng1", role="engineer", reports_to="moe")
org.hire(name="ria", role="reviewer", reports_to="moe")

task = org.submit("build a login page", assignee="moe")   # the role defines the DoD
org.start()                                               # the concurrent always-on heartbeat
...                                                        # employees work in the background
await org.stop()                                          # signal + drain
org.status()                                              # the company at a glance
```

`Chorus` is **two tiers**: a flat front door anyone can run a company with
(`hire` · `submit` · `start`/`stop` · `status`), and grouped accessors for every niche capability
(`org.governance` · `org.budgets` · `org.trust` · `org.inspect` · `org.routines` · `org.workforce` ·
`org.dod`). Simple on top, complete underneath. (`examples/_common.py` wires the harness for you so
each script stays about one idea.)

## Examples index

| Script | Concept | Needs a model? | Shows |
|---|---|---|---|
| `examples/01_hire_and_submit.py` | employee · task · DoD | **yes** | The smallest company: one engineer, one task, lands `done`. |
| `examples/02_team_goal.py` | the whole org | **yes** | A goal → manager **decomposes** → engineers build **concurrently** (independent) or **in order** (dependent) → **reviewer** reviews → integrate. Driven by `org.start()`. |
| `examples/03_approvals.py` | governance | no | Open a human gate on a task, see the inbox, approve it. |
| `examples/04_budgets.py` | budgets | no | Arm a token-salary cap; the two-gate (warn / pause) model. |
| `examples/05_dod_revision.py` | Definition of Done | no | A manager tightens a task's DoD (a loosen would open a gate). |
| `examples/06_trust.py` | trust | no | Run a task under a narrowed trust posture. |
| `examples/07_routines.py` | recurring work | no | Add a cron routine; list / pause / resume it. |
| `examples/08_inspect.py` | the read model | no | `status()` + `org.inspect.*` — task views, the stuck inbox, the rollup. |

Run any of them standalone:

```bash
# offline ones (03–08) need nothing:
uv run python consumer-facing-api/examples/03_approvals.py

# live ones (01, 02) need an OpenAI-compatible endpoint — see QUICKSTART.md:
set -a; eval "$(grep -E '^AZURE_OPENAI_(API_KEY|BASE_URL|DEPLOYMENT)=' .env)"; set +a
uv run python consumer-facing-api/examples/02_team_goal.py
```

## The four repos (where chorus sits)

```
dream      one task        →  the employee (plan → sprint → evaluate loop)
chorus     one sprint      →  the org of employees that do durable work   ← you are here
horizon    one company     →  strategy / OKRs / direction
lattice    the people      →  employee growth + memory consolidation
```

`chorus` is **dream-free**: it never imports the model layer. `chorus_harness` is the seam that brings
dream + credentials and plugs into `Chorus.build`. That's why the offline examples need no keys.
