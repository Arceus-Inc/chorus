"""Unit + integration: beat raw_record persists into ledger agent_session (SoT)."""

from __future__ import annotations

import json

import pytest

from chorus.heartbeat import Scheduler, Wake, WakeReason
from chorus.heartbeat._beat import BeatDisposition, BeatOutcome
from chorus.ledger import (
    ConversationRole,
    Ledger,
    Task,
    TaskStatus,
    ensure_open_session,
    load_transcript,
    parse_raw_record,
    persist_beat_account,
    resume_intent,
)
from chorus.outcomes import Verifier
from chorus.roles import RoleRegistry, default_roles
from chorus.testing import uid
from chorus.workforce import Employee, LedgerWorkforce

pytestmark = pytest.mark.integration


def test_parse_raw_record_maps_text_and_tools() -> None:
    raw = "\n".join(
        [
            json.dumps({"kind": "role.text", "text": "looking"}),
            json.dumps(
                {
                    "kind": "role.tool.start",
                    "tool": "grep",
                    "tool_use_id": "tu1",
                    "input": {"pattern": "bug"},
                }
            ),
            json.dumps(
                {
                    "kind": "role.tool.result",
                    "tool_use_id": "tu1",
                    "content": "src/a.py:1",
                    "is_error": False,
                }
            ),
            json.dumps({"kind": "planner.run.completed"}),
        ]
    )
    delta = parse_raw_record(raw, session_id="sess", start_seq=0)
    assert len(delta.messages) == 1
    assert delta.messages[0].role is ConversationRole.ASSISTANT
    assert delta.messages[0].content[0]["text"] == "looking"
    assert len(delta.tool_starts) == 1
    assert delta.tool_starts[0].tool_name == "grep"
    assert delta.tool_completions == (("tu1", "src/a.py:1", False),)


class _Beat:
    def __init__(self) -> None:
        self.intents: list[str] = []

    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        verification: object = (),
        rubric: object = "",
        observer: object = None,
        run_id: str | None = None,
    ) -> BeatOutcome:
        self.intents.append(intent)
        raw = "\n".join(
            [
                json.dumps({"kind": "role.text", "text": f"handled:{intent[:24]}"}),
                json.dumps(
                    {
                        "kind": "role.tool.start",
                        "tool": "read_file",
                        "tool_use_id": f"t-read-{len(self.intents)}",
                        "input": {"path": "TODO.md"},
                    }
                ),
                json.dumps(
                    {
                        "kind": "role.tool.result",
                        "tool_use_id": f"t-read-{len(self.intents)}",
                        "content_preview": "todo body",
                    }
                ),
            ]
        )
        return BeatOutcome(
            passed=True,
            disposition=BeatDisposition.PASSED,
            summary="ok",
            raw_record=raw,
            model="test-model",
            input_tokens=10,
            output_tokens=5,
            cost_cents=3,
        )


async def test_scheduler_persists_raw_record_into_ledger(ledger: Ledger) -> None:
    emp = "ada"
    task_id = uid("t-session")
    ledger.employees.create(Employee(id=emp, name="Ada", role="engineer"))
    ledger.tasks.submit(
        Task(id=task_id, intent="fix auth", status=TaskStatus.TODO, assignee_employee_id=emp)
    )
    ledger.dod.create(task_id, Verifier.command("true"))
    beat = _Beat()
    sched = Scheduler(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        beat_runner=beat,
        roles=RoleRegistry.from_plugins(default_roles()),
        max_concurrent_runs=1,
    )
    ledger.wakes.enqueue(
        Wake(
            id=uid("w1"),
            employee_id=emp,
            reason=WakeReason.MANUAL,
            payload={"task_id": task_id},
        )
    )
    await sched.tick_once()
    await sched.drain()

    session = ledger.agent_sessions.latest_for_task(task_id)
    assert session is not None
    messages = load_transcript(ledger, session.id)
    assert any("handled:" in str(m.content) for m in messages)
    tools = ledger.agent_sessions.tool_calls_for(session.id)
    assert len(tools) == 1
    assert tools[0].tool_name == "read_file"
    assert tools[0].result_content == "todo body"
    assert session.cost.input_tokens >= 10


async def test_second_beat_intent_includes_ledger_transcript(ledger: Ledger) -> None:
    """Cross-beat resume: prior ledger rows appear in the next beat's intent."""
    emp = "ada"
    task_id = uid("t-resume")
    ledger.employees.create(Employee(id=emp, name="Ada", role="engineer"))
    ledger.tasks.submit(
        Task(
            id=task_id,
            intent="continue work",
            status=TaskStatus.TODO,
            assignee_employee_id=emp,
        )
    )
    session = ensure_open_session(
        ledger,
        employee_id=emp,
        task_id=task_id,
        dream_session_key=f"task:{task_id}",
        model="",
        system_prompt=None,
        run_id=None,
    )
    persist_beat_account(
        ledger,
        session.id,
        raw_record=json.dumps({"kind": "role.text", "text": "earlier reasoning"}),
    )
    assert "earlier reasoning" in resume_intent(ledger, session.id, "continue work")

    beat = _Beat()
    sched = Scheduler(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        beat_runner=beat,
        roles=RoleRegistry.from_plugins(default_roles()),
        max_concurrent_runs=1,
    )
    ledger.wakes.enqueue(
        Wake(
            id=uid("w1"),
            employee_id=emp,
            reason=WakeReason.MANUAL,
            payload={"task_id": task_id},
        )
    )
    await sched.tick_once()
    await sched.drain()
    assert beat.intents
    assert "Prior session transcript" in beat.intents[0]
    assert "earlier reasoning" in beat.intents[0]
