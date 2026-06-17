"""CompanyWorkspace — branch-isolated git worktrees under a shared company root (spec 04 §4).

Every employee of a company writes in ``.chorus/chat/{company}/worktrees/{employee}`` — a git
worktree on its own branch ``chorus/{employee}`` cut from the company ``repo/`` (branch ``main``).
Because dream's tools are confined to the harness ``working_dir`` (the tool execution cwd; see
``dream.tools.builtin.bash``), making that ``working_dir`` the worktree is what actually isolates one
employee's edits from another's. Work merges back to ``main`` later via :meth:`CompanyWorkspace.merge`.

This is a dream-free primitive: pure ``git`` side-effects behind a small typed surface, so it is
reusable by the public API and fully testable with a real git repo in a temp dir.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

# A local identity for the company workspace repos (which live under .chorus/, never the user's source
# repo). Commits here are operational snapshots, not authored history — keep them clearly machine-made.
_COMMIT_IDENTITY = ("-c", "user.name=chorus", "-c", "user.email=chorus@local")

# dream/chorus operational dirs the harness writes into the working dir — excluded from the branch so a
# merge carries only real deliverables (shared across all worktrees via the repo's info/exclude).
_OPERATIONAL_EXCLUDES = (
    "roles/",  # the per-role overlays chorus writes
    ".dream/",  # dream task/ledger artefacts
    ".harness/",  # dream tool-tier / policy files
    ".chorus/",  # any nested chorus state
    "memory/",  # memory store spill, if working-dir-local
)


class WorkspaceError(RuntimeError):
    """A git operation in the company workspace failed (non-zero exit)."""


@dataclass(frozen=True)
class WorktreeWorkspace:
    """One employee's branch-isolated workspace: the worktree path + its branch."""

    path: Path
    branch: str


@dataclass(frozen=True)
class MergeResult:
    """The outcome of merging an employee's branch into the company ``main``."""

    branch: str
    into: str
    merged: bool
    conflicted: bool
    detail: str


class CompanyWorkspace:
    """The shared git root for one company's employees (``.chorus/chat/{company}/``).

    Owns a canonical ``repo/`` (branch ``main``) and one worktree per employee under ``worktrees/``.
    Every method is idempotent: re-ensuring the repo or re-requesting a worktree is a no-op that
    returns the existing one, so a chat session can call them on every turn without accumulating state.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._repo = root / "repo"
        self._worktrees = root / "worktrees"

    @property
    def root(self) -> Path:
        return self._root

    @property
    def repo(self) -> Path:
        return self._repo

    def ensure_repo(self) -> Path:
        """Create the company ``repo/`` (branch ``main`` + an empty root commit) if absent; return it.

        The empty root commit is what lets worktrees branch off ``main`` (you cannot add a worktree
        from an unborn HEAD). The operational excludes are written to the repo's shared
        ``info/exclude`` so every worktree inherits them.
        """
        if (self._repo / ".git").exists():
            return self._repo
        self._repo.mkdir(parents=True, exist_ok=True)
        self._run(self._repo, "init", "-b", "main")
        self._run(self._repo, *_COMMIT_IDENTITY, "commit", "--allow-empty", "-m", "chorus: company root")
        exclude = self._repo / ".git" / "info" / "exclude"
        exclude.write_text("\n".join(_OPERATIONAL_EXCLUDES) + "\n", encoding="utf-8")
        return self._repo

    def worktree_for(self, employee_id: str) -> WorktreeWorkspace:
        """Create (or reuse) ``employee_id``'s branch-isolated worktree; return its path + branch."""
        self.ensure_repo()
        branch = f"chorus/{employee_id}"
        path = self._worktrees / employee_id
        if path.exists():
            return WorktreeWorkspace(path=path, branch=branch)
        path.parent.mkdir(parents=True, exist_ok=True)
        if self._branch_exists(branch):
            self._run(self._repo, "worktree", "add", str(path), branch)
        else:
            self._run(self._repo, "worktree", "add", "-b", branch, str(path), "main")
        return WorktreeWorkspace(path=path, branch=branch)

    def merge(self, employee_id: str, *, into: str = "main", message: str | None = None) -> MergeResult:
        """Snapshot the employee's uncommitted work, then merge its branch into ``into`` (default main).

        Returns a :class:`MergeResult`; a merge conflict is reported (and aborted), never raised, so a
        caller can surface it without the workspace left mid-merge.
        """
        branch = f"chorus/{employee_id}"
        self._snapshot(employee_id)
        msg = message or f"chorus: merge {branch}"
        done = subprocess.run(
            ["git", "-C", str(self._repo), *_COMMIT_IDENTITY, "merge", "--no-ff", branch, "-m", msg],
            capture_output=True,
            text=True,
        )
        if done.returncode == 0:
            return MergeResult(branch=branch, into=into, merged=True, conflicted=False, detail=done.stdout.strip())
        conflicted = "CONFLICT" in (done.stdout + done.stderr)
        if conflicted:
            self._run(self._repo, "merge", "--abort")
        return MergeResult(
            branch=branch,
            into=into,
            merged=False,
            conflicted=conflicted,
            detail=(done.stderr or done.stdout).strip(),
        )

    def _snapshot(self, employee_id: str) -> None:
        """Commit any uncommitted (non-excluded) work in the employee's worktree, if there is any."""
        wt = self.worktree_for(employee_id).path
        self._run(wt, "add", "-A")
        staged = subprocess.run(
            ["git", "-C", str(wt), "diff", "--cached", "--quiet"], capture_output=True, text=True
        )
        if staged.returncode != 0:  # non-zero → there are staged changes to capture
            self._run(wt, *_COMMIT_IDENTITY, "commit", "-m", "chorus: snapshot work")

    def _branch_exists(self, branch: str) -> bool:
        return (
            subprocess.run(
                ["git", "-C", str(self._repo), "rev-parse", "--verify", "--quiet", branch],
                capture_output=True,
                text=True,
            ).returncode
            == 0
        )

    def _run(self, cwd: Path, *args: str) -> str:
        done = subprocess.run(
            ["git", "-C", str(cwd), *args], capture_output=True, text=True
        )
        if done.returncode != 0:
            raise WorkspaceError(f"git {' '.join(args)} failed: {(done.stderr or done.stdout).strip()}")
        return done.stdout.strip()


__all__ = ["CompanyWorkspace", "MergeResult", "WorkspaceError", "WorktreeWorkspace"]
