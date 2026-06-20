"""The per-employee beat-runner seam (spec 03 §3, spec 06 §2).

The converged kernel runs every beat *as its employee*: the scheduler dispatches one beat per
employee, and resolves the :class:`~chorus.heartbeat.BeatRunner` whose dream harness is materialized
for *that* employee's role (its tools, brief, permission posture, worktree). :class:`BeatRunnerFor` is
that resolution seam; the concrete factory lives at the composition root (it owns the dream import).
:func:`single` is the degenerate one-runner case — a fixed runner for every employee, for tests and
the facade's single-harness injection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from chorus.heartbeat._beat import BeatRunner
    from chorus.workforce import Employee


@runtime_checkable
class BeatRunnerFor(Protocol):
    """Resolve the :class:`BeatRunner` for a dispatched employee (the role-faithful execution seam).

    ``task_id`` is the task this beat will run, so a resolver can shape the harness to the beat's
    *phase* — e.g. a manager's integrate beat (its task already has children) is materialized without
    the ``decompose`` tool, so the model cannot re-decompose a delegated subtree (M3 §5).
    """

    def runner_for(self, employee: Employee, *, task_id: str | None = None) -> BeatRunner: ...


class BeatRunnerForFn(Protocol):
    """The callable form of the seam — ``factory.runner_for`` (a bound method) or any function.

    Lets the composition root accept the resolver *function* directly, so the §0 front door reads
    ``Chorus.build(..., beat_runner_for=factory.runner_for)`` instead of passing the whole factory.
    """

    def __call__(self, employee: Employee, *, task_id: str | None = None) -> BeatRunner: ...


@dataclass(frozen=True)
class _Single:
    """A :class:`BeatRunnerFor` that returns one fixed runner regardless of the employee."""

    runner: BeatRunner

    def runner_for(self, employee: Employee, *, task_id: str | None = None) -> BeatRunner:
        return self.runner


@dataclass(frozen=True)
class _FromCallable:
    """A :class:`BeatRunnerFor` backed by a resolver callable (e.g. a bound ``factory.runner_for``)."""

    fn: BeatRunnerForFn

    def runner_for(self, employee: Employee, *, task_id: str | None = None) -> BeatRunner:
        return self.fn(employee, task_id=task_id)


def single(runner: BeatRunner) -> BeatRunnerFor:
    """Wrap one :class:`BeatRunner` as a :class:`BeatRunnerFor` (one harness for every employee)."""
    return _Single(runner)


def runner_from(fn: BeatRunnerForFn) -> BeatRunnerFor:
    """Adapt a resolver callable into a :class:`BeatRunnerFor` (the callable-seam form, §0)."""
    return _FromCallable(fn)


__all__ = ["BeatRunnerFor", "BeatRunnerForFn", "runner_from", "single"]
