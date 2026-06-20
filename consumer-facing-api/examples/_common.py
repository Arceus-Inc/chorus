"""Shared plumbing for the consumer-facing examples — so each script stays about *one* concept.

Two kinds of example:

* **offline** (governance, budgets, trust, routines, dod, inspect) only touch the kernel's data
  surfaces — no model, no keys. They build an org with :func:`offline_org`.
* **live** (hire → submit → run, and the team goal) dispatch real beats through ``chorus_harness``
  against an OpenAI-compatible endpoint. They build with :func:`live_org` and need three env vars:

      export AZURE_OPENAI_API_KEY=...
      export AZURE_OPENAI_BASE_URL=...
      export AZURE_OPENAI_DEPLOYMENT=...      # the model / deployment name

  Point ``CHORUS_ENV_FILE`` at a ``KEY=VALUE`` file (e.g. the repo ``.env``) to load them from disk.

Everything throwaway lives under ``/tmp`` so the examples never touch your real repos.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from chorus import Caps, Chorus, default_roles
from chorus.ledger import SqliteLedger
from chorus.roles import RoleRegistry

_REQUIRED = ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_BASE_URL", "AZURE_OPENAI_DEPLOYMENT")


# -- credentials --------------------------------------------------------------------------------


def _load_env_file() -> None:
    """Best-effort: fold ``CHORUS_ENV_FILE`` (default ``./.env``) into the environment."""
    path = Path(os.environ.get("CHORUS_ENV_FILE", ".env"))
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def have_creds() -> bool:
    """True when the three Azure/OpenAI env vars are present — so live examples can skip cleanly."""
    _load_env_file()
    return all(os.environ.get(name) for name in _REQUIRED)


def creds() -> dict[str, str]:
    """The model credentials, or a clean exit pointing at QUICKSTART when they're missing."""
    _load_env_file()
    missing = [name for name in _REQUIRED if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"missing env: {', '.join(missing)} — see consumer-facing-api/QUICKSTART.md")
    return {
        "api_key": os.environ["AZURE_OPENAI_API_KEY"],
        "base_url": os.environ["AZURE_OPENAI_BASE_URL"],
        "deployment": os.environ["AZURE_OPENAI_DEPLOYMENT"],
    }


# -- workspaces ---------------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def seed_repo(path: Path, files: dict[str, str] | None = None) -> Path:
    """A throwaway git repo employees branch their worktrees from (seeded with ``files``)."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "trunk")
    for name, body in (files or {"README.md": "# company\n"}).items():
        (path / name).write_text(body, encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "-c", "user.name=seed", "-c", "user.email=seed@x", "commit", "-m", "init")
    return path


def git_log(repo: Path, n: int = 5) -> str:
    """The repo's recent commits (one line each) — what landed on company main."""
    return subprocess.run(
        ["git", "-C", str(repo), "log", "--oneline", f"-{n}"],
        check=False, capture_output=True, text=True,
    ).stdout.rstrip()


# -- orgs ---------------------------------------------------------------------------------------


@dataclass
class Org:
    """An example's company: the facade plus the throwaway paths backing it."""

    chorus: Chorus
    base: Path
    company_main: Path  # where landed work shows up (only meaningful for live orgs)
    factory: object | None = None
    ledger: SqliteLedger | None = None


def offline_org(prefix: str = "chorus-cf-") -> Org:
    """An org with **no** model wired — for the data-surface concepts (governance/budgets/trust/…).

    Beats are never dispatched, so no creds are needed; every group verb and the read model work
    against the in-memory ledger directly.
    """
    base = Path(tempfile.mkdtemp(prefix=prefix))
    chorus = Chorus.build(
        db_path=str(base / "company.db"),
        org_repo=str(base / "org"),
        memory_repo=str(base / "memory"),
        dream=None,
    )
    return Org(chorus=chorus, base=base, company_main=base / "work")


def live_org(prefix: str = "chorus-cf-", *, seed_files: dict[str, str] | None = None) -> Org:
    """A fully-wired org that runs real beats: one shared ledger, the harness factory, landing.

    The factory owns dream + creds + per-employee worktrees; ``Chorus.build`` plugs in its two seams
    (``beat_runner_for`` = how a beat runs, ``landers`` = how its work lands) over the *same* ledger.
    """
    # Imported lazily so the offline examples never import dream / the harness layer.
    import dream

    from chorus_cli._beats import default_pricing_from_env
    from chorus_harness import EmployeeHarnessFactory

    c = creds()
    base = Path(tempfile.mkdtemp(prefix=prefix))
    seed = seed_repo(base / "source", seed_files)
    ledger = SqliteLedger.open(str(base / "company.db"))
    factory = EmployeeHarnessFactory(
        api_key=c["api_key"], base_url=c["base_url"], deployment=c["deployment"],
        company_id="acme", roles=RoleRegistry.from_plugins(default_roles()),
        pricing=default_pricing_from_env(), seed=seed, work_root=base / "work", ledger=ledger,
    )
    chorus = Chorus.build(
        ledger=ledger,
        org_repo=str(base / "org"),
        memory_repo=str(base / "memory"),
        dream=dream,
        beat_runner_for=factory,      # how a beat runs (+ the reviewer reads the author's worktree)
        landers=factory.landers,      # how the deliverable lands
        caps=Caps(tick_interval_s=0.5),
        company_id="acme",
    )
    return Org(chorus=chorus, base=base, company_main=factory.company_root / "repo",
               factory=factory, ledger=ledger)
