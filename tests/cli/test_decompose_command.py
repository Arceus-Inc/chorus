"""The console ``decompose`` verb — manager fan-out, depth-capped (spec 06 §4).

Drives the delegation depth cap end to end: a normal decompose creates a child; a decompose of a
task already at the cap is refused, the task is blocked, and a recovery is opened.
"""

from __future__ import annotations

import io

import pytest

from chorus.ledger import Ledger, Task
from chorus.ledger._models import TaskStatus
from chorus.testing import uid
from chorus_cli import CliSession, Console, LoopSignal, dispatch
from chorus_cli._commands import REGISTRY

pytestmark = pytest.mark.integration


def _run(line: str, session: CliSession) -> tuple[LoopSignal, str]:
    buffer = io.StringIO()
    signal = dispatch(
        line, session=session, console=Console(out=buffer, colour=False), registry=REGISTRY
    )
    return signal, buffer.getvalue()


def test_decompose_creates_a_child(session: CliSession, ledger: Ledger) -> None:
    ledger.tasks.submit(Task(id=uid("src"), intent="big"))  # depth 0
    _, out = _run(f"decompose {uid('src')} split off a piece", session)
    assert f"decomposed {uid('src')} ->" in out


def test_decompose_at_cap_is_refused_and_blocks_the_task(
    session: CliSession, ledger: Ledger
) -> None:
    ledger.tasks.submit(Task(id=uid("src"), intent="big", request_depth=5))  # at the default cap
    _, out = _run(f"decompose {uid('src')} one hop too far", session)
    assert "depth cap" in out
    assert ledger.tasks.get(uid("src")).status is TaskStatus.BLOCKED  # type: ignore[union-attr]
    assert ledger.recovery_actions.active_for_source(uid("src")) is not None


def test_decompose_unknown_parent_errors(session: CliSession) -> None:
    _, out = _run(f"decompose {uid('ghost')} do a thing", session)
    assert "no such task" in out


def test_decompose_wrong_arity_reports_usage(session: CliSession) -> None:
    _, out = _run(f"decompose {uid('src')}", session)
    assert "usage: decompose" in out
