"""swe_eval — a SWE-bench-style evaluation harness for Chorus code-writing employees.

The loop, per benchmark case:

    clone repo @ base_commit  ->  seed the employee's worktree with that state
    ->  run_task(intent = the issue text)  ->  capture the candidate `git diff`
    ->  evaluate it against the human PR (objective test-patch oracle, else an LLM judge)
    ->  aggregate a resolved-rate report.

It reuses Chorus's native seeding (``EmployeeHarnessFactory(seed=...)`` ->
``CompanyWorkspace._seed_repo``), so the employee starts from a real codebase and its
fix is just a branch diff — exactly the SWE-bench setup, with no bespoke plumbing.

This is a *dev/eval* tool, not part of the shipped SDK, so it lives under ``examples/``.
Run it via ``examples/run_swe_eval.py`` (which puts ``examples/`` on ``sys.path`` so
``from swe_eval import ...`` resolves this package).
"""

from __future__ import annotations

from swe_eval.case import BenchCase, CandidateSolution, EvalResult

__all__ = ["BenchCase", "CandidateSolution", "EvalResult"]
