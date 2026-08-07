"""The conversational ``chat`` sub-loop — talk to an employee, watch the beat reply.

Where the rest of the console is verb-driven (``hire``, ``submit``, ``assign``), ``chat`` is a
*conversational* front door to a single employee, modelled on dream's ``repl chat``. Each line you
type is recorded as a :class:`~chorus.ledger.Message`, auto-promoted into a task so a beat can run,
and dispatched through one scheduler ``tick`` — the real path, so budget / pause / invokability gates
all apply. The employee's work streams back live (the :class:`ChatRenderBus` renders the beat's
``run.*`` event stream), and a verdict footer closes the turn.

Continuity is the ledger ``agent_session`` transcript (conversation + tool-call SoT), plus the
employee's episodic memory / stable worktree. The CLI display list is not authoritative — ``/transcript``
reads from the ledger. This module holds no dream import — it drives a wired :class:`Scheduler`
through the small :class:`ChatBeatService` bridge, and is fully testable with a fake beat runner.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import TextIO

from chorus.events import Event, EventKind
from chorus.heartbeat import Scheduler, TickReport, Wake, WakeReason
from chorus.ids import mint_id
from chorus.ledger import (
    ConversationRole,
    Ledger,
    Message,
    MessageKind,
    Task,
    append_user_turn,
    load_transcript,
)
from chorus.lifecycle import assign_task
from chorus.observability import EventBus
from chorus.roles import RoleBeatConfig
from chorus.workspace import CompanyWorkspace
from chorus_cli._render import Console

_OPERATOR = "operator"  # the human at the console — the sender of the lines it records

# ANSI dim, for the tool/status action lines (mirrors Console's private palette).
_RESET = "\x1b[0m"
_DIM = "\x1b[2m"


class ChatRenderBus(EventBus):
    """Render a beat's structured event stream as a chat reply (an :class:`EventBus` the scheduler
    emits onto).

    The :class:`Scheduler` only ever calls :meth:`emit`; this subclass overrides it to *render* each
    ``run.*`` event to a text stream instead of fanning out + logging (``subscribe`` / ``replay`` stay
    the inherited spec-08 stubs — nothing here fakes that work). ``run.text`` deltas stream as the
    employee's prose; tool use / result and lifecycle markers print as dim one-liners. The bus tracks
    whether prose is mid-line so a structured line never lands in the middle of a streamed sentence.
    """

    def __init__(self, out: TextIO, *, colour: bool = False) -> None:
        super().__init__(log_path=None)
        self._out = out
        self._colour = colour
        self._mid_line = False  # True while streamed prose has been written without a trailing \n

    def reset(self) -> None:
        """Forget per-turn state (call before each turn so role/line tracking starts clean)."""
        self._mid_line = False

    def _dim(self, text: str) -> str:
        return f"{_DIM}{text}{_RESET}" if self._colour else text

    def _break_line(self) -> None:
        """End a half-written prose line before printing a structured (tool/status) line."""
        if self._mid_line:
            self._out.write("\n")
            self._mid_line = False

    def _status(self, text: str) -> None:
        self._break_line()
        self._out.write(self._dim(text) + "\n")
        self._out.flush()

    def emit(self, event: Event) -> None:
        payload = event.payload
        if event.kind is EventKind.RUN_TEXT:
            text = str(payload.get("text", ""))
            if text:
                self._out.write(text)
                self._out.flush()
                self._mid_line = not text.endswith("\n")
            return
        if event.kind is EventKind.RUN_TOOL_USE:
            self._status(f"  [tool {payload.get('tool', '?')}]")
            return
        if event.kind is EventKind.RUN_TOOL_RESULT:
            flag = "error" if payload.get("is_error") else "ok"
            self._status(f"  [-> {payload.get('tool', '?')} {flag}]")
            return
        if event.kind is EventKind.RUN_EVALUATED:
            self._status("  [evaluated]")
            return
        # RUN_STARTED / RUN_DONE and everything else are silent — the prose + footer carry the turn.

    def end_turn(self) -> None:
        """Close any half-written prose line so the footer starts on its own line."""
        self._break_line()


class ChatBeatService:
    """Sync bridge from the chat loop to the async kernel — one ``tick`` + ``drain`` per turn.

    Mirrors ``chorus_cli._beats.SchedulerTickRunner`` but is constructed directly from a wired
    :class:`Scheduler` (whose ``event_bus`` is a :class:`ChatRenderBus`), so a test can hand it a
    scheduler backed by a fake beat runner with no dream import. ``model`` / ``working_dir`` are
    surfaced for the ``/info`` slash command; ``harness_spec`` is the employee's full
    :class:`~chorus.roles.RoleBeatConfig` — every ``build_harness`` component — surfaced for ``/config``
    (``None`` when the service was built without a resolved role, e.g. an old test harness).
    ``workspace`` + ``employee_id`` are the branch-isolated worktree handle ``/merge`` integrates back
    into the company ``main`` (``None`` when the role runs unisolated).
    """

    def __init__(
        self,
        scheduler: Scheduler,
        *,
        model: str,
        working_dir: str,
        harness_spec: RoleBeatConfig | None = None,
        workspace: CompanyWorkspace | None = None,
        employee_id: str | None = None,
    ) -> None:
        self._scheduler = scheduler
        self.model = model
        self.working_dir = working_dir
        self.harness_spec = harness_spec
        self.workspace = workspace
        self.employee_id = employee_id

    def run_turn(self) -> TickReport:
        """Dispatch the queued wake(s) and await the beat — returns the pulse's :class:`TickReport`."""
        return asyncio.run(self._tick_and_drain())

    async def _tick_and_drain(self) -> TickReport:
        report = await self._scheduler.tick_once()
        await self._scheduler.drain()
        return report


@dataclass
class _ChatState:
    """Per-session chat UI state. Conversation SoT is ``agent_session`` in the ledger."""

    last_task_id: str | None = None


def _wake_already_queued(ledger: Ledger, task_id: str) -> bool:
    """True iff a wake referencing ``task_id`` is already queued (dedupe the steer re-wake)."""
    return any(w.payload.get("task_id") == task_id for w in ledger.wakes.queued())


def ensure_task(ledger: Ledger, employee_id: str, line: str) -> tuple[str, str]:
    """Record the line as a message and make sure a beat will run for it (spec: auto-promote).

    Returns ``(task_id, mode)`` where ``mode`` is ``"attach"`` (re-woke a live workable task) or
    ``"promote"`` (created + assigned a fresh task from the line). The mailbox message stays for
    coordination; the operator line is also appended to ``agent_session`` (conversation SoT).
    """
    open_task = ledger.tasks.open_for_assignee(employee_id)
    if open_task is not None:
        ledger.messages.send(_message(employee_id, line, task_id=open_task.id))
        _record_operator_turn(ledger, employee_id=employee_id, task_id=open_task.id, line=line)
        if not _wake_already_queued(ledger, open_task.id):
            ledger.wakes.enqueue(
                Wake(
                    id=mint_id(),
                    employee_id=employee_id,
                    reason=WakeReason.RECOVERY,
                    payload={"task_id": open_task.id, "cause": "chat_steer"},
                )
            )
        return open_task.id, "attach"
    task_id = mint_id()
    ledger.tasks.submit(Task(id=task_id, intent=line))
    ledger.messages.send(_message(employee_id, line, task_id=task_id))
    # No ``assigned_by`` — like the ``assign`` command; the activity actor FKs employees, and the
    # console operator is a user, not an employee.
    assign_task(ledger, task_id, employee_id)
    _record_operator_turn(ledger, employee_id=employee_id, task_id=task_id, line=line)
    return task_id, "promote"


def _record_operator_turn(
    ledger: Ledger, *, employee_id: str, task_id: str, line: str
) -> None:
    """Append the console operator line into the task's durable agent_session transcript."""
    from chorus.ledger import dream_session_key_for_task, ensure_open_session

    session = ensure_open_session(
        ledger,
        employee_id=employee_id,
        task_id=task_id,
        dream_session_key=dream_session_key_for_task(task_id),
        model="",
        system_prompt=None,
        run_id=None,
    )
    append_user_turn(ledger, session.id, line)


def _transcript_lines(ledger: Ledger, task_id: str | None) -> list[tuple[str, str]]:
    """Load display lines from the ledger agent_session for ``task_id``."""
    if task_id is None:
        return []
    session = ledger.agent_sessions.get_open_for_task(task_id)
    if session is None:
        session = ledger.agent_sessions.latest_for_task(task_id)
    if session is None:
        return []
    lines: list[tuple[str, str]] = []
    for message in load_transcript(ledger, session.id):
        text_parts = [
            str(block.get("text", "")).strip()
            for block in message.content
            if isinstance(block.get("text"), str)
        ]
        text = "\n".join(p for p in text_parts if p)
        if not text:
            continue
        who = _OPERATOR if message.role is ConversationRole.USER else "employee"
        lines.append((who, text))
    return lines


def _transcript_turn_count(ledger: Ledger, task_id: str | None) -> int:
    return len(_transcript_lines(ledger, task_id))


def _message(employee_id: str, body: str, *, task_id: str) -> Message:
    return Message(
        id=mint_id(),
        to_employee_id=employee_id,
        body=body,
        kind=MessageKind.INSTRUCTION,
        from_user_id=_OPERATOR,
        task_id=task_id,
    )


def _turn_cost_cents(ledger: Ledger, task_id: str) -> tuple[str, int | None]:
    """Best-effort ``(run_status, cost_cents)`` for the most recent run of ``task_id``.

    ``cost`` is ``None`` when no run exists (the beat never started — e.g. a budget gate); otherwise
    it sums the run's recorded cost events (0 when the beat was unpriced).
    """
    runs = ledger.runs.for_task(task_id)
    if not runs:
        return "no-run", None
    run = runs[-1]
    cost = sum(event.cost_cents for event in ledger.cost_events.for_run(run.id))
    return run.status.value, cost


def _turn_failure_reason(ledger: Ledger, task_id: str) -> str | None:
    """A short, human reason the turn failed — so a blocked turn is never a silent ``cost=0c``.

    Distinguishes the cases that need different responses: a *transient* planner/evaluator parse blip
    (re-send the line), a hard engine fault, or a met-the-plan-but-failed-the-DoD verdict.
    """
    runs = ledger.runs.for_task(task_id)
    if not runs or runs[-1].status.value != "failed":
        return None
    error = str((runs[-1].outcome or {}).get("error") or "")
    if "HeadParseError" in error:
        return "planner parse error (transient — re-send the line)"
    if error:
        return f"errored ({error.split('(')[0][:48]})"
    return "DoD not met"  # the beat ran but the acceptance gate (e.g. pytest/ruff) rejected it


def _render_footer(console: Console, *, task_id: str, report: TickReport, ledger: Ledger) -> None:
    """Close the turn with a one-line verdict (task status, run status, spend) — dream-style."""
    task = ledger.tasks.get(task_id)
    status = task.status.value if task is not None else "?"
    run_status, cost = _turn_cost_cents(ledger, task_id)
    bits = [f"task={task_id}", f"status={status}", f"run={run_status}"]
    if cost is not None:
        bits.append(f"cost={cost}c")
    if report.budget_gated:
        bits.append("budget-gated")
    reason = _turn_failure_reason(ledger, task_id)
    if reason is not None:
        bits.append(reason)  # name the cause, not a silent cost=0c
    console.line(f"  [{' '.join(bits)}]")


_HELP = """\
chat commands:
  /help              this message
  /quit | /exit      leave chat (back to the console)
  /info              employee, model, working dir, active task
  /config            the employee's full harness config (every component)
  /merge             merge this employee's isolated worktree into company main
  /task              the current/last task with its runs
  /transcript        ledger session transcript (SoT)
type anything else to send it to the employee as a turn.\
"""


def _fmt_list(values: tuple[str, ...]) -> str:
    """Render a tool/skill allow-list for display — the names, or ``(none)`` when empty."""
    return ", ".join(values) if values else "(none)"


def _cmd_config(
    console: Console, *, employee_id: str, service: ChatBeatService, ledger: Ledger
) -> None:
    """Show the employee's complete dream-harness config — every ``build_harness`` component.

    This is "the chat representing the employee": the resolved role projected to a
    :class:`~chorus.roles.RoleBeatConfig`, one row per harness knob, so you can see exactly what this
    employee *is* before you task it.
    """
    spec = service.harness_spec
    if spec is None:
        console.line(
            "no resolved role config (keys-free chat) — set Azure creds for a real harness"
        )
        return
    employee = ledger.employees.get(employee_id)
    role = employee.role if employee is not None else "?"
    memory = spec.memory_scope + (" +working-scratchpad" if spec.working_memory else "")
    isolated = service.workspace is not None and spec.isolation == "worktree"
    isolation = f"worktree → branch chorus/{employee_id}" if isolated else spec.isolation
    console.kv(
        {
            "employee": f"{employee_id} ({role})",
            "model": spec.model or service.model,
            "max_turns": spec.max_turns,
            "permission": spec.permission_mode,
            "memory": memory,
            "isolation": isolation,
            "trust": spec.sandbox,
            "tools": _fmt_list(spec.tools),
            "skills": _fmt_list(spec.skills),
            "mcp": "on" if spec.mcp else "off",
            "plugins": "on" if spec.plugins else "off",
            "wake_model": spec.wake_model or "(deployment)",
            "env": _fmt_list(tuple(f"{k}={v}" for k, v in spec.env)),
            "working_dir": service.working_dir,
        }
    )


def _cmd_merge(console: Console, *, service: ChatBeatService) -> None:
    """Merge this employee's branch-isolated worktree back into the company ``main``.

    The "merged later" half of containment: the employee worked confined to ``chorus/{employee}``;
    this snapshots any uncommitted work and integrates the branch. A conflict is reported, not raised.
    """
    if service.workspace is None or service.employee_id is None:
        console.line("no isolated worktree to merge (this role runs unisolated)")
        return
    result = service.workspace.merge(service.employee_id)
    if result.merged:
        console.line(f"  [merged {result.branch} → {result.into}]")
    elif result.conflicted:
        console.error(
            f"merge conflict on {result.branch} (aborted) — resolve in {service.workspace.repo}"
        )
    else:
        console.error(f"merge failed: {result.detail}")


def _cmd_info(
    console: Console,
    *,
    employee_id: str,
    service: ChatBeatService,
    state: _ChatState,
    ledger: Ledger,
) -> None:
    open_task = ledger.tasks.open_for_assignee(employee_id)
    console.kv(
        {
            "employee": employee_id,
            "model": service.model,
            "working_dir": service.working_dir,
            "active_task": open_task.id if open_task is not None else "-",
            "turns": _transcript_turn_count(ledger, state.last_task_id),
        }
    )


def _cmd_task(console: Console, *, state: _ChatState, ledger: Ledger) -> None:
    if state.last_task_id is None:
        console.line("no task yet — send a line first")
        return
    task = ledger.tasks.get(state.last_task_id)
    if task is None:
        console.error(f"task {state.last_task_id!r} vanished")
        return
    console.kv({"id": task.id, "intent": task.intent, "status": task.status.value})
    runs = ledger.runs.for_task(task.id)
    console.table(
        ("run", "status", "started", "finished"),
        [(r.id, r.status.value, str(r.started_at), str(r.finished_at)) for r in runs],
    )


def _cmd_transcript(console: Console, *, state: _ChatState, ledger: Ledger) -> None:
    lines = _transcript_lines(ledger, state.last_task_id)
    if not lines:
        console.line("(no turns yet)")
        return
    for who, body in lines:
        console.line(f"  {who}: {body}")


def _slash(
    line: str,
    *,
    console: Console,
    employee_id: str,
    service: ChatBeatService,
    state: _ChatState,
    ledger: Ledger,
) -> bool:
    """Handle a ``/command``. Returns ``True`` to keep chatting, ``False`` to leave chat."""
    cmd = line.strip().split(maxsplit=1)[0].lower()
    if cmd in ("/quit", "/exit"):
        return False
    if cmd == "/help":
        console.line(_HELP)
    elif cmd == "/info":
        _cmd_info(console, employee_id=employee_id, service=service, state=state, ledger=ledger)
    elif cmd == "/config":
        _cmd_config(console, employee_id=employee_id, service=service, ledger=ledger)
    elif cmd == "/merge":
        _cmd_merge(console, service=service)
    elif cmd == "/task":
        _cmd_task(console, state=state, ledger=ledger)
    elif cmd == "/transcript":
        _cmd_transcript(console, state=state, ledger=ledger)
    else:
        console.error(f"unknown command {cmd!r}; /help for the list")
    return True


def run_chat(
    employee_id: str,
    *,
    ledger: Ledger,
    service: ChatBeatService,
    render_bus: ChatRenderBus,
    console: Console,
    input_func: Callable[[str], str],
) -> None:
    """Drive the conversational loop with ``employee_id`` until ``/quit`` or end-of-input.

    Each non-slash line becomes a turn: record + auto-promote the line into a task, run one scheduler
    pulse (the beat streams its reply through ``render_bus``), then print a verdict footer. A failed
    turn is reported and the loop continues — a beat error never drops you out of chat.
    """
    console.line(f"chatting with {employee_id} (model {service.model}) — /help, /quit to leave")
    state = _ChatState()
    prompt = f"{employee_id}> "
    while True:
        try:
            line = input_func(prompt)
        except (EOFError, KeyboardInterrupt):
            console.line()
            return
        if not line.strip():
            continue
        if line.startswith("/"):
            if not _slash(
                line,
                console=console,
                employee_id=employee_id,
                service=service,
                state=state,
                ledger=ledger,
            ):
                return
            continue

        try:
            task_id, _ = ensure_task(ledger, employee_id, line)
            state.last_task_id = task_id
            render_bus.reset()
            report = service.run_turn()
        except Exception as exc:  # a turn failure must never drop the operator out of chat
            render_bus.end_turn()
            console.error(f"{type(exc).__name__}: {exc}")
            continue
        render_bus.end_turn()
        _render_footer(console, task_id=task_id, report=report, ledger=ledger)


__all__ = [
    "ChatBeatService",
    "ChatRenderBus",
    "ensure_task",
    "run_chat",
]
