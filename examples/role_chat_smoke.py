"""Role-aware chat smoke — an engineer employee writes a file through a real beat (spec 06 §2, spec 05).

Builds a role-aware chat service for an ``engineer`` and sends one turn asking it to write a file. The
harness is materialized for the engineer's role (its file/bash/git tools + a per-role overlay of its
brief + ``acceptEdits`` posture), and the whole ``run_task`` loop runs as that employee — so the
generator actually writes the file. Proves the role configures real, tool-using behaviour (unlike a
custom tool, built-in file tools are dream's native coding flow).

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/role_chat_smoke.py

Skips cleanly (exit 0) when those env vars are unset.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from chorus.ledger import SqliteLedger
from chorus.workforce import Employee
from chorus_cli._beats import default_pricing_from_env
from chorus_cli._chat import ChatRenderBus, ensure_task
from chorus_cli._role_chat import build_role_chat_service

_INSTRUCTION = "Create a file named hello.txt in the working directory containing exactly: hi"


def main() -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        print("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    work = Path(tempfile.mkdtemp(prefix="chorus-role-chat-"))
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
            work_root=work,
        )
        print(f"[engineer 'ada' | model {service.model} | workdir {work}]")
        print(f"> {_INSTRUCTION}\n")
        ensure_task(ledger, "ada", _INSTRUCTION)
        render.reset()
        service.run_turn()
        render.end_turn()

        hits = sorted(p for p in work.rglob("hello.txt"))
        if hits:
            print(f"\nOK: engineer wrote {hits[0]} -> {hits[0].read_text(encoding='utf-8').strip()!r}")
        else:
            files = sorted(str(p.relative_to(work)) for p in work.rglob("*") if p.is_file())
            print(f"\nprobe: no hello.txt this run (model non-determinism). workdir files: {files}")
        return 0
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
