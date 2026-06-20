"""Throwaway probe: why does gpt-5.4-mini return an empty completion for the planner prompt?

Replicates dream's request shape (chat/completions, tools + tool_choice=auto) and prints the raw
response: finish_reason, content length, and reasoning-token usage — first with NO token cap (dream's
current behavior), then with an explicit max_completion_tokens to test the reasoning-exhaustion theory.
"""

from __future__ import annotations

import json
import os

import httpx

API_KEY = os.environ["AZURE_OPENAI_API_KEY"]
BASE = os.environ["AZURE_OPENAI_BASE_URL"].rstrip("/")
if not BASE.endswith("/openai/v1"):
    BASE = BASE + "/openai/v1"
MODEL = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5.4-mini")
URL = f"{BASE}/chat/completions"

PROMPT = (
    "You are drafting the sprint plan for task task_probe.\n\nUSER INTENT\n-----------\n"
    "Stand up a small Python package called `greet`. Create greet/__init__.py with "
    "hello(name) -> 'Hello, <name>!' and greet/cli.py main(). Add test_greet.py.\n\n"
    "OUTPUT FORMAT\n-------------\nReply with <spec>...</spec> then <ledger>...</ledger>.\n"
)


def call(*, extra: dict, label: str) -> None:
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT}],
        **extra,
    }
    print(f"\n===== {label} =====")
    print(f"request extra: {extra}")
    try:
        r = httpx.post(
            URL,
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json=body,
            timeout=120,
        )
    except httpx.HTTPError as exc:
        print(f"HTTP error: {exc}")
        return
    print(f"status: {r.status_code}")
    if r.status_code != 200:
        print(f"body: {r.text[:2000]}")
        return
    data = r.json()
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    content = msg.get("content") or ""
    print(f"finish_reason: {choice.get('finish_reason')}")
    print(f"content_len: {len(content)}")
    print(f"usage: {json.dumps(data.get('usage'), indent=2)}")
    if content:
        print(f"content[:300]: {content[:300]!r}")


if __name__ == "__main__":
    print(f"model={MODEL}\nurl={URL}")
    # 1) dream's current shape: no token cap.
    call(extra={}, label="no cap (dream default)")
    # 2) explicit generous output budget.
    call(extra={"max_completion_tokens": 4000}, label="max_completion_tokens=4000")
    # 3) generous budget + minimal reasoning effort.
    call(
        extra={"max_completion_tokens": 4000, "reasoning_effort": "low"},
        label="max_completion_tokens=4000 + reasoning_effort=low",
    )

    # The REAL planner request shape: read-only tools + tool_choice=auto.
    _TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file from the worktree.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "git",
                "description": "Run a read-only git command.",
                "parameters": {
                    "type": "object",
                    "properties": {"args": {"type": "array", "items": {"type": "string"}}},
                    "required": ["args"],
                },
            },
        },
    ]
    call(
        extra={"tools": _TOOLS, "tool_choice": "auto"},
        label="TOOLS + tool_choice=auto (dream real shape, no cap)",
    )
    call(
        extra={"tools": _TOOLS, "tool_choice": "auto", "max_completion_tokens": 4000},
        label="TOOLS + tool_choice=auto + max_completion_tokens=4000",
    )
    call(
        extra={"tools": _TOOLS, "tool_choice": "none"},
        label="TOOLS + tool_choice=none (force text)",
    )
