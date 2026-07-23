"""T3 live-run contracts: coarse parallel delegation and verified integration."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "t3_delegation_live.py"


def _load_module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("t3_delegation_live", _EXAMPLE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _passing_snapshot(module):  # type: ignore[no-untyped-def]
    return module.T3Snapshot(
        root_status="done",
        child_ids=("links-child", "analytics-child"),
        child_statuses=("done", "done"),
        child_assignees=("links-ic", "analytics-ic"),
        child_scopes=("links", "analytics"),
        employee_run_windows=(
            module.RunWindow("links-child", "links-ic", 10.0, 30.0),
            module.RunWindow("analytics-child", "analytics-ic", 12.0, 28.0),
        ),
        contract_status_history=("delegated", "integrating", "verifying", "done"),
        parent_verifier_principals=("system-verifier",),
        parent_verifier_statuses=("succeeded",),
        parent_verdict_passed=True,
        child_prs_merged=(True, True),
        company_branch="main",
        gate_exit_code=0,
        shipped_paths=(
            "analytics.py",
            "gate_check.py",
            "links.py",
            "tests/test_analytics.py",
            "tests/test_links.py",
        ),
        child_tdd_valid=(True, True),
        child_review_valid=(True, True),
        evaluator_retrieval_complete=True,
        task_count=3,
        tool_use_count=10,
        tool_result_count=10,
        all_tool_results_lossless=True,
        event_count=100,
        trace_count=6,
        secret_redaction_safe=True,
    )


def _check(module, snapshot, name: str):  # type: ignore[no-untyped-def]
    return next(check for check in module.evaluate_invariants(snapshot) if check.name == name)


def test_t3_invariants_accept_two_parallel_verified_chunks() -> None:
    module = _load_module()
    snapshot = _passing_snapshot(module)

    assert all(check.passed for check in module.evaluate_invariants(snapshot))


def test_t3_invariants_reject_oversplit_decomposition() -> None:
    module = _load_module()
    passing = _passing_snapshot(module)
    oversplit = module.T3Snapshot(
        **{
            **passing.__dict__,
            "child_ids": (*passing.child_ids, "helper-child"),
            "child_statuses": (*passing.child_statuses, "done"),
            "child_assignees": (*passing.child_assignees, "links-ic"),
            "child_scopes": (*passing.child_scopes, "helper"),
            "task_count": 4,
        }
    )

    assert not _check(module, oversplit, "exactly two coarse children").passed


def test_t3_invariants_reject_serial_child_execution() -> None:
    module = _load_module()
    passing = _passing_snapshot(module)
    serial = module.T3Snapshot(
        **{
            **passing.__dict__,
            "employee_run_windows": (
                module.RunWindow("links-child", "links-ic", 10.0, 20.0),
                module.RunWindow("analytics-child", "analytics-ic", 20.0, 30.0),
            ),
        }
    )

    assert not _check(module, serial, "parallel child beats").passed


def test_t3_invariants_reject_missing_integrating_phase() -> None:
    module = _load_module()
    passing = _passing_snapshot(module)
    skipped = module.T3Snapshot(
        **{
            **passing.__dict__,
            "contract_status_history": ("delegated", "verifying", "done"),
        }
    )

    assert not _check(module, skipped, "delegation phase transitions").passed


def test_t3_invariants_reject_non_system_parent_verifier() -> None:
    module = _load_module()
    passing = _passing_snapshot(module)
    self_reviewed = module.T3Snapshot(
        **{**passing.__dict__, "parent_verifier_principals": ("lead",)}
    )

    assert not _check(module, self_reviewed, "independent subtree verification").passed


def test_t3_invariants_reject_missing_landed_module() -> None:
    module = _load_module()
    passing = _passing_snapshot(module)
    missing = module.T3Snapshot(
        **{
            **passing.__dict__,
            "shipped_paths": tuple(
                path for path in passing.shipped_paths if path != "analytics.py"
            ),
        }
    )

    assert not _check(module, missing, "both modules landed").passed


def test_t3_invariants_reject_missing_child_quality_provenance() -> None:
    module = _load_module()
    passing = _passing_snapshot(module)
    unproven = module.T3Snapshot(**{**passing.__dict__, "child_tdd_valid": (True, False)})

    assert not _check(module, unproven, "per-child quality provenance").passed


def test_t3_test_author_audit_rejects_unproven_test_plan(tmp_path: Path) -> None:
    module = _load_module()
    (tmp_path / "test_plan.json").write_text(
        json.dumps(
            {
                "authored": True,
                "files": ["tests/test_links.py"],
                "covers": ["create and resolve"],
                "red_evidence": "red-confirmed",
                "evidence": "python -m pytest -q",
            }
        )
    )

    valid, detail = module._audit_test_author([], tmp_path)

    assert valid is False
    assert "provenance" in detail
