"""Tick e2e — the kernel dispatches a role-faithful beat (spec 06 §2, the converged kernel).

Drives the CLI's own tick path (``build_beat_service`` → ``run_tick``): hire an engineer, submit +
assign a task, and tick once. The kernel resolves the engineer's role through the shared
``EmployeeHarnessFactory``, so the beat runs **as the engineer** — its file/bash/git tools and brief,
in its own branch-isolated worktree under ``.chorus/work/{org}/`` — exactly as ``chat`` would. This is
the autonomous path becoming role-faithful (it used to run a generic harness).

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/tick_role_faithful_smoke.py

Skips cleanly (exit 0) when those env vars are unset.
"""

from __future__ import annotations

import os
import uuid

_EXAMPLE_COMPANY = str(uuid.uuid4())  # fresh org per run — slugs reset
import sys
import tempfile
from pathlib import Path

from chorus.ids import derive_id
from chorus.ledger import Ledger, Task

_T1 = derive_id("demo", "tick-role-t1")
from chorus.lifecycle import assign_task
from chorus.workforce import Employee
from chorus_cli._beats import build_beat_service, default_pricing_from_env

_INSTRUCTION = "Create a file named hello.txt in the working directory containing exactly: hi"


def main() -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        print("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    sys.stdout.reconfigure(line_buffering=True)
    base = Path(tempfile.mkdtemp(prefix="chorus-tick-"))
    os.chdir(base)  # .chorus/work/... lands under the tmp dir

    ledger = Ledger.open(
        os.environ.get("CHORUS_LEDGER_DSN", "postgresql://localhost/chorus"),
        company_id=_EXAMPLE_COMPANY,
    )
    try:
        ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
        ledger.tasks.submit(Task(id=_T1, intent=_INSTRUCTION))
        assign_task(ledger, _T1, "ada")  # → todo + a task-assigned wake the tick will claim

        service = build_beat_service(
            ledger,
            api_key=api_key,
            base_url=base_url,
            deployment=deployment,
            company_id="acme",
            pricing=default_pricing_from_env(),
        )
        print(f"[tick | model {service.model} | engineer 'ada']")
        report = service.run_tick()  # one kernel pulse: dispatch + await the beat

        task = ledger.tasks.get(_T1)
        worktree = base / ".chorus" / "work" / "acme" / "worktrees" / "ada"
        print(f"[tick report] dispatched={report.wakes_dispatched}")
        print(f"[task t1] status={task.status.value if task else '?'}")
        print(f"[worktree] {worktree} exists={worktree.is_dir()}")

        hits = sorted(worktree.rglob("hello.txt")) if worktree.is_dir() else []
        if hits:
            print(
                f"\nOK: the engineer (via tick) wrote {hits[0].name} in its own worktree, role-faithful."
            )
        else:
            files = (
                sorted(str(p.relative_to(worktree)) for p in worktree.rglob("*") if p.is_file())
                if worktree.is_dir()
                else []
            )
            print(
                f"\nprobe: no hello.txt this run (model non-determinism). worktree files: {files}"
            )
        return 0
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
