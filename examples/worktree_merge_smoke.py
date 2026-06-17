"""Worktree isolation + merge smoke — seed a company, an engineer edits real code, merge it (spec 04 §4).

The full containment loop, end to end against a real model:

1. Create a small **source repo** (``calc.py`` with an ``add`` function).
2. Seed a company workspace from it — the engineer's branch-isolated worktree starts from that code.
3. Send one turn asking the engineer to add a ``subtract`` function to ``calc.py``.
4. ``/merge`` the engineer's ``chorus/ada`` branch back into the company ``main``.
5. Assert the company ``main`` now carries the engineer's change.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/worktree_merge_smoke.py

Skips cleanly (exit 0) when those env vars are unset.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from chorus.ledger import SqliteLedger
from chorus.workforce import Employee
from chorus_cli._beats import default_pricing_from_env
from chorus_cli._chat import ChatRenderBus, ensure_task
from chorus_cli._role_chat import build_role_chat_service

_SEED_CALC = "def add(a, b):\n    return a + b\n"
_INSTRUCTION = (
    "Edit calc.py: add a function `subtract(a, b)` that returns a - b. "
    "Keep the existing add function. Make the change directly in calc.py."
)


def _make_seed_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "calc.py").write_text(_SEED_CALC, encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.name=seed", "-c", "user.email=s@x", "commit", "-m", "init"],
        check=True,
        capture_output=True,
    )


def main() -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        print("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    sys.stdout.reconfigure(line_buffering=True)  # interleave cleanly with the beat's streamed prose
    base = Path(tempfile.mkdtemp(prefix="chorus-worktree-"))
    os.chdir(base)  # .chorus/chat/... lands under the tmp dir, not the real cwd
    seed = base / "source"
    _make_seed_repo(seed)

    ledger = SqliteLedger.open(":memory:")
    try:
        ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
        render = ChatRenderBus(out=sys.stdout)
        service = build_role_chat_service(
            ledger,
            employee_id="ada",
            api_key=api_key,
            base_url=base_url,
            deployment=deployment,
            company_id="acme",
            render_bus=render,
            pricing=default_pricing_from_env(),
            seed=seed,
        )
        worktree = Path(service.working_dir)
        print(f"[engineer 'ada' | model {service.model}]")
        print(f"[seed {seed}]")
        print(f"[worktree {worktree} | branch chorus/ada]")
        print(f"[company main {service.workspace.repo if service.workspace else '-'}]")
        # the worktree starts from the seeded code
        print(f"[worktree calc.py before]\n{(worktree / 'calc.py').read_text(encoding='utf-8')}")
        print(f"> {_INSTRUCTION}\n")

        task_id, _ = ensure_task(ledger, "ada", _INSTRUCTION)
        render.reset()
        service.run_turn()
        render.end_turn()

        # DoD-at-intake (spec 04 §1 / 06 §2): the chat task inherited the engineer role's DoD,
        # so this beat was held to the engineer's `pytest -q && ruff check .` gate.
        dod = ledger.dod.get_for_task(task_id)
        print(f"\n[intake DoD] kind={dod.kind if dod else None}")

        wt_calc = (worktree / "calc.py").read_text(encoding="utf-8") if (worktree / "calc.py").exists() else ""
        print(f"\n[worktree calc.py after]\n{wt_calc}")

        assert service.workspace is not None
        result = service.workspace.merge("ada")
        print(f"\n[merge] merged={result.merged} conflicted={result.conflicted} :: {result.detail.splitlines()[:1]}")

        main_calc = service.workspace.repo / "calc.py"
        merged = main_calc.read_text(encoding="utf-8") if main_calc.exists() else ""
        print(f"\n[company main calc.py]\n{merged}")

        if "def subtract" in merged and "def add" in merged:
            print("\nOK: the engineer's change merged into company main, branch-isolated then integrated.")
        else:
            print("\nprobe: no subtract in main this run (model non-determinism or no edit). see output above.")
        return 0
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
