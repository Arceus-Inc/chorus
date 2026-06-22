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

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# A local identity for the company workspace repos (which live under .chorus/, never the user's source
# repo). Commits here are operational snapshots, not authored history — keep them clearly machine-made.
_COMMIT_IDENTITY = ("-c", "user.name=chorus", "-c", "user.email=chorus@local")

# dream/chorus operational dirs the harness writes into the working dir — excluded from the branch so a
# merge carries only real deliverables (shared across all worktrees via the repo's info/exclude).
_OPERATIONAL_EXCLUDES = (
    "roles/",  # legacy role overlay location; kept excluded for old worktrees
    ".dream/",  # dream task/ledger artefacts
    ".harness/",  # dream tool-tier / policy / role-overlay files
    ".chorus/",  # any nested chorus state
    "docs/evals/",  # dream planner eval artefacts written into the working dir (not deliverable)
    "docs/exec-plans/",  # dream planner exec-plan artefacts (not deliverable)
    ".mypy_cache/",
    ".playwright-mcp/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".venv/",
    "__pycache__/",
    "memory/",  # memory store spill, if working-dir-local
    "node_modules/",
    # Compiled build output — language-agnostic, never the deliverable's source. Without these a
    # Rust crate's ``target/`` (~thousands of files) or a JS ``dist/`` lands in the "PR" (the tinyvec
    # 1241-file leak). High-confidence dirs only — never names that can hold tracked source.
    "target/",  # Rust/Cargo, Maven
    "dist/",  # Python/JS build output
    ".next/",  # Next.js build
    ".nuxt/",  # Nuxt build
    ".gradle/",  # Gradle cache
    ".tox/",  # Python tox envs
    "htmlcov/",  # coverage HTML
    ".coverage",  # coverage data file
    "*.egg-info/",  # Python packaging metadata
)
_OPERATIONAL_EXCLUDE_NAMES = {path.rstrip("/") for path in _OPERATIONAL_EXCLUDES}
_SEED_COPY_IGNORE = shutil.ignore_patterns(".git", *_OPERATIONAL_EXCLUDE_NAMES)
_HARNESS_SEED_FILES = frozenset({"mcp-allowlist.toml", "plugins-enabled.toml"})


# The default base for company workspaces under the current working directory. ``chat``, ``tick``, and
# the ``company`` console command all resolve a company to ``<cwd>/.chorus/work/{company}`` — defined
# once here so the front ends cannot drift from the harness factory.
_WORK_ROOT = Path(".chorus") / "work"


def default_work_root() -> Path:
    """``<cwd>/.chorus/work`` — the base a company workspace is rooted under (``base / company_id``)."""
    return Path.cwd() / _WORK_ROOT


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

    def __init__(self, root: Path, *, seed: str | Path | None = None) -> None:
        self._root = root
        self._repo = root / "repo"
        self._worktrees = root / "worktrees"
        # Optional source the company ``main`` is seeded from on first creation, so employees branch
        # off a real codebase instead of an empty tree: a local git repo or remote URL (cloned), or a
        # plain directory (copied + committed). Ignored once ``repo/`` exists — seeding happens once.
        self._seed = seed

    @property
    def root(self) -> Path:
        return self._root

    @property
    def repo(self) -> Path:
        return self._repo

    def ensure_repo(self) -> Path:
        """Create the company ``repo/`` (branch ``main``) if absent; return it.

        Without a seed, ``main`` is an empty root commit (the minimum that lets worktrees branch — you
        cannot add a worktree from an unborn HEAD). With a seed, ``main`` carries the seeded code. The
        operational excludes are written to the repo's shared ``info/exclude`` so every worktree
        inherits them.
        """
        if (self._repo / ".git").exists():
            return self._repo
        self._repo.parent.mkdir(parents=True, exist_ok=True)
        if self._seed is not None:
            self._seed_repo(self._seed)
        else:
            self._repo.mkdir(parents=True, exist_ok=True)
            self._run(self._repo, "init", "-b", "main")
            self._run(
                self._repo, *_COMMIT_IDENTITY, "commit", "--allow-empty", "-m", "chorus: company root"
            )
        exclude = self._repo / ".git" / "info" / "exclude"
        exclude.write_text("\n".join(_OPERATIONAL_EXCLUDES) + "\n", encoding="utf-8")
        return self._repo

    def _seed_repo(self, seed: str | Path) -> None:
        """Materialize ``repo/`` from ``seed`` — clone a git repo/URL, or copy a plain directory."""
        src = Path(seed)
        if src.exists() and (src / ".git").exists():
            self._clone(str(src))
        elif src.exists():
            self._repo.mkdir(parents=True, exist_ok=True)
            self._run(self._repo, "init", "-b", "main")
            self._copy_tree(src, self._repo)
            self._run(self._repo, "add", "-A")
            self._run(self._repo, *_COMMIT_IDENTITY, "commit", "-m", f"chorus: seed from {src.name}")
        else:  # not a local path → treat as a remote clone URL
            self._clone(str(seed))

    def _clone(self, source: str) -> None:
        """Clone ``source`` into ``repo/`` and normalize the checked-out branch to ``main``."""
        self._run(self._repo.parent, "clone", source, str(self._repo))
        if self._has_commits():
            self._run(self._repo, "branch", "-M", "main")  # worktrees branch off `main`
        else:
            self._run(self._repo, "checkout", "-b", "main")

    def _has_commits(self) -> bool:
        return (
            subprocess.run(
                ["git", "-C", str(self._repo), "rev-parse", "--verify", "--quiet", "HEAD"],
                capture_output=True,
                text=True,
            ).returncode
            == 0
        )

    @staticmethod
    def _copy_tree(src: Path, dst: Path) -> None:
        """Copy ``src``'s contents into ``dst`` (a fresh repo), skipping operational dirs."""
        for item in src.iterdir():
            if item.name == ".harness":
                CompanyWorkspace._copy_seed_harness_files(item, dst / item.name)
                continue
            if item.name == ".git" or item.name in _OPERATIONAL_EXCLUDE_NAMES:
                continue
            target = dst / item.name
            if item.is_dir():
                shutil.copytree(item, target, ignore=_SEED_COPY_IGNORE)
            else:
                shutil.copy2(item, target)

    @staticmethod
    def _copy_seed_harness_files(src: Path, dst: Path) -> None:
        """Copy only declarative Dream harness config from a seed repo."""
        if not src.is_dir():
            return
        for name in _HARNESS_SEED_FILES:
            source = src / name
            if source.is_file():
                dst.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dst / name)

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

    def sync_to_main(self, employee_id: str) -> bool:
        """Bring ``employee_id``'s worktree up to the current company ``main``; return whether it synced.

        A manager that delegated never edited code, so its worktree still sits at the ``main`` it
        branched from — blind to the children's deliverables that have since landed there. Merging
        ``main`` into the branch (a fast-forward, since a delegating manager has no own commits) makes
        the integrated subtree visible in the worktree, so the manager's integrate beat reviews the real
        merged result instead of an empty tree. A divergent branch that cannot merge cleanly is left
        untouched (the beat falls back to its stale worktree) rather than raised — sync is best-effort.
        """
        wt = self.worktree_for(employee_id)
        done = subprocess.run(
            ["git", "-C", str(wt.path), *_COMMIT_IDENTITY, "merge", "main",
             "-m", f"chorus: sync {wt.branch} to main"],
            capture_output=True,
            text=True,
        )
        if done.returncode == 0:
            return True
        if "CONFLICT" in (done.stdout + done.stderr):
            self._run(wt.path, "merge", "--abort")
        return False

    def snapshot(self, employee_id: str) -> str:
        """Commit any uncommitted work in the employee's worktree; return its branch HEAD commit sha.

        The outcome-landing primitive (spec 04 §2): an Engineer's deliverable is its branch + the
        committed work, so landing a "PR" snapshots the worktree and points the artifact at this sha.
        """
        self._snapshot(employee_id)
        return self._run(self.worktree_for(employee_id).path, "rev-parse", "HEAD")

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


__all__ = [
    "CompanyWorkspace",
    "MergeResult",
    "WorkspaceError",
    "WorktreeWorkspace",
    "default_work_root",
]
