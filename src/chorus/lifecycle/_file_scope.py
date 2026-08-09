"""Typed file-scope validation for delegated child work."""

from __future__ import annotations

import ntpath
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath


class FileScopeViolationCode(StrEnum):
    """Stable reasons a task or child scope is refused."""

    EMPTY_SCOPE = "empty_scope"
    EMPTY_PATH = "empty_path"
    ABSOLUTE_PATH = "absolute_path"
    DRIVE_QUALIFIED_PATH = "drive_qualified_path"
    TRAVERSAL_PATH = "traversal_path"
    NON_POSIX_PATH = "non_posix_path"
    CONTROL_CHARACTER_PATH = "control_character_path"
    DUPLICATE_PATH = "duplicate_path"
    NESTED_PATH = "nested_path"
    EXTRA_PATH = "extra_path"
    MISSING_PATH = "missing_path"


@dataclass(frozen=True)
class BlockerScope:
    """One existing blocker child's file scope."""

    task_id: str
    files_to_touch: tuple[str, ...]


@dataclass(frozen=True)
class ProposedBlockerScope:
    """One new blocker child's file scope, optionally replacing an older blocker."""

    task_id: str
    files_to_touch: tuple[str, ...]
    replaces_task_id: str | None = None


@dataclass(frozen=True)
class FileScopeViolation:
    """One typed refusal emitted by the pure validator."""

    code: FileScopeViolationCode
    task_id: str | None = None
    path: str | None = None
    other_task_id: str | None = None
    other_path: str | None = None


@dataclass(frozen=True)
class FileScopeValidation:
    """Normalized scopes plus any violations found."""

    parent_files_to_touch: tuple[str, ...]
    current_blockers: tuple[BlockerScope, ...]
    proposed_blockers: tuple[ProposedBlockerScope, ...]
    violations: tuple[FileScopeViolation, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.violations


def validate_file_scope(
    *,
    parent_files_to_touch: tuple[str, ...],
    current_blockers: tuple[BlockerScope, ...],
    proposed_blockers: tuple[ProposedBlockerScope, ...] = (),
    require_current_scope: bool,
    require_proposed_scope: bool,
) -> FileScopeValidation:
    """Normalize and validate a parent/child blocker scope set."""

    violations: list[FileScopeViolation] = []
    scoped_plan = (
        bool(parent_files_to_touch)
        or any(blocker.files_to_touch for blocker in current_blockers)
        or any(blocker.files_to_touch for blocker in proposed_blockers)
    )
    normalized_parent, parent_violations = _normalize_scope(
        parent_files_to_touch, task_id=None, require_nonempty=False
    )
    violations.extend(parent_violations)

    normalized_current: list[BlockerScope] = []
    for blocker in current_blockers:
        files_to_touch, blocker_violations = _normalize_scope(
            blocker.files_to_touch,
            task_id=blocker.task_id,
            require_nonempty=require_current_scope or scoped_plan,
        )
        violations.extend(blocker_violations)
        normalized_current.append(BlockerScope(task_id=blocker.task_id, files_to_touch=files_to_touch))

    normalized_proposed: list[ProposedBlockerScope] = []
    for proposed in proposed_blockers:
        files_to_touch, blocker_violations = _normalize_scope(
            proposed.files_to_touch,
            task_id=proposed.task_id,
            require_nonempty=require_proposed_scope or scoped_plan,
        )
        violations.extend(blocker_violations)
        normalized_proposed.append(
            ProposedBlockerScope(
                task_id=proposed.task_id,
                files_to_touch=files_to_touch,
                replaces_task_id=proposed.replaces_task_id,
            )
        )

    replaced_ids = {child.replaces_task_id for child in normalized_proposed}
    proposed_ids = {child.task_id for child in normalized_proposed}
    active_current = {
        blocker.task_id: blocker
        for blocker in normalized_current
        if blocker.task_id not in replaced_ids and blocker.task_id not in proposed_ids
    }
    active_blockers = tuple(active_current.values()) + tuple(
        BlockerScope(task_id=blocker.task_id, files_to_touch=blocker.files_to_touch)
        for blocker in normalized_proposed
    )
    violations.extend(_cross_scope_violations(active_blockers))

    if normalized_parent:
        current_union = {
            path
            for blocker in active_blockers
            for path in blocker.files_to_touch
        }
        parent_paths = set(normalized_parent)
        for path in sorted(current_union - parent_paths):
            violations.append(FileScopeViolation(FileScopeViolationCode.EXTRA_PATH, path=path))
        for path in sorted(parent_paths - current_union):
            violations.append(FileScopeViolation(FileScopeViolationCode.MISSING_PATH, path=path))

    return FileScopeValidation(
        parent_files_to_touch=normalized_parent,
        current_blockers=tuple(normalized_current),
        proposed_blockers=tuple(normalized_proposed),
        violations=tuple(violations),
    )


def describe_file_scope_violation(violation: FileScopeViolation) -> str:
    """Human text for one violation."""

    if violation.code is FileScopeViolationCode.EMPTY_SCOPE:
        return _prefix(violation.task_id) + "files_to_touch must not be empty"
    if violation.code is FileScopeViolationCode.EMPTY_PATH:
        return _prefix(violation.task_id) + "files_to_touch contains an empty path"
    if violation.code is FileScopeViolationCode.ABSOLUTE_PATH:
        return _prefix(violation.task_id) + f"{violation.path!r} must be repo-relative"
    if violation.code is FileScopeViolationCode.DRIVE_QUALIFIED_PATH:
        return _prefix(violation.task_id) + f"{violation.path!r} must not include a Windows drive"
    if violation.code is FileScopeViolationCode.TRAVERSAL_PATH:
        return _prefix(violation.task_id) + f"{violation.path!r} must not traverse upward"
    if violation.code is FileScopeViolationCode.NON_POSIX_PATH:
        return _prefix(violation.task_id) + f"{violation.path!r} must use POSIX separators"
    if violation.code is FileScopeViolationCode.CONTROL_CHARACTER_PATH:
        return _prefix(violation.task_id) + f"{violation.path!r} contains control characters"
    if violation.code is FileScopeViolationCode.DUPLICATE_PATH:
        if violation.other_task_id is None:
            return _prefix(violation.task_id) + f"{violation.path!r} is duplicated"
        return (
            _prefix(violation.task_id)
            + f"{violation.path!r} overlaps exactly with {violation.other_task_id}"
        )
    if violation.code is FileScopeViolationCode.NESTED_PATH:
        other = violation.other_path or ""
        if violation.other_task_id is None:
            return _prefix(violation.task_id) + f"{violation.path!r} overlaps nested path {other!r}"
        return (
            _prefix(violation.task_id)
            + f"{violation.path!r} overlaps nested path {other!r} on {violation.other_task_id}"
        )
    if violation.code is FileScopeViolationCode.EXTRA_PATH:
        return f"{violation.path!r} falls outside the parent scope"
    return f"{violation.path!r} is missing from the current child union"


def _normalize_scope(
    raw_paths: tuple[str, ...], *, task_id: str | None, require_nonempty: bool
) -> tuple[tuple[str, ...], tuple[FileScopeViolation, ...]]:
    normalized: list[str] = []
    seen: set[str] = set()
    violations: list[FileScopeViolation] = []
    for raw_path in raw_paths:
        text = raw_path.strip()
        if not text:
            violations.append(FileScopeViolation(FileScopeViolationCode.EMPTY_PATH, task_id=task_id))
            continue
        if _has_control_characters(text):
            violations.append(
                FileScopeViolation(
                    FileScopeViolationCode.CONTROL_CHARACTER_PATH,
                    task_id=task_id,
                    path=text,
                )
            )
            continue
        if ntpath.splitdrive(text)[0]:
            violations.append(
                FileScopeViolation(
                    FileScopeViolationCode.DRIVE_QUALIFIED_PATH,
                    task_id=task_id,
                    path=text,
                )
            )
            continue
        if "\\" in text:
            violations.append(
                FileScopeViolation(
                    FileScopeViolationCode.NON_POSIX_PATH,
                    task_id=task_id,
                    path=text,
                )
            )
            continue
        pure = PurePosixPath(text)
        if pure.is_absolute():
            violations.append(
                FileScopeViolation(
                    FileScopeViolationCode.ABSOLUTE_PATH,
                    task_id=task_id,
                    path=text,
                )
            )
            continue
        parts: list[str] = []
        traverses = False
        for part in pure.parts:
            if part in ("", "."):
                continue
            if part == "..":
                violations.append(
                    FileScopeViolation(
                        FileScopeViolationCode.TRAVERSAL_PATH,
                        task_id=task_id,
                        path=text,
                    )
                )
                traverses = True
                break
            parts.append(part)
        if traverses:
            continue
        if not parts:
            violations.append(FileScopeViolation(FileScopeViolationCode.EMPTY_PATH, task_id=task_id))
            continue
        normalized_path = PurePosixPath(*parts).as_posix()
        if normalized_path in seen:
            violations.append(
                FileScopeViolation(
                    FileScopeViolationCode.DUPLICATE_PATH,
                    task_id=task_id,
                    path=normalized_path,
                )
            )
            continue
        seen.add(normalized_path)
        normalized.append(normalized_path)
    if require_nonempty and not normalized:
        violations.append(FileScopeViolation(FileScopeViolationCode.EMPTY_SCOPE, task_id=task_id))
    violations.extend(_internal_overlap_violations(task_id, tuple(normalized)))
    return tuple(normalized), tuple(violations)


def _internal_overlap_violations(
    task_id: str | None, files_to_touch: tuple[str, ...]
) -> tuple[FileScopeViolation, ...]:
    violations: list[FileScopeViolation] = []
    for index, left in enumerate(files_to_touch):
        for right in files_to_touch[index + 1 :]:
            if _is_ancestor(left, right) or _is_ancestor(right, left):
                violations.append(
                    FileScopeViolation(
                        FileScopeViolationCode.NESTED_PATH,
                        task_id=task_id,
                        path=left,
                        other_path=right,
                    )
                )
    return tuple(violations)


def _cross_scope_violations(blockers: tuple[BlockerScope, ...]) -> tuple[FileScopeViolation, ...]:
    violations: list[FileScopeViolation] = []
    for index, left in enumerate(blockers):
        for right in blockers[index + 1 :]:
            for left_path in left.files_to_touch:
                for right_path in right.files_to_touch:
                    if left_path == right_path:
                        violations.append(
                            FileScopeViolation(
                                FileScopeViolationCode.DUPLICATE_PATH,
                                task_id=left.task_id,
                                path=left_path,
                                other_task_id=right.task_id,
                                other_path=right_path,
                            )
                        )
                    elif _is_ancestor(left_path, right_path) or _is_ancestor(right_path, left_path):
                        violations.append(
                            FileScopeViolation(
                                FileScopeViolationCode.NESTED_PATH,
                                task_id=left.task_id,
                                path=left_path,
                                other_task_id=right.task_id,
                                other_path=right_path,
                            )
                        )
    return tuple(violations)


def _is_ancestor(left: str, right: str) -> bool:
    left_parts = PurePosixPath(left).parts
    right_parts = PurePosixPath(right).parts
    return len(left_parts) < len(right_parts) and right_parts[: len(left_parts)] == left_parts


def _has_control_characters(text: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in text)


def _prefix(task_id: str | None) -> str:
    return f"{task_id}: " if task_id is not None else ""


__all__ = [
    "BlockerScope",
    "FileScopeValidation",
    "FileScopeViolation",
    "FileScopeViolationCode",
    "ProposedBlockerScope",
    "describe_file_scope_violation",
    "validate_file_scope",
]
