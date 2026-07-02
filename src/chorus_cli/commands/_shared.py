"""Cross-cutting console helpers shared by the command modules — formatting, arg parsing,
employee/task resolution, and the demo heartbeat worker. No verbs register here."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

from chorus.ledger import (
    SqliteLedger,
    Task,
    TaskPriority,
)
from chorus.outcomes import Verifier
from chorus.roles import RoleRegistry
from chorus.workforce import LedgerWorkforce
from chorus.workspace import default_work_root
from chorus_cli._context import BeatService, CommandContext
from chorus_cli._render import Console

_logger = logging.getLogger("chorus_cli.heartbeat")

_PREVIEW = 48  # how many chars of free text (intent/body) a table cell shows
_OPERATOR = "operator"  # the human at the console — the sender of messages it delivers
# default heartbeat cadence for the lightweight always-on demo runner
_HEARTBEAT_INTERVAL_S = 0.5
_CHECK_LEDGER_LIMIT = 12
_WRITE_FILE_RE = re.compile(r"\bwrite\b.+\bto\s+([A-Za-z0-9_.-]+\.md)\b", re.IGNORECASE)


def _roles_from_env() -> RoleRegistry:
    """Role registry used for CLI inspection, matching the beat composition root."""
    from chorus_cli._beats import default_roles_from_env

    return RoleRegistry.from_plugins(default_roles_from_env())


class _HeartbeatWorker:
    """Run ``beats.run_tick()`` on a daemon thread so the employee keeps working while the CLI waits.

    It is intentionally tiny: best-effort pulse loop with swallowed exceptions (a single failed tick
    must not kill the console), stopped by an event the ``quit`` command sets.
    """

    def __init__(
        self,
        *,
        db_path: str,
        company_id: str,
        interval_s: float = _HEARTBEAT_INTERVAL_S,
    ) -> None:
        self._db_path = db_path
        self._company_id = company_id
        self._interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="chorus-heartbeat", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        if self._db_path == ":memory:":
            return
        ledger = SqliteLedger.open(self._db_path)
        try:
            beats = self._build_thread_beat_service(ledger)
            if beats is None:
                return
            while not self._stop.is_set():
                try:
                    beats.run_tick()
                except Exception:
                    # A single failed tick must not kill the background thread (and the console), but
                    # it must not be silent either — a permanently-broken runner would otherwise spin
                    # at the cadence with zero signal. Log with the traceback and keep ticking.
                    _logger.warning("heartbeat tick failed; continuing", exc_info=True)
                self._stop.wait(self._interval_s)
        finally:
            ledger.close()

    def _build_thread_beat_service(self, ledger: SqliteLedger) -> BeatService | None:
        api_key = os.environ.get("AZURE_OPENAI_API_KEY")
        base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
        if not (api_key and base_url and deployment):
            return None
        from chorus_cli._beats import build_beat_service, default_pricing_from_env

        return build_beat_service(
            ledger,
            api_key=api_key,
            base_url=base_url,
            deployment=deployment,
            company_id=self._company_id,
            pricing=default_pricing_from_env(),
            seed=os.environ.get("CHORUS_COMPANY_SEED") or str(Path.cwd()),
        )


_HEARTBEAT_BY_LEDGER: dict[int, _HeartbeatWorker] = {}


def _ensure_heartbeat(ctx: CommandContext) -> bool:
    if ctx.session.beats is None or ctx.session.db_path is None:
        return False
    key = id(ctx.session.ledger)
    worker = _HEARTBEAT_BY_LEDGER.get(key)
    if worker is None:
        worker = _HeartbeatWorker(db_path=ctx.session.db_path, company_id=ctx.session.company_id)
        _HEARTBEAT_BY_LEDGER[key] = worker
        worker.start()
    return True


def _stop_heartbeat(ctx: CommandContext) -> None:
    worker = _HEARTBEAT_BY_LEDGER.pop(id(ctx.session.ledger), None)
    if worker is not None:
        worker.stop()


def _maybe_bootstrap_employee(ctx: CommandContext) -> None:
    """Born-on-start behavior for the minimal demo: one default employee if the org is empty."""
    if not ctx.session.minimal_mode:
        return
    ledger = ctx.session.ledger
    if ledger.employees.list():
        return
    try:
        created = LedgerWorkforce(ledger.employees).hire(name="employee", role="engineer")
    except Exception as exc:
        # The demo can continue without the seed employee, but the operator should know why the
        # org came up empty rather than have it fail silently.
        ctx.out.error(f"could not create the default employee: {type(exc).__name__}: {exc}")
        return
    company_root = default_work_root() / ctx.session.company_id
    base = company_root / "worktrees" / created.id
    ctx.out.line(f"employee born: {created.id} ({created.role}) -- base path {base}")


def _minimal_file_dod(prompt: str) -> Verifier | None:
    match = _WRITE_FILE_RE.search(prompt)
    if match is None:
        return None
    filename = match.group(1)
    command = subprocess.list2cmdline(
        [sys.executable, "-c", f"from pathlib import Path; assert Path({filename!r}).is_file()"]
    )
    return Verifier.command(command, artifact_class="file", timeout_s=30)


def _employee_base_path(company_id: str, employee_id: str) -> Path:
    return (default_work_root() / company_id) / "worktrees" / employee_id


def _resolve_employee(ledger: SqliteLedger, raw: str) -> str | None:
    """Resolve ``raw`` to an employee id.

    Accepts a direct employee id first; if absent, treats ``raw`` as a role name and resolves it
    only when exactly one employee has that role. ``None`` means no match; ``ValueError`` means an
    ambiguous role (multiple employees share it).
    """
    if ledger.employees.get(raw) is not None:
        return raw
    matches = [e.id for e in ledger.employees.list() if e.role == raw]
    if not matches:
        return None
    if len(matches) > 1:
        raise ValueError(f"{raw!r} matches multiple employees {matches}; use an employee id")
    return matches[0]


def _latest_task_for_employee(ledger: SqliteLedger, employee_id: str) -> Task | None:
    open_task = ledger.tasks.open_for_assignee(employee_id)
    if open_task is not None:
        return open_task
    candidates = [
        t for t in ledger.tasks.list_eligible(limit=200) if t.assignee_employee_id == employee_id
    ]
    if candidates:
        return candidates[-1]
    for activity in ledger.activity.recent(limit=200):
        if activity.subject_kind == "task":
            task = ledger.tasks.get(activity.subject_id)
            if task is not None and task.assignee_employee_id == employee_id:
                return task
    return None


def _fmt(value: object) -> str:
    """Render an optional field: ``-`` for ``None``, otherwise its string form."""
    return "-" if value is None else str(value)


def _preview(text: str) -> str:
    """One-line, length-capped preview of free text for a table cell."""
    flat = text.replace("\n", " ").strip()
    return flat if len(flat) <= _PREVIEW else flat[: _PREVIEW - 1] + "…"


def _parse_priority(raw: str, out: Console) -> TaskPriority | None:
    """Convert a user string to :class:`TaskPriority` at the boundary, or report and return ``None``."""
    try:
        return TaskPriority(raw)
    except ValueError:
        choices = ", ".join(level.value for level in TaskPriority)
        out.error(f"unknown priority {raw!r}; choose one of: {choices}")
        return None


def _parse_limit(raw: str, out: Console) -> int | None:
    """Parse a positive integer limit, or report and return ``None``."""
    try:
        value = int(raw)
    except ValueError:
        out.error(f"{raw!r} is not an integer")
        return None
    if value < 1:
        out.error(f"limit must be a positive integer, got {value}")
        return None
    return value


def _pop_flag(args: tuple[str, ...], name: str) -> tuple[str | None, tuple[str, ...]]:
    """Pull a ``--name`` flag out of ``args``; return ``(value | None, remaining_args)``.

    Accepts both joined (``--name=value``) and space-separated (``--name value``) forms — the two
    conventions a user reasonably types — and leaves everything else in ``rest``.
    """
    joined = f"--{name}="
    bare = f"--{name}"
    value: str | None = None
    rest: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg.startswith(joined):
            value = arg[len(joined) :]
        elif arg == bare and index + 1 < len(args):
            value = args[index + 1]
            index += 1  # consume the following value token
        else:
            rest.append(arg)
        index += 1
    return value, tuple(rest)


# -- meta -------------------------------------------------------------------------------------------
