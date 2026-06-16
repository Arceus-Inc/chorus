"""Smoke run — one real beat through dream on Azure OpenAI (manual; needs keys).

Not a test. Run it by hand to watch the domino fall: build a real dream Harness against your Azure
OpenAI endpoint, wrap it in the :class:`~chorus.adapters.DreamBeatRunner` adapter, and execute one
beat end to end.

    AZURE_OPENAI_API_KEY=...
    AZURE_OPENAI_BASE_URL=https://<resource>.openai.azure.com/openai/v1
    AZURE_OPENAI_DEPLOYMENT=<deployment>
    uv run python examples/real_beat.py

Skips cleanly (exit 0) when those env vars are unset, so it is safe to invoke anywhere.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import dream  # type: ignore[import-not-found]

from chorus.adapters import DreamBeatRunner, check_dream_contract

_INTENT = "Reply with the single word DONE and mark the task complete."


async def main() -> int:
    # Fail fast at the composition root if the installed dream's contract has drifted from what chorus
    # was built against (spec 05 §2) — a clear error here beats a mid-beat signature mismatch.
    check_dream_contract(dream)
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        print("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    with tempfile.TemporaryDirectory() as work_dir:
        # Lean harness: no skills / memory / MCP / plugins, so this first end-to-end run has the
        # smallest failure surface and no external dependencies. The trivial intent needs no tools.
        harness = dream.build_harness(
            model=deployment,
            api_key=api_key,
            base_url=base_url,
            working_dir=Path(work_dir),
            skills=False,
            memory=False,
            mcp=False,
            plugins=False,
        )
        runner = DreamBeatRunner(harness)
        print(f"running one beat — intent: {_INTENT!r}")
        outcome = await runner.run_task(task_id="smoke-1", intent=_INTENT)
        print(f"passed={outcome.passed}")
        print(f"summary={outcome.summary}")
        print(f"outcome={outcome.outcome}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
