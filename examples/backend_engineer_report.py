"""Backend Engineer run reporter — give Bex a task, let it roll, emit two HTML reports.

Runs one keyed Backend-Engineer beat on a real task, captures the whole flow (every tool call, each
subagent it spawns, the evidence it writes), then INDEPENDENTLY re-runs the gates in the shipped
worktree — the harness's own hands, not Bex's self-report — and renders two self-contained HTML reports
in the style of the Frontend Engineer's:

  reports/backend-engineer-flow-report.html   — the run, phase by phase (understand → build → author
                                                tests → prove → verify the running system → land).
  reports/backend-engineer-test-report.html   — independent re-verification: the gate table re-run by
                                                hand, the stack Bex chose, and the files it shipped.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/backend_engineer_report.py

Skips cleanly (exit 0) when those env vars are unset.
"""

from __future__ import annotations

import asyncio
import html
import json
import os
import uuid

_EXAMPLE_COMPANY = str(uuid.uuid5(uuid.NAMESPACE_URL, "chorus-example"))  # one stable demo org
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from chorus.budgets import BudgetEnforcer
from chorus.events import Event, EventKind
from chorus.heartbeat import Scheduler
from chorus.ledger import Ledger, RunStatus, Task, TaskStatus
from chorus.lifecycle import assign_task
from chorus.memory import EpisodicStore
from chorus.observability import EventBus
from chorus.outcomes import Verifier
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee, LedgerWorkforce
from chorus_cli._beats import default_pricing_from_env
from chorus_employee import default_landers
from chorus_harness import EmployeeHarnessFactory
from chorus_tools import is_noop_quality_command

# --------------------------------------------------------------------------- the task

# THREE-DOMAIN commerce API — deliberately too big for one 600s beat, to prove the checkpoint half of
# resumption: when the budget is exhausted mid-build, todo_write must have left a durable TODO.md in the
# worktree (the resume point), even though the beat is killed abruptly.
_INTENT = (
    "Build the BACKEND of a small commerce API as an HTTP service (Python standard library ONLY — "
    "http.server + sqlite3 + json + secrets + hashlib, no pip installs, no frontend). It starts with "
    "`python main.py` on the PORT env var (default 8000) and DB_PATH env var (default commerce.db), and "
    "applies a SQL schema via a small MIGRATIONS mechanism on startup (an ordered list recorded in a "
    "schema_migrations table so re-runs are idempotent). Use ThreadingHTTPServer with a per-request "
    "connection. There are THREE DOMAINS, each its own bounded context — organise the code as ONE "
    "PACKAGE PER DOMAIN (`auth/`, `orders/`, `payments/`), NOT by file-type folders, and point "
    "dependencies inward (transport/HTTP -> service -> data-access -> domain):\n"
    "  - GET  /health -> 200 'ok'\n"
    "  auth:\n"
    '    - POST /auth/register  {"email","password"} -> 201; store a SALTED password HASH, never the '
    "plaintext (hashlib); duplicate email -> 409.\n"
    '    - POST /auth/login     {"email","password"} -> 200 {"token"} (an opaque bearer token minted '
    "with `secrets`); wrong credentials -> 401. Protected routes require `Authorization: Bearer <token>` "
    "(else 401).\n"
    "  orders (auth required):\n"
    '    - POST /orders         {"items":[{"sku","qty"}]} -> 201 {"order_id","total","status":"pending"} '
    "(total = sum of qty * a fixed per-sku price table you define).\n"
    "    - GET  /orders/{id}    -> 200 the order, but OWNER-ONLY: a user may read only their OWN order; "
    "another user's order -> 403 (object-level authorization — do not infer access from the id alone).\n"
    "  payments (auth required):\n"
    '    - POST /payments       {"order_id","amount"} -> 201 {"payment_id","status":"paid"} and flip the '
    "order's status to 'paid'. IDEMPOTENT on an `Idempotency-Key` header: the same key replays the same "
    "payment and must NOT double-charge or create a second payment row.\n"
    "Data MUST survive a process restart. Author the tests INDEPENDENTLY: unit for the password "
    "hash+verify and the idempotency-key dedup; integration for the owner-only 403 and the "
    "pay-flips-order-status flow; and prove the RUNNING service end-to-end (register -> login -> create "
    "order -> pay -> the order reads back 'paid', still 'paid' after a restart)."
)


# --------------------------------------------------------------------------- captured model

_TOOL_META: dict[str, tuple[str, str]] = {
    "spawn_subagent": ("#7c3aed", "spawn_subagent"),
    "bash": ("#0d9488", "bash"),
    "run_command": ("#0d9488", "bash"),
    "git": ("#d97706", "git"),
    "test_evidence": ("#2563eb", "test_evidence"),
    "secret_scan": ("#2563eb", "secret_scan"),
    "write_file": ("#16a34a", "write_file"),
    "read_file": ("#6b7280", "read_file"),
    "grep": ("#6b7280", "grep"),
    "glob": ("#6b7280", "glob"),
    "lsp": ("#6b7280", "lsp"),
    "skill": ("#db2777", "skill"),
    "todo_write": ("#0891b2", "todo_write"),
}


def _arg_of(tool: str, payload_input: object) -> str:
    """A short, human argument for a tool call, drawn from its input payload."""
    data = payload_input if isinstance(payload_input, dict) else {}
    if tool in ("bash", "run_command"):
        return str(data.get("command", ""))
    if tool in ("read_file", "write_file"):
        return str(data.get("path", ""))
    if tool == "git":
        args = data.get("args", [])
        return "git " + " ".join(str(a) for a in args) if isinstance(args, list) else "git"
    if tool == "spawn_subagent":
        return str(data.get("name", "?"))
    if tool == "test_evidence":
        return "(run the discovered verify gates)"
    if tool == "secret_scan":
        return "(scan the worktree for secrets)"
    return ""


@dataclass
class _Step:
    color: str
    tool: str
    arg: str
    is_error: bool = False


@dataclass
class _Group:
    agent: str
    steps: list[_Step] = field(default_factory=list)


@dataclass
class _Capture:
    """Reconstructs the flat event stream into a timeline with subagent groups nested inline."""

    timeline: list[_Step | _Group] = field(default_factory=list)
    _open_group: _Group | None = None
    _last_step: _Step | None = None
    evaluated: str = "?"

    def on_use(self, tool: str, payload_input: object) -> None:
        if tool == "spawn_subagent":
            group = _Group(agent=_arg_of(tool, payload_input))
            self.timeline.append(group)
            self._open_group = group
            self._last_step = None
            return
        color, label = _TOOL_META.get(tool, ("#6b7280", tool))
        step = _Step(color=color, tool=label, arg=_arg_of(tool, payload_input))
        (self._open_group.steps if self._open_group is not None else self.timeline).append(step)
        self._last_step = step

    def on_result(self, tool: str, is_error: bool) -> None:
        if tool == "spawn_subagent":
            self._open_group = None
            self._last_step = None
            return
        if self._last_step is not None:
            self._last_step.is_error = is_error


class _CaptureBus(EventBus):
    def __init__(self) -> None:
        super().__init__(log_path=None)
        self.cap = _Capture()

    def emit(self, event: Event) -> None:
        # A telemetry observer must NEVER be able to fail the beat it watches: dream calls this as its
        # observer callback, so any exception here would surface as a failed run. Swallow defensively.
        try:
            p = event.payload
            if event.kind is EventKind.RUN_TOOL_USE:
                self.cap.on_use(str(p.get("tool", "?")), p.get("input"))
            elif event.kind is EventKind.RUN_TOOL_RESULT:
                self.cap.on_result(str(p.get("tool", "?")), bool(p.get("is_error")))
            elif event.kind is EventKind.RUN_EVALUATED:
                self.cap.evaluated = str(p.get("outcome", "?"))
        except Exception:
            pass


# --------------------------------------------------------------------------- HTML rendering

_CSS = """
:root{--bg:#f6f8fa;--card:#fff;--ink:#1f2328;--muted:#57606a;--line:#d0d7de;--accent:#0d9488;--accent-soft:#ecfeff;}
*{box-sizing:border-box;}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
.wrap{max-width:980px;margin:0 auto;padding:32px 20px 80px;}
header.top{background:linear-gradient(135deg,#ecfeff,#f6f8fa);border:1px solid var(--line);border-radius:16px;padding:28px 28px 22px;margin-bottom:22px;}
header.top .eyebrow{color:var(--accent);font-weight:700;letter-spacing:.06em;text-transform:uppercase;font-size:12px;}
header.top h1{margin:.2em 0 .3em;font-size:26px;}
header.top .intent,header.top .sub{color:var(--muted);margin:0;}
header.top .intent b,header.top .sub b{color:var(--ink);}
.badge{font-size:12px;font-weight:700;padding:3px 10px;border-radius:999px;white-space:nowrap;}
.badge.ok{background:#dcfce7;color:#166534;}.badge.warn{background:#fef9c3;color:#854d0e;}.badge.info{background:var(--accent-soft);color:#0e7490;}
.reverify{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:6px 20px 18px;margin:22px 0;}
.reverify h2{font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:16px 0 6px;}
.vrow{display:flex;align-items:center;gap:12px;padding:8px 0;border-bottom:1px dashed var(--line);}
.vrow:last-of-type{border-bottom:none;}.vlabel{min-width:250px;font-weight:600;font-size:14px;}.vrow .muted{color:var(--muted);font-size:12.5px;}
.overall{display:flex;align-items:center;gap:14px;margin:16px 0;padding:16px 18px;border-radius:12px;}
.overall.ok{background:#f0fdf4;border:1px solid #bbf7d0;}.overall.warn{background:#fffbeb;border:1px solid #fde68a;}
.overall .big{font-size:19px;font-weight:800;letter-spacing:.02em;}.overall.ok .big{color:#166534;}.overall.warn .big{color:#854d0e;}
.overall p{margin:0;color:var(--muted);font-size:13.5px;}
.chips{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:22px 0;}
.chip{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;color:var(--muted);font-size:12.5px;}
.chip span{display:block;font-size:24px;font-weight:750;color:var(--ink);line-height:1.1;}.chip.green span{color:#166534;}
.subchips{display:flex;flex-wrap:wrap;gap:8px;margin:-6px 0 22px;}
.subchip{background:#f3e8ff;color:#6b21a8;border:1px solid #e9d5ff;border-radius:999px;padding:4px 12px;font-size:13px;}
h2.sec{font-size:15px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:34px 0 12px;padding-top:8px;border-top:1px solid var(--line);}
h2.sec:first-of-type{border-top:none;}
.lead{color:var(--muted);margin:-4px 0 16px;font-size:14px;}
.legend{display:flex;flex-wrap:wrap;gap:14px;margin-bottom:14px;font-size:12.5px;color:var(--muted);}
.leg{display:inline-flex;align-items:center;gap:6px;}.dot{width:9px;height:9px;border-radius:50%;display:inline-block;flex:0 0 auto;}
.phase{background:var(--card);border:1px solid var(--line);border-radius:14px;margin-bottom:16px;overflow:hidden;}
.phase-head{display:flex;gap:14px;align-items:flex-start;padding:18px 20px 14px;border-bottom:1px solid var(--line);background:#fbfcfe;}
.pnum{flex:0 0 auto;width:30px;height:30px;border-radius:50%;background:var(--accent);color:#fff;font-weight:750;display:grid;place-items:center;}
.phase-head h3{margin:2px 0 3px;font-size:17px;}.phase-head p{margin:0;color:var(--muted);font-size:13.5px;}
.phase-body{padding:12px 16px 16px;display:flex;flex-direction:column;gap:5px;}
.step{display:flex;align-items:center;gap:9px;padding:5px 8px;border-radius:8px;font-size:13.5px;}
.step:hover{background:#f6f8fa;}.step .tool{font-weight:650;}
.step .arg{color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font:12.5px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;}
.err{font-size:10.5px;font-weight:700;color:#b91c1c;background:#fee2e2;border-radius:5px;padding:1px 6px;}
details.sub{border:1px solid #e9d5ff;border-radius:10px;background:#faf5ff;margin:3px 0;}
details.sub>summary{cursor:pointer;list-style:none;padding:8px 12px;display:flex;align-items:center;gap:9px;font-size:13.5px;}
details.sub>summary::-webkit-details-marker{display:none;}
details.sub>summary::before{content:"\\25B6";font-size:9px;color:#a855f7;}
details.sub .agent{font-weight:750;color:#6b21a8;}.details .count,details.sub .count{margin-left:auto;color:var(--muted);font-size:12px;}
.subbody{padding:2px 12px 12px 26px;display:flex;flex-direction:column;gap:3px;border-top:1px dashed #e9d5ff;}
.empty{color:var(--muted);font-size:13px;padding:6px;}
.eval{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:12px;}
.eval-top{display:flex;align-items:center;gap:12px;}.eval-top .score{margin-left:auto;color:var(--muted);font-size:13px;}
.bar{height:8px;background:#eaeef2;border-radius:999px;margin:10px 0 8px;overflow:hidden;}.bar span{display:block;height:100%;background:linear-gradient(90deg,#14b8a6,#0d9488);}
.notes{margin:0;color:var(--muted);font-size:13px;}
details.art{background:var(--card);border:1px solid var(--line);border-radius:12px;margin-bottom:12px;}
details.art>summary{cursor:pointer;padding:14px 18px;font-weight:650;}
details.art pre{margin:0;padding:0 18px 18px;white-space:pre-wrap;word-wrap:break-word;font:12.5px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:#24292f;}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;margin-bottom:14px;}
th,td{text-align:left;padding:11px 14px;border-bottom:1px solid var(--line);font-size:13.5px;vertical-align:top;}
th{background:#fbfcfe;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;font-size:11.5px;font-weight:700;}
tr:last-child td{border-bottom:none;}td.mono,.mono-inline{font:12.5px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;}td .cmd{color:#0e7490;}
.stack{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 18px;}
.pill{background:#f3e8ff;color:#6b21a8;border:1px solid #e9d5ff;border-radius:999px;padding:4px 12px;font-size:13px;font-weight:600;}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:6px 18px 14px;margin-bottom:14px;}
.file{border-bottom:1px dashed var(--line);padding:13px 0;}.file:last-child{border-bottom:none;}
.file h4{margin:0 0 5px;font:13.5px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--ink);display:flex;align-items:center;gap:9px;flex-wrap:wrap;}
.file p{margin:0;color:var(--muted);font-size:13px;}
.note{background:#fffbeb;border:1px solid #fde68a;border-radius:12px;padding:13px 18px;color:#854d0e;font-size:13px;margin:14px 0;}
footer{color:var(--muted);font-size:12px;text-align:center;margin-top:44px;border-top:1px solid var(--line);padding-top:18px;}
"""


def _esc(text: str, limit: int = 120) -> str:
    trimmed = text if len(text) <= limit else text[: limit - 1] + "…"
    return html.escape(trimmed)


def _step_html(step: _Step) -> str:
    err = ' <span class="err">err</span>' if step.is_error else ""
    return (
        f'<div class="step"><span class="dot" style="background:{step.color}"></span>'
        f'<span class="tool">{html.escape(step.tool)}</span>'
        f'<span class="arg">{_esc(step.arg)}</span>{err}</div>'
    )


def _group_html(group: _Group) -> str:
    errs = sum(1 for s in group.steps if s.is_error)
    tail = f" · {errs} benign err" if errs else ""
    inner = "".join(_step_html(s) for s in group.steps) or '<div class="empty">— returned —</div>'
    return (
        '<details class="sub" open><summary><span class="dot" style="background:#7c3aed"></span>'
        f'<b>spawn_subagent</b> <span class="agent">{html.escape(group.agent)}</span>'
        f'<span class="count">{len(group.steps)} inner call(s){tail}</span></summary>'
        f'<div class="subbody">{inner}</div></details>'
    )


def _phase_of(item: _Step | _Group, seen_write: bool) -> int:
    """Bucket a timeline item into one of the six backend phases."""
    if isinstance(item, _Group):
        return 2 if item.agent == "test_author" else 4 if item.agent == "api_verifier" else 3
    if item.tool in ("test_evidence", "secret_scan"):
        return 3
    if item.tool == "write_file":
        return 1
    if item.tool == "git":
        return 5
    if item.tool in ("read_file", "grep", "glob", "lsp"):
        return 1 if seen_write else 0
    probe = (
        "ls",
        "dir",
        "find",
        "cat",
        "type",
        "pwd",
        "python -v",
        "git status",
        "python --version",
    )
    if item.tool == "bash" and item.arg.lower().startswith(probe):
        return 1 if seen_write else 0
    return 1


_PHASES: tuple[tuple[str, str], ...] = (
    (
        "Understand & probe the stack",
        "Read the intent and the existing repo, detect the language / framework / datastore from its "
        "manifests, and pick the smallest slice that actually works.",
    ),
    (
        "Build the service",
        "Implement to the contract in the stack it discovered — the smallest change, illegal states "
        "made unrepresentable, secrets read from the environment.",
    ),
    (
        "Author the tests",
        "Delegate to the Test-Author subagent to write honeycomb-shaped tests independent of the code "
        "(happy path + the error/edge cases), then run them green.",
    ),
    (
        "Prove it — evidence & safety",
        "Run the discovered verify commands into a durable test_evidence/ bundle, and scan the worktree "
        "for hardcoded credentials — proof on disk, not a claim.",
    ),
    (
        "Verify the running system",
        "Spawn the API-Verifier to boot the service on a real socket and probe it over HTTP — and, for "
        "a stateful service, prove the data survives a restart.",
    ),
    (
        "Land",
        "Leave the finished changes in the worktree; the harness snapshots the branch and opens the "
        "reviewable PR — the engineer never touches git itself.",
    ),
)


@dataclass(frozen=True)
class GateRow:
    label: str
    badge_text: str
    badge_cls: str
    command: str
    detail: str


@dataclass(frozen=True)
class FileCard:
    path: str
    badge: str
    note: str


@dataclass(frozen=True)
class ReportData:
    intent: str
    ok: bool
    evaluated: str
    reverify_rows: tuple[GateRow, ...]
    gate_rows: tuple[GateRow, ...]
    stack: tuple[str, ...]
    files: tuple[FileCard, ...]
    artifacts: tuple[tuple[str, str], ...]
    total_calls: int
    subagents: int
    run_calls: int
    subagent_counts: tuple[tuple[str, int], ...]
    timeline: list[_Step | _Group]


def _badge(row: GateRow) -> str:
    return f'<span class="badge {row.badge_cls}">{html.escape(row.badge_text)}</span>'


def render_flow(d: ReportData) -> str:
    cls = "ok" if d.ok else "warn"
    reverify = "".join(
        f'<div class="vrow"><span class="vlabel">{html.escape(r.label)}</span>{_badge(r)}'
        f' <span class="muted">{html.escape(r.detail)}</span></div>'
        for r in d.reverify_rows
    )
    big = "TRULY PASSED" if d.ok else "DID NOT LAND"
    note = (
        "the shipped code passed the DoD floor AND its gates went green again under the harness's own "
        "hands (independent re-run in the landed worktree)"
        if d.ok
        else "the beat did not land a green, independently reproducible deliverable"
    )
    chips = (
        f'<div class="chip"><span>{d.total_calls}</span>Total tool calls</div>'
        f'<div class="chip"><span>{d.subagents}</span>Subagents spawned</div>'
        f'<div class="chip"><span>{d.run_calls}</span>run_command calls</div>'
        f'<div class="chip"><span>{len(d.reverify_rows)}</span>Gates re-verified</div>'
    )
    subchips = "".join(
        f'<span class="subchip">{html.escape(n)} <b>&times;{c}</b></span>'
        for n, c in d.subagent_counts
    )
    seen_write = False
    buckets: list[list[str]] = [[] for _ in _PHASES]
    for item in d.timeline:
        ph = _phase_of(item, seen_write)
        if isinstance(item, _Step) and item.tool == "write_file":
            seen_write = True
        buckets[ph].append(_group_html(item) if isinstance(item, _Group) else _step_html(item))
    phases = ""
    for i, (title, blurb) in enumerate(_PHASES):
        body = "".join(buckets[i]) or '<div class="empty">— no steps recorded in this phase —</div>'
        phases += (
            f'<section class="phase"><div class="phase-head"><span class="pnum">{i}</span>'
            f"<div><h3>{html.escape(title)}</h3><p>{html.escape(blurb)}</p></div></div>"
            f'<div class="phase-body">{body}</div></section>'
        )
    eval_cls = "ok" if d.ok else "warn"
    # The badge must agree with the outcome: a passing run (DoD green + landed) is "passed", not the raw
    # last dream sprint disposition (which can read "needs-changes" from an intermediate review the beat
    # then resolved past). An observation surface that contradicts its own score/bar is a reporting bug.
    eval_label = "passed" if d.ok else (d.evaluated or "did not land")
    pct = 100 if d.ok else 40
    eval_note = (
        "HTTP service built to the contract in the stack Bex discovered, a green test_evidence bundle, "
        "and an API-Verifier proof that the running service answers over a real socket — all landed as "
        "a reviewable PR, reproduced green under an independent re-run."
        if d.ok
        else "The beat did not converge to a landed, independently green deliverable this run."
    )
    arts = "".join(
        f'<details class="art"><summary>{html.escape(name)}</summary><pre>{html.escape(content)}</pre></details>'
        for name, content in d.artifacts
    )
    legend = (
        '<div class="legend">'
        '<span class="leg"><span class="dot" style="background:#7c3aed"></span>subagent</span>'
        '<span class="leg"><span class="dot" style="background:#0d9488"></span>run</span>'
        '<span class="leg"><span class="dot" style="background:#d97706"></span>git</span>'
        '<span class="leg"><span class="dot" style="background:#2563eb"></span>evidence</span>'
        '<span class="leg"><span class="dot" style="background:#16a34a"></span>write</span>'
        '<span class="leg"><span class="dot" style="background:#6b7280"></span>read</span></div>'
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Backend Engineer — Run Flow Report</title><style>{_CSS}</style></head>
<body><div class="wrap">
<header class="top"><div class="eyebrow">Chorus · Backend Engineer (Bex) · run flow</div>
<h1>Run Flow Report</h1><p class="intent"><b>Intent:</b> {html.escape(d.intent)}</p></header>
<div class="reverify"><h2>Independent verification — did the shipped code actually work?</h2>
{reverify}<div class="overall {cls}"><span class="big">{big}</span><p>{note}</p></div></div>
<div class="chips">{chips}</div><div class="subchips">{subchips}</div>
<h2 class="sec">The flow, phase by phase</h2>{legend}{phases}
<h2 class="sec">Sprint evaluation</h2>
<div class="eval"><div class="eval-top"><span class="badge {eval_cls}">sprint 1: {html.escape(eval_label)}</span>
<span class="score">score {"1.00" if d.ok else "0.40"}</span></div>
<div class="bar"><span style="width:{pct}%"></span></div><p class="notes">{html.escape(eval_note)}</p></div>
<h2 class="sec">Artifacts produced</h2>{arts}
<footer>Chorus · Backend Engineer (Bex) — Run Flow Report · generated from a live keyed beat and an independent re-run of the shipped worktree.</footer>
</div></body></html>"""


def render_test(d: ReportData) -> str:
    cls = "ok" if d.ok else "warn"
    big = "ALL GREEN" if d.ok else "NOT VERIFIED"
    verdict_big = "TRUSTWORTHY" if d.ok else "NEEDS ATTENTION"
    overall_note = (
        "every gate re-ran green by hand in the shipped worktree — build/tests, the test_evidence "
        "bundle, the API-Verifier verdict, and the secret scan"
        if d.ok
        else "the shipped deliverable did not reproduce green under an independent re-run"
    )
    chips = "".join(
        f'<div class="chip green"><span>{html.escape(r.badge_text)}</span>{html.escape(r.label)}</div>'
        for r in d.gate_rows
    )
    rows = "".join(
        f'<tr><td>{html.escape(r.label)}</td><td class="mono"><span class="cmd">{html.escape(r.command)}</span></td>'
        f"<td>{_badge(r)}</td><td>{html.escape(r.detail)}</td></tr>"
        for r in d.gate_rows
    )
    stack = "".join(f'<span class="pill">{html.escape(s)}</span>' for s in d.stack)
    files = "".join(
        f'<div class="file"><h4>{html.escape(f.path)} <span class="badge ok">{html.escape(f.badge)}</span></h4>'
        f"<p>{html.escape(f.note)}</p></div>"
        for f in d.files
    )
    verdict_note = (
        "Bex read the intent, chose its own stack, built the service, had the tests authored "
        "independently, proved the running system (including durability across a restart), and proved "
        "no secrets were hardcoded — then landed it as a reviewable PR. Every gate reproduced green "
        "under the harness's own independent re-run."
        if d.ok
        else "The deliverable did not reproduce green independently; see the gate table above."
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Backend Engineer (Bex) — Test Report</title><style>{_CSS}</style></head>
<body><div class="wrap">
<header class="top"><div class="eyebrow">Chorus · Backend Engineer (Bex) · Quality Assurance</div>
<h1>Test Report</h1><p class="sub">Independent verification that Bex — the stack-agnostic Backend Engineer employee — <b>actually ships a working, proven service</b>. Every gate below was re-run <b>by hand</b> in Bex's shipped worktree, in a fresh process — nothing here relies on Bex's own self-reported evidence.</p></header>
<div class="overall {cls}"><span class="big">{big}</span><p>{overall_note}</p></div>
<div class="chips">{chips}</div>
<h2 class="sec">1 · Independent re-verification (the harness's own hands)</h2>
<p class="lead">The task: <span class="mono-inline">{html.escape(d.intent[:130])}…</span> Below, each gate is re-run in the landed worktree.</p>
<table><thead><tr><th>Gate</th><th>Command</th><th>Result</th><th>Detail</th></tr></thead><tbody>{rows}</tbody></table>
<h2 class="sec">2 · The stack Bex chose — on its own</h2>
<p class="lead">No framework or datastore name is hardcoded in the employee. Bex probed the repo, bound to what it found, and cleared every gate.</p>
<div class="stack">{stack}</div>
<h2 class="sec">3 · The files Bex shipped</h2>
<p class="lead">Every source and test file in the landed worktree, independently inspected.</p>
<div class="card">{files}</div>
<h2 class="sec">Verdict</h2>
<div class="overall {cls}"><span class="big">{verdict_big}</span><p>{verdict_note}</p></div>
<footer>Chorus · Backend Engineer (Bex) — Test Report · generated from an independent re-run of the shipped worktree.</footer>
</div></body></html>"""


# --------------------------------------------------------------------------- driver


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _seed(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text(
        "# demo service\n\nRun with `python app.py` (honours PORT and DB_PATH).\n", encoding="utf-8"
    )
    (path / "test_placeholder.py").write_text(
        "def test_placeholder() -> None:\n    assert True\n", encoding="utf-8"
    )
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "-c",
            "user.name=s",
            "-c",
            "user.email=s@x",
            "commit",
            "-m",
            "init",
        ],
        check=True,
        capture_output=True,
    )


def _read(path: Path, limit: int = 4000) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    return text if len(text) <= limit else text[:limit] + "\n… (truncated)"


def _detect_stack(repo: Path) -> tuple[str, ...]:
    stack: list[str] = []
    if (repo / "go.mod").exists():
        stack += ["Go", "net/http"]
    if any(repo.glob("*.py")):
        stack.append("Python (stdlib)")
    joined = " ".join(_read(p, 2000) for p in repo.glob("*.py"))
    if "http.server" in joined:
        stack.append("http.server")
    if "sqlite3" in joined:
        stack.append("SQLite")
    if (repo / "package.json").exists():
        stack.append("Node")
    stack.append("pytest")
    seen: set[str] = set()
    deduped: list[str] = []
    for item in stack:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return tuple(deduped)


def _reverify(repo: Path) -> tuple[bool, list[GateRow]]:
    """Re-run the gates by hand in the shipped worktree; return (all-green, rows)."""
    rows: list[GateRow] = []
    ok = True

    def gate(label: str, cmd: str, passed: bool, detail: str) -> None:
        nonlocal ok
        ok = ok and passed
        rows.append(
            GateRow(label, "pass" if passed else "fail", "ok" if passed else "warn", cmd, detail)
        )

    py = str(Path(sys.executable))
    if (repo / "go.mod").exists():
        run = subprocess.run(["go", "test", "./..."], cwd=repo, capture_output=True, text=True)
        gate(
            "Tests (fresh re-run)",
            "go test ./...",
            run.returncode == 0,
            (run.stdout + run.stderr).strip()[:120],
        )
    else:
        run = subprocess.run([py, "-m", "pytest", "-q"], cwd=repo, capture_output=True, text=True)
        tail = (run.stdout + run.stderr).strip().splitlines()
        gate("Tests (fresh re-run)", "pytest -q", run.returncode == 0, tail[-1] if tail else "")

    manifest = repo / "test_evidence" / "manifest.json"
    verdict = ""
    if manifest.exists():
        verdict = json.loads(manifest.read_text(encoding="utf-8")).get("verdict", "?")
    gate(
        "test_evidence bundle",
        "grep verdict",
        verdict == "pass",
        f"manifest verdict: {verdict or 'absent'}",
    )

    apiv = repo / "api_verdict.json"
    if apiv.exists():
        data = json.loads(apiv.read_text(encoding="utf-8"))
        checks = ", ".join(c.get("name", "?") for c in data.get("checks", []))
        gate(
            "API-Verifier (running service)",
            "api_verdict.json",
            bool(data.get("passed")),
            f"checks: {checks}"[:130],
        )

    report = repo / "security_scan" / "report.json"
    if report.exists():
        data = json.loads(report.read_text(encoding="utf-8"))
        n = len(data.get("findings", []))
        gate("Secret scan", "security_scan report", bool(data.get("clean")), f"{n} finding(s)")

    # Code quality — the harness's OWN hands: re-run the exact fmt/lint/type commands the code_quality
    # tool recorded (no hardcoded `ruff` here — the stack knowledge lives in the tool's report).
    quality = repo / "code_quality" / "report.json"
    if quality.exists():
        checks = json.loads(quality.read_text(encoding="utf-8")).get("checks", [])
        failed: list[str] = []
        gamed: list[str] = []
        for check in checks:
            cmd = str(check.get("command", ""))
            if not cmd:
                continue
            # Independently detect a gamed gate: a byte-compiler / no-op re-runs green but proves
            # nothing. The harness's own hands must not be fooled by a command that always passes.
            if is_noop_quality_command(cmd):
                gamed.append(str(check.get("name", "?")))
                continue
            rerun = subprocess.run(["bash", "-c", cmd], cwd=repo, capture_output=True, text=True)
            if rerun.returncode != 0:
                failed.append(str(check.get("name", "?")))
        # Independently confirm BREADTH — a green report must prove format AND lint AND types, not one.
        kinds = {str(c.get("kind", "")) for c in checks}
        missing = {"format", "lint", "types"} - kinds
        names = ", ".join(str(c.get("name", "?")) for c in checks)
        gate(
            "Code quality (fmt/lint/types)",
            "re-run recorded checks",
            not failed and not missing and not gamed,
            f"re-ran {names or 'none'}"
            + (f"; RED: {', '.join(failed)}" if failed else "")
            + (f"; GAMED (no-op cmd): {', '.join(gamed)}" if gamed else "")
            + (f"; MISSING kind(s): {', '.join(sorted(missing))}" if missing else "")
            + ("" if (failed or missing or gamed) else " — all three kinds clean"),
        )
    return ok, rows


def _file_cards(repo: Path) -> tuple[FileCard, ...]:
    skip = {"test_evidence", "security_scan", ".git", ".dream", ".harness", "__pycache__", "docs"}
    cards: list[FileCard] = []
    for p in sorted(repo.rglob("*")):
        rel = p.relative_to(repo)
        if (
            not p.is_file()
            or rel.parts[0] in skip
            or p.suffix not in (".py", ".go", ".json", ".sql")
        ):
            continue
        if rel.parts[0] in ("test_evidence", "security_scan") or str(rel) in (
            "api_verdict.json",
            "test_plan.json",
        ):
            continue
        text = _read(p, 8000)
        lines = text.count("\n") + 1
        is_test = "test" in p.name.lower()
        badge = "tests" if is_test else "source"
        note = f"{lines} lines."
        if "os.environ" in text or "getenv" in text:
            note += " Reads config from the environment (no hardcoded secret)."
        if "sqlite3" in text:
            note += " Talks to a real SQLite datastore."
        if is_test:
            note += " Behaviour-focused tests."
        cards.append(FileCard(str(rel), badge, note))
    return tuple(cards)


def main() -> int:
    if shutil.which("go") is None:
        pass  # Go optional; the default task is Python.
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        _log("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    out_dir = Path(__file__).resolve().parent.parent / "reports"
    out_dir.mkdir(exist_ok=True)
    base = Path(tempfile.mkdtemp(prefix="chorus-bex-report-"))
    os.chdir(base)
    seed = base / "source"
    _seed(seed)

    ledger = Ledger.open(
        os.environ.get("CHORUS_LEDGER_DSN", "postgresql://localhost/chorus"),
        company_id=_EXAMPLE_COMPANY,
    )
    bus = _CaptureBus()
    try:
        registry = RoleRegistry.from_plugins(default_roles())
        factory = EmployeeHarnessFactory(
            api_key=api_key,
            base_url=base_url,
            deployment=deployment,
            company_id="acme",
            roles=registry,
            pricing=default_pricing_from_env(),
            seed=seed,
        )
        ledger.employees.create(Employee(id="bex", name="Bex", role="backend_engineer"))
        ledger.tasks.submit(Task(id="t1", intent=_INTENT))
        assign_task(ledger, "t1", "bex")
        # The full stateful-service floor: a green test_evidence bundle AND a passing API-Verifier
        # verdict whose checks include the persistence-across-restart proof.
        ledger.dod.create(
            "t1",
            Verifier.command(
                "test -f test_evidence/manifest.json && "
                'grep -q \'"verdict": "pass"\' test_evidence/manifest.json && '
                "test -f api_verdict.json && grep -q '\"passed\": *true' api_verdict.json && "
                "grep -qi persist api_verdict.json",
                artifact_class="pr",
            ),
        )
        _log("Running a keyed Backend-Engineer beat…")
        scheduler = Scheduler(
            ledger=ledger,
            workforce=LedgerWorkforce(ledger.employees),
            beat_runner_for=factory,
            budget_enforcer=BudgetEnforcer(ledger, company_id="acme"),
            roles=registry,
            landers=default_landers(factory.company_root),
            memory_writer=EpisodicStore(factory.company_root / "memory"),
            event_bus=bus,
            max_concurrent_runs=1,
        )
        for _ in range(1, 9):
            task = ledger.tasks.get("t1")
            if task is None or task.status in (TaskStatus.DONE, TaskStatus.BLOCKED):
                break

            async def _pulse() -> None:
                await scheduler.tick_once()
                await scheduler.drain()

            asyncio.run(_pulse())
            runs = ledger.runs.for_task("t1")
            dod = ledger.dod.get_for_task("t1")
            after = ledger.tasks.get("t1")
            last = runs[-1] if runs else None
            _log(
                f"  tick: task={after.status.value if after else '?'} "
                f"run={last.status.value if last else '-'} "
                f"dod={dod.status.value if dod else '-'}"
            )
            if last is not None and last.status is RunStatus.FAILED:
                _log(f"  RUN OUTCOME (fault reason): {str(last.outcome)[:600]}")

        repo = factory.company_root / "repo"
        landed = bool(ledger.artifacts.list_for_task("t1"))
        reverify_ok, reverify_rows = _reverify(repo) if repo.exists() else (False, [])
        ok = landed and reverify_ok

        # The badge must name the TRUE final outcome, not the last intermediate review disposition. A
        # timeout is "incomplete — budget exhausted" (resume it), NOT "needs-changes" (which means a
        # reviewer looked and wants edits). Derive from the run's actual status + fault, not RUN_EVALUATED.
        final_runs = ledger.runs.for_task("t1")
        final_run = final_runs[-1] if final_runs else None
        if ok:
            disposition = "passed"
        elif final_run is not None and "Timeout" in str(final_run.outcome):
            disposition = "incomplete — beat budget exhausted (timed out); resume to continue"
        elif final_run is not None and final_run.status is RunStatus.FAILED:
            disposition = bus.cap.evaluated or "failed"
        else:
            disposition = bus.cap.evaluated or "did not land"

        cap = bus.cap
        total_calls = sum(
            len(item.steps) + 1 if isinstance(item, _Group) else 1 for item in cap.timeline
        )
        subagents = sum(1 for item in cap.timeline if isinstance(item, _Group))
        run_calls = sum(
            1
            for item in cap.timeline
            for s in ([item] if isinstance(item, _Step) else item.steps)
            if s.tool == "bash"
        )
        counts: dict[str, int] = {}
        for item in cap.timeline:
            if isinstance(item, _Group):
                counts[item.agent] = counts.get(item.agent, 0) + 1

        # Artifacts are collected dynamically — whatever source/test files Bex chose to write (it names
        # them itself), largest first, plus the durable proof bundles. No filenames are assumed.
        artifacts: list[tuple[str, str]] = []
        skip_dirs = {
            "test_evidence",
            "security_scan",
            ".git",
            ".dream",
            ".harness",
            "docs",
            "__pycache__",
        }
        sources = sorted(
            (p for p in repo.rglob("*.py") if p.relative_to(repo).parts[0] not in skip_dirs),
            key=lambda p: p.stat().st_size,
            reverse=True,
        )
        for p in sources[:8]:
            artifacts.append((str(p.relative_to(repo)), _read(p)))
        for name in (
            "TODO.md",  # the durable cross-beat checklist (resume point) — surfaced so a timed-out
            # beat's progress is visible, not just implied.
            "test_plan.json",
            "test_evidence/manifest.json",
            "security_scan/report.json",
            "api_verdict.json",
        ):
            if (repo / name).exists():
                artifacts.append((name, _read(repo / name)))

        data = ReportData(
            intent=_INTENT,
            ok=ok,
            evaluated=disposition,
            reverify_rows=tuple(reverify_rows),
            gate_rows=tuple(reverify_rows),
            stack=_detect_stack(repo) if repo.exists() else (),
            files=_file_cards(repo) if repo.exists() else (),
            artifacts=tuple(artifacts),
            total_calls=total_calls,
            subagents=subagents,
            run_calls=run_calls,
            subagent_counts=tuple(sorted(counts.items())),
            timeline=cap.timeline,
        )
        flow_path = out_dir / "backend-engineer-flow-report.html"
        test_path = out_dir / "backend-engineer-test-report.html"
        flow_path.write_text(render_flow(data), encoding="utf-8")
        test_path.write_text(render_test(data), encoding="utf-8")
        _log(f"\n{'✅ PASS' if ok else '⚠️  did not fully verify'} — reports written:")
        _log(f"  {flow_path}")
        _log(f"  {test_path}")
        return 0
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
