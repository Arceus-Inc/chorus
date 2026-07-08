"""AppendOnlyMemoryWriter — chorus owns the write mechanism, lattice the policy (spec 07 §3).

One raw episodic delta per beat, append-only: a new ``*.md`` under the agent's dir named by the
``run_id``, with provenance, never merged/compressed/forgotten. The decisive contract test writes a
record with *chorus* and reads it back with *dream's own scanner* — the two halves of the
``MemoryWriter`` / ``MemoryStore`` split must agree on the file format.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from dream.contracts import MemoryScope
from dream.memory._scan import scan_memory_dir

from chorus.memory import AppendOnlyMemoryWriter, SprintDelta

pytestmark = pytest.mark.integration  # touches the filesystem


def _sprint(**over: object) -> SprintDelta:
    base: dict[str, object] = dict(
        run_id="r_1",
        task_id="t_1",
        employee_id="ada",
        scope="project",
        intent="add retry to the upload client",
        outcome="done",
        score=0.83,
        created_at=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
        artifacts=("pr:org/repo#214",),
        files_touched=("src/upload/client.py",),
        body="What happened: added a retry; the flaky network fought back.",
    )
    base.update(over)
    return SprintDelta(**base)  # type: ignore[arg-type]


async def test_apply_writes_a_per_agent_record_named_by_run_id(tmp_path) -> None:
    writer = AppendOnlyMemoryWriter(str(tmp_path))
    record = await writer.apply(_sprint().to_memory_delta())
    assert (tmp_path / "ada" / "r_1.md").is_file()  # {employee_id}/{run_id}.md
    assert record.id == "r_1"
    assert record.scope is MemoryScope.PROJECT
    assert "added a retry" in record.content


async def test_record_carries_role_and_recorded_at(tmp_path) -> None:
    writer = AppendOnlyMemoryWriter(str(tmp_path))
    now = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)
    await writer.apply(_sprint(role="engineer", recorded_at=now).to_memory_delta())

    fm = scan_memory_dir(tmp_path / "ada")[0].frontmatter
    assert fm.get("role") == "engineer"
    assert fm.get("recorded_at") == now.isoformat()


async def test_recorded_at_defaults_to_created_at(tmp_path) -> None:
    writer = AppendOnlyMemoryWriter(str(tmp_path))
    await writer.apply(_sprint().to_memory_delta())  # recorded_at left unset
    fm = scan_memory_dir(tmp_path / "ada")[0].frontmatter
    assert fm.get("recorded_at") == fm.get("created_at")


async def test_record_is_dream_readable_with_provenance(tmp_path) -> None:
    # the decisive contract: chorus writes, dream's own scanner reads it back.
    writer = AppendOnlyMemoryWriter(str(tmp_path))
    await writer.apply(_sprint().to_memory_delta())

    records = scan_memory_dir(tmp_path / "ada")
    assert len(records) == 1
    fm = records[0].frontmatter
    assert fm.get("run_id") == "r_1"  # provenance survives the round-trip
    assert fm.get("task_id") == "t_1"
    assert fm.get("employee_id") == "ada"
    assert fm.get("outcome") == "done"
    assert fm.get("score") == 0.83
    assert fm.get("kind") == "sprint_delta"


async def test_apply_is_append_only_idempotent_on_the_same_run(tmp_path) -> None:
    writer = AppendOnlyMemoryWriter(str(tmp_path))
    delta = _sprint().to_memory_delta()
    await writer.apply(delta)
    await writer.apply(delta)  # a crash-retry re-applies the same run's delta
    assert len(list((tmp_path / "ada").glob("*.md"))) == 1  # one file per run_id, never duplicated


async def test_never_overwrites_an_existing_record(tmp_path) -> None:
    # append-only: the file for a run id is written once; it is never merged or rewritten.
    writer = AppendOnlyMemoryWriter(str(tmp_path))
    await writer.apply(_sprint(body="first").to_memory_delta())
    await writer.apply(_sprint(body="second").to_memory_delta())  # same run_id, different body
    content = scan_memory_dir(tmp_path / "ada")[0].content
    assert "first" in content and "second" not in content


async def test_disjoint_run_ids_for_an_agent_never_collide(tmp_path) -> None:
    writer = AppendOnlyMemoryWriter(str(tmp_path))
    await writer.apply(_sprint(run_id="r_a").to_memory_delta())
    await writer.apply(_sprint(run_id="r_b").to_memory_delta())
    assert {p.stem for p in (tmp_path / "ada").glob("*.md")} == {"r_a", "r_b"}


async def test_employee_id_partitions_the_record(tmp_path) -> None:
    # Episodic memory is per-agent: two employees' records live in separate subtrees; scope
    # (project/team/…) is retained as a frontmatter tag, not a directory.
    writer = AppendOnlyMemoryWriter(str(tmp_path))
    await writer.apply(_sprint(employee_id="ada", scope="team").to_memory_delta())
    await writer.apply(_sprint(employee_id="bo", run_id="r_2").to_memory_delta())
    assert (tmp_path / "ada" / "r_1.md").is_file()
    assert (tmp_path / "bo" / "r_2.md").is_file()
    assert scan_memory_dir(tmp_path / "ada")[0].frontmatter.get("scope") == "team"


async def test_rollback_removes_the_appended_record(tmp_path) -> None:
    writer = AppendOnlyMemoryWriter(str(tmp_path))
    await writer.apply(_sprint().to_memory_delta())
    await writer.rollback("r_1", to_version="0")
    assert not (tmp_path / "ada" / "r_1.md").exists()
