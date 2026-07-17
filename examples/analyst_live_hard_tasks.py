"""Hard, goal-only Analyst tasks — stress the analyst on research, analysis, and distinguished-engineer
reasoning. Each intent states ONLY the goal: no tools, skills, or integrations are named, so the
analyst must choose its own method (and, ideally, reach for the right skill).

Tasks:
  1. reasoning  — a distinguished-engineer capacity estimate (first-principles, no data/web).
  2. analysis   — a seeded Simpson's-paradox dataset: the aggregate fell while every segment rose.
  3. research   — a current open-web landscape comparison with tradeoffs (needs the web).
  4. predict    — a seeded train/test classification task → PREDICT action → objective Command DoD.

Run all, or one by index:
    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=... TAVILY_API_KEY=...
    python examples/analyst_live_hard_tasks.py [1|2|3|4]
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import sqlite3
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")

from chorus.events import Event, EventKind
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee
from chorus_employee.analyst import analyst_plugin, classify_action
from chorus_harness import EmployeeHarnessFactory

# --- seeders -----------------------------------------------------------------


def _seed_simpson(work: Path) -> None:
    """A textbook mix shift: every channel's CVR rises, the aggregate falls."""
    db = work / "warehouse.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE sessions (week TEXT, channel TEXT, sessions INTEGER, conversions INTEGER)"
    )
    conn.executemany(
        "INSERT INTO sessions VALUES (?,?,?,?)",
        [
            ("2026-W1", "organic", 8000, 400),  # 5.00%
            ("2026-W1", "paid", 2000, 40),  # 2.00%   aggregate W1 = 440/10000 = 4.40%
            ("2026-W2", "organic", 8000, 420),  # 5.25%  (up)
            ("2026-W2", "paid", 12000, 252),  # 2.10%  (up)  aggregate W2 = 672/20000 = 3.36% (down)
        ],
    )
    conn.commit()
    conn.close()


def _seed_predict(work: Path) -> None:
    """A learnable binary classification set: train.csv (with y) + test.csv (with y as answer key)."""
    import numpy as np
    from sklearn.datasets import make_classification

    x, y = make_classification(
        n_samples=700,
        n_features=8,
        n_informative=5,
        n_redundant=1,
        class_sep=1.4,
        random_state=7,
    )
    cols = [f"f{i}" for i in range(x.shape[1])]
    header = ",".join(cols) + ",y"
    rows = np.column_stack([x, y])
    train, test = rows[:560], rows[560:]

    def _write(path: Path, data: np.ndarray) -> None:
        lines = [header]
        for r in data:
            lines.append(",".join(f"{v:.6f}" for v in r[:-1]) + f",{int(r[-1])}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    _write(work / "train.csv", train)
    _write(work / "test.csv", test)


# --- tasks -------------------------------------------------------------------

_TASKS = [
    {
        "key": "reasoning",
        "company": "analyst-hard-reasoning",
        "run": "run-reasoning",
        "seed": None,
        "intent": (
            "Estimate whether a single primary PostgreSQL instance can sustain a read-heavy JSON API "
            "at 50,000 requests per second with a sub-20ms p99, serving rows from a 500 GB table. Show "
            "the reasoning and the numbers behind your answer, identify what will break first as load "
            "grows, and state what you would change to reach the target."
        ),
    },
    {
        "key": "analysis",
        "company": "analyst-hard-analysis",
        "run": "run-analysis",
        "seed": _seed_simpson,
        "intent": (
            "A SQLite warehouse `warehouse.db` with a `sessions` table (week, channel, sessions, "
            "conversions) is in your working directory. Our overall conversion rate fell from the first "
            "week to the second even though nothing on the site changed. Explain what actually happened, "
            "with the exact numbers, and say what we should watch instead."
        ),
    },
    {
        "key": "research",
        "company": "analyst-hard-research",
        "run": "run-research",
        "seed": None,
        "intent": (
            "Compare the three most widely used open-source servers for running large-language-model "
            "inference by real-world adoption, and lay out the tradeoffs that matter when choosing one "
            "for a self-hosted deployment. Every factual claim must carry the source it came from."
        ),
    },
    {
        "key": "predict",
        "company": "analyst-hard-predict",
        "run": "run-predict",
        "seed": _seed_predict,
        "intent": (
            "Files `train.csv` (columns f0..f7 and a binary label `y`) and `test.csv` (the same columns, "
            "with the true `y` present as the answer key) are in your working directory. Build the best "
            "classifier you can from the training data to predict `y`, write your test-row predictions to "
            "`predictions.csv`, and make sure an independent scorer can confirm accuracy on the test rows "
            "clears 0.80."
        ),
    },
]


def _short(value: object, n: int = 200) -> str:
    s = str(value).replace("\n", " / ")
    return s if len(s) <= n else s[:n] + "..."


def _observer(ev: Event) -> None:
    p = ev.payload
    if ev.kind is EventKind.RUN_TOOL_USE:
        print(f"  [tool ->] {p.get('tool')}  {_short(p.get('input'))}")
    elif ev.kind is EventKind.RUN_TOOL_RESULT:
        flag = " (ERROR)" if p.get("is_error") else ""
        print(f"  [tool <-] {p.get('tool')}{flag}")
    elif ev.kind is EventKind.RUN_EVALUATED:
        keys = {k: v for k, v in p.items() if k != "dream_kind"}
        print(f"  [EVALUATED] {_short(keys, 600)}")
    elif ev.kind is EventKind.RUN_DONE:
        print("== beat done ==")


async def _run_task(task: dict, key: str, base: str, dep: str) -> None:
    roles = RoleRegistry.from_plugins(default_roles())
    factory = EmployeeHarnessFactory(
        api_key=key,
        base_url=base,
        deployment=dep,
        company_id=task["company"],
        roles=roles,
        timeout_s=600.0,
    )
    # Clean slate so the planner doesn't collide with a prior run's artefacts.
    workroot = Path("chorus") if Path("chorus").is_dir() else Path(".")
    company_dir = workroot / ".chorus" / "work" / task["company"]
    with contextlib.suppress(Exception):
        if company_dir.exists():
            shutil.rmtree(company_dir)

    mat = factory.materialize(Employee(id="vera", name="Vera", role="analyst"))
    if task["seed"]:
        task["seed"](mat.working_dir)

    verifier = analyst_plugin().dod_generator(task["intent"])
    print("\n" + "=" * 78)
    print(
        f"TASK [{task['key']}]  action={classify_action(task['intent']).value} -> DoD {verifier.kind.value}"
    )
    print(f"intent: {task['intent']}")
    print("=" * 78)

    outcome = await mat.runner.run_task(
        task_id=task["run"],
        intent=task["intent"],
        run_id=task["run"],
        verification=verifier.verification_steps(),
        rubric=verifier.rubric(),
        observer=_observer,
    )
    print(f"\n[{task['key']}] passed = {outcome.passed}")
    print(f"[{task['key']}] summary = {outcome.summary}")
    findings = mat.working_dir / "findings.md"
    if findings.is_file():
        print(f"\n----- [{task['key']}] findings.md -----\n{findings.read_text(encoding='utf-8')}")
    else:
        print(f"[{task['key']}] (no findings.md)")
    for extra in ("predictions.csv", "score.py"):
        f = mat.working_dir / extra
        if f.is_file():
            print(f"[{task['key']}] produced {extra} ({f.stat().st_size} bytes)")


async def main() -> int:
    key = os.environ.get("AZURE_OPENAI_API_KEY")
    base = os.environ.get("AZURE_OPENAI_BASE_URL")
    dep = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (key and base and dep):
        print(
            "skipping: set AZURE_OPENAI_API_KEY / AZURE_OPENAI_BASE_URL / AZURE_OPENAI_DEPLOYMENT"
        )
        return 0

    which = sys.argv[1] if len(sys.argv) > 1 else None
    tasks = _TASKS
    if which is not None:
        idx = int(which) - 1
        tasks = [_TASKS[idx]]

    for task in tasks:
        if task["key"] == "research" and not (
            os.environ.get("TAVILY_API_KEY") or os.environ.get("DREAM_TAVILY_API_KEY")
        ):
            print(f"[{task['key']}] skipped: no TAVILY_API_KEY")
            continue
        await _run_task(task, key, base, dep)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
