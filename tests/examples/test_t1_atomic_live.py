"""T1 live-run report contracts: fail-closed invariants and secret-safe rendering."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "t1_atomic_live.py"


def _load_module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("t1_atomic_live", _EXAMPLE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_t1_invariants_require_one_worker_and_system_verifier() -> None:
    module = _load_module()
    passing = module.T1Snapshot(
        task_status="done",
        worker_run_principals=("bex",),
        worker_run_statuses=("succeeded",),
        verifier_run_principals=("system-verifier",),
        verifier_run_statuses=("succeeded",),
        dod_status="passed",
        artifact_types=("pr",),
        pr_merged=True,
        pr_target="main",
        company_branch="main",
        gate_exit_code=0,
        shipped_paths=("links.py", "tests/test_links.py"),
        red_evidence_verdict="red-confirmed",
        tdd_chronology_valid=True,
        review_provenance_valid=True,
        evaluator_retrieval_complete=True,
        secret_redaction_safe=True,
        tool_use_count=8,
        tool_result_count=8,
        all_tool_results_lossless=True,
        event_count=24,
        trace_count=2,
    )

    assert all(check.passed for check in module.evaluate_invariants(passing))

    oversplit = module.T1Snapshot(
        **{
            **passing.__dict__,
            "worker_run_principals": ("bex", "bex"),
            "worker_run_statuses": ("succeeded", "succeeded"),
        }
    )
    wrong_verifier = module.T1Snapshot(
        **{
            **passing.__dict__,
            "verifier_run_principals": ("bex",),
        }
    )
    runtime_state_landed = module.T1Snapshot(
        **{
            **passing.__dict__,
            "shipped_paths": (
                "links.py",
                "tests/test_links.py",
                "links.sqlite3",
            ),
        }
    )
    invalid_red = module.T1Snapshot(
        **{
            **passing.__dict__,
            "red_evidence_verdict": "invalid",
        }
    )
    replaced_review = module.T1Snapshot(**{**passing.__dict__, "review_provenance_valid": False})
    unread_evaluator_output = module.T1Snapshot(
        **{**passing.__dict__, "evaluator_retrieval_complete": False}
    )
    unmerged_pr = module.T1Snapshot(**{**passing.__dict__, "pr_merged": False})

    assert not next(
        check for check in module.evaluate_invariants(oversplit) if check.name == "one build beat"
    ).passed
    assert not next(
        check
        for check in module.evaluate_invariants(replaced_review)
        if check.name == "independent review provenance"
    ).passed
    assert not next(
        check
        for check in module.evaluate_invariants(unmerged_pr)
        if check.name == "PR artifact landed"
    ).passed
    assert not next(
        check
        for check in module.evaluate_invariants(unread_evaluator_output)
        if check.name == "evaluator evidence retrieval"
    ).passed
    assert not next(
        check
        for check in module.evaluate_invariants(wrong_verifier)
        if check.name == "independent system verification"
    ).passed
    assert not next(
        check
        for check in module.evaluate_invariants(runtime_state_landed)
        if check.name == "artifact hygiene"
    ).passed
    assert not next(
        check
        for check in module.evaluate_invariants(invalid_red)
        if check.name == "strict TDD chronology"
    ).passed


def test_tdd_audit_requires_behavior_specific_red_before_production_write(
    tmp_path: Path,
) -> None:
    module = _load_module()
    red = tmp_path / "red.json"
    red.write_text(
        json.dumps(
            {
                "verdict": "red-confirmed",
                "returncode": 1,
                "expected_failure_matched": True,
                "command_unavailable": False,
                "production_paths": [],
                "invalid_test_paths": [],
                "missing_tests": [],
            }
        )
    )
    now = datetime(2026, 7, 15, tzinfo=UTC)
    events = [
        module.Event(
            kind=module.EventKind.RUN_TOOL_RESULT,
            at=now,
            task_id="t1-links",
            payload={"tool": "test_red", "is_error": False, "content": "red-confirmed"},
        ),
        module.Event(
            kind=module.EventKind.RUN_TOOL_USE,
            at=now,
            task_id="t1-links",
            payload={
                "tool": "write_file",
                "role": "generator",
                "input": {"path": "links.py", "content": "production"},
            },
        ),
    ]

    valid, _ = module._audit_tdd(events, red)
    assert valid is True

    payload = json.loads(red.read_text())
    payload["expected_failure_matched"] = False
    red.write_text(json.dumps(payload))
    invalid, detail = module._audit_tdd(events, red)
    assert invalid is False
    assert "expected failure" in detail


def test_evaluator_offload_audit_requires_later_retrieval() -> None:
    module = _load_module()
    now = datetime(2026, 7, 15, tzinfo=UTC)
    pointer = "Full output saved to: eval-output.txt\nRetrieve it with read_offloaded."
    result = module.Event(
        kind=module.EventKind.RUN_TOOL_RESULT,
        at=now,
        task_id="t1-links",
        payload={"tool": "read_file", "role": "evaluator", "content": pointer},
    )
    retrieval = module.Event(
        kind=module.EventKind.RUN_TOOL_USE,
        at=now,
        task_id="t1-links",
        payload={
            "tool": "read_offloaded",
            "role": "evaluator",
            "input": {"path": "eval-output.txt"},
        },
    )

    missing, _ = module._audit_evaluator_retrieval([result])
    complete, _ = module._audit_evaluator_retrieval([result, retrieval])

    assert missing is False
    assert complete is True


def test_redact_text_removes_nonempty_secret_values() -> None:
    module = _load_module()
    secret = "super-secret-provider-key"

    rendered = module.redact_text(
        f'{{"authorization": "Bearer {secret}", "safe": "kept"}}',
        ("", secret),
    )

    assert secret not in rendered
    assert "[REDACTED]" in rendered
    assert '"safe": "kept"' in rendered
