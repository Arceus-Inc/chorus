"""The episodic capture path — the honest per-agent record a beat leaves behind (spec 07 §3).

Unit-covers the two pure pieces the scheduler wires: ``_sprint_delta`` (fills role, recorded_at, and
the raw-record body) and ``_baseline_sha`` (the fingerprint baseline, best-effort). The end-to-end
write is exercised by the scheduler's own dispatch tests.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from chorus.heartbeat._beat import BeatDisposition, BeatOutcome
from chorus.heartbeat._scheduler import _artifact_ref, _baseline_sha, _sprint_delta
from chorus.ledger import Artifact, ArtifactType, Task
from chorus.workforce._models import Employee

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)


def _employee() -> Employee:
    return Employee(id="ada", name="Ada", role="engineer")


def _task() -> Task:
    return Task(id="t_1", intent="add retry to the upload client")


def _outcome() -> BeatOutcome:
    return BeatOutcome(
        passed=True,
        raw_record='{"kind": "assistant", "text": "bumped the pool size"}',
        disposition=BeatDisposition.PASSED,
    )


def test_sprint_delta_sets_role_recorded_at_and_raw_body() -> None:
    delta = _sprint_delta(
        run_id="r_1",
        employee=_employee(),
        task=_task(),
        result=_outcome(),
        scope="project",
        now=_NOW,
        files_touched=("src/upload/client.py",),
        artifacts=("pr#1",),
    )
    assert delta.role == "engineer"
    assert delta.recorded_at == _NOW
    assert delta.body == _outcome().raw_record  # the entire raw agent record, not a step counter
    assert delta.files_touched == ("src/upload/client.py",)
    assert delta.artifacts == ("pr#1",)
    assert delta.outcome == "done"


def test_sprint_delta_falls_back_to_summary_without_raw_record() -> None:
    result = BeatOutcome(passed=True, summary="plan complete", disposition=BeatDisposition.PASSED)
    delta = _sprint_delta(
        run_id="r_1", employee=_employee(), task=_task(), result=result, scope="project", now=_NOW
    )
    assert delta.body == "plan complete"


def test_artifact_ref_prefers_string_ids_then_json_dumps_resource_ref() -> None:
    assert _artifact_ref(_artifact(external_id="pr:org/repo#7")) == "pr:org/repo#7"
    assert _artifact_ref(_artifact(url="https://x/y")) == "https://x/y"
    ref = _artifact_ref(_artifact(resource_ref={"commit": "abc", "branch": "chorus/ada"}))
    assert ref == '{"branch": "chorus/ada", "commit": "abc"}'  # canonical, str-typed
    assert _artifact_ref(_artifact()) == ""


def _artifact(**over: object) -> Artifact:
    base: dict[str, object] = dict(id="art_1", task_id="t_1", type=ArtifactType.PR)
    base.update(over)
    return Artifact(**base)  # type: ignore[arg-type]


def _git(worktree: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(worktree), *args], capture_output=True, text=True, check=True)


def test_baseline_sha_reads_head_and_is_best_effort(tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    _git(worktree, "init", "-q")
    _git(worktree, "config", "user.email", "t@t")
    _git(worktree, "config", "user.name", "t")
    (worktree / "f").write_text("x", encoding="utf-8")
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "-qm", "s")

    assert _baseline_sha(worktree) is not None
    assert _baseline_sha(None) is None
    assert _baseline_sha(tmp_path / "nope") is None


@pytest.mark.integration
async def test_capture_memory_writes_keyed_per_agent_record(tmp_path, ledger) -> None:
    from chorus.heartbeat import Scheduler
    from chorus.memory import EpisodicStore

    worktree = tmp_path / "wt"
    worktree.mkdir()
    _git(worktree, "init", "-q")
    _git(worktree, "config", "user.email", "t@t")
    _git(worktree, "config", "user.name", "t")
    (worktree / "seed.py").write_text("x = 1\n", encoding="utf-8")
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "-qm", "seed")
    base_sha = _baseline_sha(worktree)
    (worktree / "feature.py").write_text("y = 2\n", encoding="utf-8")  # this beat's work

    ledger.tasks.submit(_task())
    ledger.artifacts.create(_artifact(task_id="t_1", external_id="pr:org/repo#7", is_primary=True))

    store = EpisodicStore(tmp_path / "memory")
    scheduler = Scheduler(ledger=ledger, memory_writer=store)
    await scheduler._capture_memory(
        ledger,
        run_id="r_1",
        employee=_employee(),
        task=_task(),
        result=_outcome(),
        now=_NOW,
        working_dir=worktree,
        base_sha=base_sha,
    )

    record = store.get("r_1")
    assert record is not None
    assert record.employee_id == "ada"  # per-agent attribution
    assert "feature.py" in record.files_touched  # the fingerprint of this beat
    assert record.role == "engineer"
    assert record.recorded_at is not None
    assert record.artifacts == ("pr:org/repo#7",)
    assert "bumped the pool size" in record.body  # body = the raw agent record
