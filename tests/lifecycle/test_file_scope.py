"""Pure validator tests for delegated file scopes."""

from __future__ import annotations

import pytest

from chorus.lifecycle._file_scope import (
    BlockerScope,
    FileScopeViolationCode,
    ProposedBlockerScope,
    validate_file_scope,
)


@pytest.mark.parametrize(
    ("paths", "code"),
    [
        (("/tmp/app.py",), FileScopeViolationCode.ABSOLUTE_PATH),
        (("../app.py",), FileScopeViolationCode.TRAVERSAL_PATH),
        (("src/app.py", "src/app.py"), FileScopeViolationCode.DUPLICATE_PATH),
        (("src", "src/app.py"), FileScopeViolationCode.NESTED_PATH),
        (("src\\app.py",), FileScopeViolationCode.NON_POSIX_PATH),
        (("C:/app.py",), FileScopeViolationCode.DRIVE_QUALIFIED_PATH),
        (("C:\\app.py",), FileScopeViolationCode.DRIVE_QUALIFIED_PATH),
        (("src/\x00app.py",), FileScopeViolationCode.CONTROL_CHARACTER_PATH),
        (("src/\x1fapp.py",), FileScopeViolationCode.CONTROL_CHARACTER_PATH),
    ],
)
def test_invalid_paths_are_rejected_with_precise_codes(
    paths: tuple[str, ...], code: FileScopeViolationCode
) -> None:
    result = validate_file_scope(
        parent_files_to_touch=(),
        current_blockers=(),
        proposed_blockers=(ProposedBlockerScope(task_id="child", files_to_touch=paths),),
        require_current_scope=False,
        require_proposed_scope=False,
    )

    assert code in {violation.code for violation in result.violations}


def test_parent_coverage_reports_extra_and_missing_paths() -> None:
    result = validate_file_scope(
        parent_files_to_touch=("src/api.py", "src/ui.py"),
        current_blockers=(),
        proposed_blockers=(
            ProposedBlockerScope(task_id="api", files_to_touch=("src/api.py",)),
            ProposedBlockerScope(task_id="other", files_to_touch=("src/other.py",)),
        ),
        require_current_scope=False,
        require_proposed_scope=False,
    )

    assert {violation.code for violation in result.violations} >= {
        FileScopeViolationCode.EXTRA_PATH,
        FileScopeViolationCode.MISSING_PATH,
    }


def test_mixed_proposed_wave_requires_all_scopes_once_any_scope_exists() -> None:
    result = validate_file_scope(
        parent_files_to_touch=(),
        current_blockers=(),
        proposed_blockers=(
            ProposedBlockerScope(task_id="api", files_to_touch=("src/api.py",)),
            ProposedBlockerScope(task_id="ui", files_to_touch=()),
        ),
        require_current_scope=False,
        require_proposed_scope=False,
    )

    assert {(violation.code, violation.task_id) for violation in result.violations} == {
        (FileScopeViolationCode.EMPTY_SCOPE, "ui")
    }


def test_existing_mixed_current_wave_requires_all_current_scopes_once_any_scope_exists() -> None:
    result = validate_file_scope(
        parent_files_to_touch=(),
        current_blockers=(
            BlockerScope(task_id="api", files_to_touch=("src/api.py",)),
            BlockerScope(task_id="ui", files_to_touch=()),
        ),
        proposed_blockers=(),
        require_current_scope=False,
        require_proposed_scope=False,
    )

    assert {(violation.code, violation.task_id) for violation in result.violations} == {
        (FileScopeViolationCode.EMPTY_SCOPE, "ui")
    }


def test_replacement_excludes_old_blocker_from_overlap_and_coverage() -> None:
    result = validate_file_scope(
        parent_files_to_touch=("src/api.py", "src/ui.py"),
        current_blockers=(
            BlockerScope(task_id="old-api", files_to_touch=("src/api.py",)),
            BlockerScope(task_id="ui", files_to_touch=("src/ui.py",)),
        ),
        proposed_blockers=(
            ProposedBlockerScope(
                task_id="new-api",
                files_to_touch=("src/api.py",),
                replaces_task_id="old-api",
            ),
        ),
        require_current_scope=False,
        require_proposed_scope=False,
    )

    assert result.valid
