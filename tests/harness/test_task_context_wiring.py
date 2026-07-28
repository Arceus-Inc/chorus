"""Wiring the packet into the beat — role overlays and the persisted sidecar.

No ledger needed: ``write_role_overlays`` and ``write_task_context`` take a packet and a directory,
so the part of PR 3 that decides *what each dream role reads* is testable without Postgres. What is
not covered here is the projection itself inside ``_materialize`` — that needs a live ledger and is
pinned by the integration suite.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from chorus.context import (
    BudgetPosition,
    Contract,
    GoalLink,
    InboxItem,
    PriorBeat,
    TaskContextPacket,
)
from chorus.roles import RoleBeatConfig
from chorus_harness._factory import (
    TASK_CONTEXT_DOC,
    write_role_overlays,
    write_task_context,
    write_task_context_error,
)


def _packet() -> TaskContextPacket:
    return TaskContextPacket(
        task_id="t-1",
        run_id="run-9",
        employee_id="e1",
        role="backend_engineer",
        what=Contract(
            intent="Implement scrubbing",
            dod_kind="command",
            dod_spec="pytest -q",
            artifact_class="pr",
        ),
        budget=BudgetPosition(spent_cents=100, limit_cents=1000, beat_number=2),
        why=(GoalLink(kind="goal", id="g-1", title="Ship the editor", status="active"),),
        prior_beats=(
            PriorBeat(
                run_id="run-1",
                beat_number=1,
                employee_id="e1",
                status="succeeded",
                phase="needs_rework",
                recovery_hint="rework",
                verdict_notes=("base62 alphabet order is wrong",),
            ),
        ),
        inbox=(InboxItem(message_id="m1", from_id="founder", body="prioritise correctness"),),
    )


def _config() -> RoleBeatConfig:
    return RoleBeatConfig(system_prompt="You are a backend engineer.", tools=())


def _overlay(root: Path, role: str) -> str:
    data = tomllib.loads((root / ".harness" / "roles" / f"{role}.toml").read_text("utf-8"))
    return str(data["system_prompt"])


def test_overlays_are_unchanged_without_a_packet(tmp_path: Path) -> None:
    """Flag off must be byte-for-byte the old behaviour, or the rollout is not reversible."""
    write_role_overlays(tmp_path, _config())

    for role in ("planner", "generator", "evaluator"):
        prompt = _overlay(tmp_path, role)
        assert "You are a backend engineer." in prompt
        assert "Task context" not in prompt


def test_each_dream_role_gets_its_own_view(tmp_path: Path) -> None:
    """The three roles need three views, and the difference is load-bearing.

    The planner is toolless and cannot fetch history, so it must be pushed. The evaluator must not
    see it: a gate told "attempt 3, previously rejected" judges the same artifact differently from
    one submitted first, and that path-dependence is exactly what a verifier must not have.
    """
    write_role_overlays(tmp_path, _config(), task_context=_packet())

    planner = _overlay(tmp_path, "planner")
    generator = _overlay(tmp_path, "generator")
    evaluator = _overlay(tmp_path, "evaluator")

    # every role learns what "done" means
    for prompt in (planner, generator, evaluator):
        assert "pytest -q" in prompt
        assert "Ship the editor" in prompt

    # history reaches the two roles that act on it
    assert "base62 alphabet order is wrong" in planner
    assert "base62 alphabet order is wrong" in generator
    # …and never the judge
    assert "base62 alphabet order is wrong" not in evaluator
    assert "Where you left off" not in evaluator

    # the inbox is a generator concern, not a planning or judging one
    assert "prioritise correctness" in generator
    assert "prioritise correctness" not in planner
    assert "prioritise correctness" not in evaluator


def test_the_brief_survives_the_packet(tmp_path: Path) -> None:
    """The packet is appended to the operating brief, never a replacement for it."""
    write_role_overlays(tmp_path, _config(), task_context=_packet())

    prompt = _overlay(tmp_path, "generator")
    assert "You are a backend engineer." in prompt
    assert prompt.index("You are a backend engineer.") < prompt.index("## Task context")


def test_packet_is_persisted_for_inspection(tmp_path: Path) -> None:
    """The on-disk copy is what turns "the model behaved oddly" into a diff."""
    packet = _packet()

    write_task_context(tmp_path, packet)

    written = json.loads((tmp_path / ".harness" / TASK_CONTEXT_DOC).read_text("utf-8"))
    assert written == packet.to_dict()
    assert written["prior_beats"][0]["phase"] == "needs_rework"


def test_a_failed_projection_leaves_a_breadcrumb(tmp_path: Path) -> None:
    """Degradation must be visible; a beat that silently lost its context is a debugging dead end."""
    write_task_context_error(tmp_path, error=ValueError("ledger unreachable"))

    written = json.loads((tmp_path / ".harness" / "task-context-error.json").read_text("utf-8"))
    assert "ValueError" in written["error"]
    assert "ledger unreachable" in written["error"]
