"""HTML report for Backend Engineer cross-beat probe sessions.

Combines probe JSON + log artifacts into a single report covering episodic storage,
recall usage, TODO.md reads, and how the agent acted after each recall.

    uv run python examples/backend_engineer_cross_beat_report.py

Reads (by default):
  reports/backend-engineer-cross-beat-probe.json          — latest probe (mega)
  reports/backend-engineer-cross-beat-probe-run.log       — domain session log
  reports/backend-engineer-cross-beat-probe-mega.log      — mega session log (optional)

Writes:
  reports/backend-engineer-cross-beat-report.html
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_REPORTS = _REPO / "reports"
_OUT = _REPORTS / "backend-engineer-cross-beat-report.html"

_TOOL_COLOR: dict[str, str] = {
    "recall": "#7c3aed",
    "todo_write": "#0891b2",
    "read_file": "#6b7280",
    "write_file": "#16a34a",
    "git": "#d97706",
    "bash": "#0d9488",
    "run_command": "#0d9488",
    "spawn_subagent": "#db2777",
    "test_evidence": "#2563eb",
}


@dataclass
class EpisodicRecord:
    run_id: str
    outcome: str
    files: list[str]


@dataclass
class RecallCall:
    mode: str
    query: str | None
    is_error: bool
    preview: str
    hit: bool


@dataclass
class BeatTrace:
    task_id: str
    tick: int
    task_status: str
    tools: list[tuple[str, str]]
    recall_calls: list[RecallCall]
    todo_preview: str = ""
    todo_md: str = ""
    tool_order_head: str = ""


@dataclass
class Session:
    name: str
    label: str
    beat_timeout_s: float
    completed_tasks: int
    total_tasks: int
    beats: int
    recall_calls: int
    query_recalls: int
    todo_reads: int
    todo_writes: int
    episodic_records: list[EpisodicRecord] = field(default_factory=list)
    traces: list[BeatTrace] = field(default_factory=list)
    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    narrative: str = ""


def _esc(text: object) -> str:
    return html.escape(str(text))


def _tool_dot(tool: str) -> str:
    color = _TOOL_COLOR.get(tool, "#9ca3af")
    return f'<span class="dot" style="background:{color}"></span>'


def _tools_html(tools: list[tuple[str, str]], *, highlight_after_recall: bool = False) -> str:
    rows: list[str] = []
    past_recall = False
    for tool, detail in tools:
        cls = "step"
        if highlight_after_recall and past_recall:
            cls += " after-recall"
        if tool == "recall":
            past_recall = True
        arg = f' <span class="arg">{_esc(detail)}</span>' if detail else ""
        rows.append(
            f'<div class="{cls}">{_tool_dot(tool)}<span class="tool">{_esc(tool)}</span>{arg}</div>'
        )
    return "\n".join(rows) if rows else '<div class="empty">(no tools captured)</div>'


def _recall_calls_html(calls: list[RecallCall]) -> str:
    if not calls:
        return '<div class="empty">No recall this beat.</div>'
    parts: list[str] = []
    for c in calls:
        badge = "hit" if c.hit else ("err" if c.is_error else "empty")
        parts.append(
            f'<div class="recall-box {badge}">'
            f'<div class="recall-head"><b>recall({_esc(c.mode)})</b> '
            f'<span class="badge {badge}">{badge}</span></div>'
            f'<pre class="recall-body">{_esc(c.preview)}</pre></div>'
        )
    return "\n".join(parts)


def _parse_recall_from_log_line(line: str) -> RecallCall | None:
    m = re.search(r"recall\((recency|query=([^)]+))\) → (\w+)", line)
    if not m:
        return None
    mode_raw = m.group(1)
    if mode_raw == "recency":
        return RecallCall("recency", None, m.group(3) == "ERR", "", m.group(3) == "hit")
    return RecallCall(
        f"query={m.group(2)}", m.group(2), m.group(3) == "ERR", "", m.group(3) == "hit"
    )


def _parse_probe_log(path: Path, *, name: str, label: str) -> Session | None:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    timeout_m = re.search(r"beat_timeout\s*:\s*([\d.]+)s", text)
    beat_timeout = float(timeout_m.group(1)) if timeout_m else 0.0

    session = Session(
        name=name,
        label=label,
        beat_timeout_s=beat_timeout,
        completed_tasks=0,
        total_tasks=0,
        beats=0,
        recall_calls=0,
        query_recalls=0,
        todo_reads=0,
        todo_writes=0,
    )

    current_task = ""
    current_trace: BeatTrace | None = None
    in_episodic = False

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("TASK "):
            current_task = line.removeprefix("TASK ").strip()
            session.total_tasks += 1
            continue
        if "→ final status: done" in line:
            session.completed_tasks += 1
            continue
        if line.startswith("PROBE tick="):
            m = re.search(
                r"tick=(\d+).*status=(\w+).*tools=(\d+).*todo_r=(\d+).*todo_w=(\d+).*recall=(\d+)",
                line,
            )
            if not m:
                continue
            current_trace = BeatTrace(
                task_id=current_task,
                tick=int(m.group(1)),
                task_status=m.group(2),
                tools=[],
                recall_calls=[],
            )
            session.beats += 1
            session.todo_reads += int(m.group(4))
            session.todo_writes += int(m.group(5))
            session.recall_calls += int(m.group(6))
            session.traces.append(current_trace)
            continue
        if current_trace and line.startswith("TODO.md:"):
            current_trace.todo_preview = line.removeprefix("TODO.md:").strip()
            continue
        if current_trace and line.startswith("tool order"):
            current_trace.tool_order_head = line.removeprefix("tool order (first 6):").strip()
            continue
        if current_trace and line.startswith("recall("):
            rc = _parse_recall_from_log_line(line)
            if rc:
                current_trace.recall_calls.append(rc)
                if rc.query:
                    session.query_recalls += 1
            continue
        if line == "EPISODIC STORE":
            in_episodic = True
            continue
        if in_episodic and line.startswith("run_"):
            em = re.match(r"run_([a-f0-9]+)… outcome=(\w+) files=(\[.*\])", line.replace("'", '"'))
            if em:
                try:
                    files = json.loads(em.group(3))
                except json.JSONDecodeError:
                    files = []
                session.episodic_records.append(
                    EpisodicRecord(f"run_{em.group(1)}", em.group(2), list(files))
                )
            continue
        if in_episodic and line.startswith("HARNESS CHECKS"):
            in_episodic = False
            continue
        if line.startswith("[PASS]") or line.startswith("[FAIL]"):
            ok = line.startswith("[PASS]")
            rest = line[6:].strip()
            if " — " in rest:
                name_part, detail = rest.split(" — ", 1)
            else:
                name_part, detail = rest, ""
            session.checks.append((name_part, ok, detail))

    return session


def _recall_from_json(raw: dict[str, object]) -> RecallCall:
    inp = raw.get("input", {})
    inp_dict = inp if isinstance(inp, dict) else {}
    query = inp_dict.get("query")
    preview = str(raw.get("preview", ""))
    is_error = bool(raw.get("is_error"))
    if query:
        mode = f"query={query!r}"
        q: str | None = str(query)
    else:
        mode = "recency"
        q = None
    hit = bool(preview) and "no past beats" not in preview
    return RecallCall(mode, q, is_error, preview, hit)


def _session_from_json(path: Path, *, name: str, label: str) -> Session | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    traces: list[BeatTrace] = []
    recall_total = 0
    query_total = 0
    todo_reads = 0
    todo_writes = 0

    for t in data.get("traces", []):
        if not isinstance(t, dict):
            continue
        tools_raw = t.get("tools", [])
        tools: list[tuple[str, str]] = []
        if isinstance(tools_raw, list):
            for step in tools_raw:
                if isinstance(step, dict):
                    tools.append((str(step.get("tool", "?")), str(step.get("detail", ""))))
        recalls = [_recall_from_json(c) for c in t.get("recall_calls", []) if isinstance(c, dict)]
        recall_total += len(recalls)
        query_total += sum(1 for c in recalls if c.query)
        todo_reads += sum(1 for tool, det in tools if tool == "read_file" and "TODO.md" in det)
        todo_writes += sum(1 for tool, _ in tools if tool == "todo_write")
        head = " → ".join(tool for tool, _ in tools[:6])
        traces.append(
            BeatTrace(
                task_id=str(t.get("task_id", "?")),
                tick=int(t.get("tick", 0)),
                task_status=str(t.get("task_status", "?")),
                tools=tools,
                recall_calls=recalls,
                todo_preview=str(t.get("todo_md_preview", ""))[:500],
                todo_md=str(t.get("todo_md_preview", "")),
                tool_order_head=head,
            )
        )

    records: list[EpisodicRecord] = []
    for r in data.get("stored_records", []):
        if isinstance(r, dict):
            records.append(
                EpisodicRecord(
                    str(r.get("run_id", "")),
                    str(r.get("outcome", "?")),
                    list(r.get("files_touched", [])),
                )
            )
    # Fallback: parse episodic lines from companion log if present
    if not records:
        log_guess = path.with_name(path.stem.replace(".json", "") + "-mega.log")
        if not log_guess.is_file():
            log_guess = _REPORTS / "backend-engineer-cross-beat-probe-mega.log"
        parsed = (
            _parse_probe_log(log_guess, name=name, label=label) if log_guess.is_file() else None
        )
        if parsed:
            records = parsed.episodic_records

    checks = [
        (str(c.get("name", "")), bool(c.get("ok")), str(c.get("detail", "")))
        for c in data.get("checks", [])
        if isinstance(c, dict)
    ]

    return Session(
        name=name,
        label=label,
        beat_timeout_s=float(data.get("beat_timeout_s", 0)),
        completed_tasks=int(data.get("completed_tasks", 0)),
        total_tasks=int(data.get("total_tasks", 0)),
        beats=len(traces),
        recall_calls=recall_total,
        query_recalls=query_total,
        todo_reads=todo_reads,
        todo_writes=todo_writes,
        episodic_records=records,
        traces=traces,
        checks=checks,
    )


def _tools_after_recall(trace: BeatTrace) -> list[tuple[str, str]]:
    if not trace.recall_calls:
        return []
    for i, (tool, detail) in enumerate(trace.tools):
        if tool == "recall":
            return trace.tools[i + 1 : i + 8]
    return []


def _session_narrative(session: Session) -> str:
    if session.name == "domain":
        return (
            "<p>Four sequential domain tasks (auth → orders → payments → durability) at "
            f"<b>{session.beat_timeout_s:.0f}s</b> per beat. <b>TODO.md</b> was read on "
            f"<b>{session.todo_reads}</b> beats and updated via <code>todo_write</code> on "
            f"<b>{session.todo_writes}</b> beats — enough to resume t1-auth across tick 2 "
            "without restarting. <b>recall was never called</b> — each slice finished in one "
            "beat (except auth), so episodic memory had no gap to fill; TODO.md + git state "
            "carried continuity.</p>"
        )
    return (
        "<p>One mega commerce-API task at <b>90s</b> per beat, spanning <b>6 ticks</b>. "
        f"<b>recall()</b> (recency) fired <b>{session.recall_calls}</b> times; "
        f"<code>recall(query=…)</code> <b>{session.query_recalls}</b> times. "
        f"Ticks 3–5 open with <code>recall → …</code> and return prior <code>blocked</code> "
        "beats with file lists matching the worktree. <b>TODO.md</b> persisted across all "
        "ticks with progressive checkoffs; only tick 2 explicitly read it (tick 1 created it). "
        "After recall hits, the agent reads source files named in the episodic record "
        "(e.g. <code>commerce_api/app.py</code>) — not retrieve-and-stop.</p>"
    )


def _beat_card(trace: BeatTrace, beat_num: int) -> str:
    todo_reads = sum(1 for t, d in trace.tools if t == "read_file" and "TODO.md" in d)
    todo_writes = sum(1 for t, _ in trace.tools if t == "todo_write")
    after = _tools_after_recall(trace)
    after_html = ""
    if after:
        after_html = "<h4>After recall — next tools</h4>" + _tools_html(
            after, highlight_after_recall=True
        )
    return f"""
    <article class="beat">
      <header class="beat-head">
        <span class="bnum">{beat_num}</span>
        <div>
          <h3>{_esc(trace.task_id)} · tick {trace.tick}</h3>
          <p class="meta">status <b>{_esc(trace.task_status)}</b> ·
            {len(trace.tools)} tools ·
            TODO read <b>{todo_reads}</b> · todo_write <b>{todo_writes}</b> ·
            recall <b>{len(trace.recall_calls)}</b>
          </p>
        </div>
      </header>
      <div class="beat-grid">
        <section>
          <h4>TODO.md at beat end</h4>
          <pre class="todo">{_esc(trace.todo_md or trace.todo_preview or "(not captured)")}</pre>
        </section>
        <section>
          <h4>Recall returned</h4>
          {_recall_calls_html(trace.recall_calls)}
        </section>
      </div>
      {after_html}
      <details class="tools-fold">
        <summary>Full tool trace ({len(trace.tools)} steps)</summary>
        <div class="tool-trace">{_tools_html(trace.tools, highlight_after_recall=bool(trace.recall_calls))}</div>
      </details>
    </article>"""


def _episodic_table(records: list[EpisodicRecord]) -> str:
    if not records:
        return '<p class="empty">No episodic records captured for this session.</p>'
    rows = []
    for r in records:
        files = ", ".join(_esc(f) for f in r.files[:6])
        if len(r.files) > 6:
            files += f" … +{len(r.files) - 6}"
        rows.append(
            f"<tr><td><code>{_esc(r.run_id[:16])}…</code></td>"
            f'<td><span class="outcome {_esc(r.outcome)}">{_esc(r.outcome)}</span></td>'
            f"<td>{files}</td></tr>"
        )
    return (
        '<table class="store"><thead><tr><th>run_id</th><th>outcome</th>'
        f"<th>files_touched</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def _checks_html(checks: list[tuple[str, bool, str]]) -> str:
    if not checks:
        return ""
    items = "".join(
        f'<li class="{"ok" if ok else "fail"}"><span class="mark">{"✓" if ok else "✗"}</span>'
        f'{_esc(name)} <span class="detail">— {_esc(detail)}</span></li>'
        for name, ok, detail in checks
    )
    return f"<ul class='checks'>{items}</ul>"


def _session_section(session: Session) -> str:
    session.narrative = _session_narrative(session)
    beats_html = "".join(_beat_card(t, i + 1) for i, t in enumerate(session.traces))
    chips = [
        ("Beats", str(session.beats)),
        ("Tasks done", f"{session.completed_tasks}/{session.total_tasks}"),
        ("Episodic records", str(len(session.episodic_records))),
        ("recall() calls", str(session.recall_calls)),
        ("recall(query=)", str(session.query_recalls)),
        ("TODO reads", str(session.todo_reads)),
        ("todo_write", str(session.todo_writes)),
    ]
    chip_html = "".join(f'<div class="chip"><span>{v}</span>{k}</div>' for k, v in chips)
    return f"""
    <section class="session" id="{_esc(session.name)}">
      <header class="session-head">
        <p class="eyebrow">Session</p>
        <h2>{_esc(session.label)}</h2>
        <p class="sub">Beat budget {_esc(session.beat_timeout_s)}s · {_esc(session.name)} probe</p>
      </header>
      <div class="chips">{chip_html}</div>
      <div class="narrative">{session.narrative}</div>
      <h3 class="sec">What got stored (episodic)</h3>
      <p class="hint">Written at beat-end by the scheduler — one row per completed run.</p>
      {_episodic_table(session.episodic_records)}
      <h3 class="sec">Beat-by-beat: stored → recalled → used</h3>
      {beats_html}
      <h3 class="sec">Harness checks</h3>
      {_checks_html(session.checks)}
    </section>"""


def build_html(sessions: list[Session]) -> str:
    total_recall = sum(s.recall_calls for s in sessions)
    total_query = sum(s.query_recalls for s in sessions)
    total_todo_r = sum(s.todo_reads for s in sessions)
    mega = next((s for s in sessions if s.name == "mega"), None)
    domain = next((s for s in sessions if s.name == "domain"), None)

    comparison = f"""
    <div class="compare">
      <h3>Cross-session comparison</h3>
      <table class="cmp">
        <thead><tr><th></th><th>Domain (4 tasks)</th><th>Mega (1 task)</th></tr></thead>
        <tbody>
          <tr><td>Beat budget</td>
              <td>{domain.beat_timeout_s if domain else "—":.0f}s</td>
              <td>{mega.beat_timeout_s if mega else "—":.0f}s</td></tr>
          <tr><td>recall() used</td>
              <td>{domain.recall_calls if domain else 0}</td>
              <td>{mega.recall_calls if mega else 0}</td></tr>
          <tr><td>recall(query=)</td>
              <td>{domain.query_recalls if domain else 0}</td>
              <td>{mega.query_recalls if mega else 0}</td></tr>
          <tr><td>TODO.md reads</td>
              <td>{domain.todo_reads if domain else 0}</td>
              <td>{mega.todo_reads if mega else 0}</td></tr>
          <tr><td>Primary resume aid</td>
              <td><b>TODO.md</b> + git</td>
              <td><b>recall()</b> + TODO.md</td></tr>
        </tbody>
      </table>
      <div class="note">
        <b>recall(query=…)</b> is implemented and unit-tested but was <b>not used</b> in either live
        session ({total_query} query calls). Both runs were greenfield build work, not regression
        tickets — the brief only nudges search recall for edge-case / failure-shape problems.
      </div>
    </div>"""

    body = "".join(_session_section(s) for s in sessions)
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Backend Engineer — Cross-Beat Memory Report</title>
<style>
  :root {{
    --bg:#f6f8fa; --card:#fff; --ink:#1f2328; --muted:#57606a; --line:#d0d7de;
    --accent:#4f46e5; --accent-soft:#eef2ff; --recall:#7c3aed; --todo:#0891b2;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
  .wrap {{ max-width:1040px; margin:0 auto; padding:28px 20px 72px; }}
  header.top {{ background:linear-gradient(135deg,#eef2ff,#f0fdf4); border:1px solid var(--line);
    border-radius:16px; padding:26px 28px; margin-bottom:24px; }}
  header.top .eyebrow {{ color:var(--accent); font-weight:700; font-size:12px;
    text-transform:uppercase; letter-spacing:.06em; }}
  header.top h1 {{ margin:.15em 0; font-size:26px; }}
  header.top p {{ margin:0; color:var(--muted); }}
  .chips {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr));
    gap:10px; margin:18px 0; }}
  .chip {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
    padding:12px 14px; font-size:12px; color:var(--muted); }}
  .chip span {{ display:block; font-size:22px; font-weight:700; color:var(--ink); }}
  h3.sec {{ font-size:14px; text-transform:uppercase; letter-spacing:.04em;
    color:var(--muted); margin:28px 0 10px; }}
  .hint {{ color:var(--muted); font-size:13px; margin:-4px 0 12px; }}
  .session {{ margin-bottom:48px; }}
  .session-head h2 {{ margin:4px 0; font-size:22px; }}
  .session-head .sub {{ color:var(--muted); margin:0; }}
  .narrative {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
    padding:16px 18px; margin:16px 0; font-size:14px; }}
  .narrative code {{ background:#f3f4f6; padding:1px 5px; border-radius:4px; font-size:13px; }}
  table.store, table.cmp {{ width:100%; border-collapse:collapse; background:var(--card);
    border:1px solid var(--line); border-radius:12px; overflow:hidden; font-size:13.5px; }}
  table.store th, table.store td, table.cmp th, table.cmp td {{
    padding:10px 14px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
  table.store th, table.cmp th {{ background:#fbfcfe; color:var(--muted); font-size:12px;
    text-transform:uppercase; }}
  .outcome.done {{ color:#166534; font-weight:600; }}
  .outcome.blocked {{ color:#b45309; font-weight:600; }}
  .beat {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
    margin-bottom:16px; overflow:hidden; }}
  .beat-head {{ display:flex; gap:14px; padding:16px 18px; border-bottom:1px solid var(--line);
    background:#fbfcfe; }}
  .bnum {{ width:32px; height:32px; border-radius:50%; background:var(--accent); color:#fff;
    display:grid; place-items:center; font-weight:700; flex-shrink:0; }}
  .beat-head h3 {{ margin:0 0 4px; font-size:16px; }}
  .meta {{ margin:0; color:var(--muted); font-size:13px; }}
  .beat-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:0; }}
  @media(max-width:720px){{ .beat-grid {{ grid-template-columns:1fr; }} }}
  .beat-grid section {{ padding:14px 16px; border-bottom:1px solid var(--line); }}
  .beat-grid section:first-child {{ border-right:1px solid var(--line); }}
  @media(max-width:720px){{ .beat-grid section:first-child {{ border-right:none; }} }}
  .beat-grid h4 {{ margin:0 0 8px; font-size:12px; text-transform:uppercase;
    color:var(--muted); letter-spacing:.03em; }}
  pre.todo {{ margin:0; white-space:pre-wrap; font:12.5px/1.45 ui-monospace,Menlo,monospace;
    background:#f6f8fa; padding:10px; border-radius:8px; max-height:140px; overflow:auto; }}
  .recall-box {{ border:1px solid #e9d5ff; border-radius:8px; background:#faf5ff; margin-bottom:8px; }}
  .recall-box.hit {{ border-color:#c4b5fd; }}
  .recall-box.empty {{ border-color:#e5e7eb; background:#f9fafb; }}
  .recall-head {{ padding:8px 10px; font-size:13px; border-bottom:1px dashed #e9d5ff; }}
  .badge {{ font-size:11px; font-weight:700; padding:2px 8px; border-radius:999px; }}
  .badge.hit {{ background:#ede9fe; color:#5b21b6; }}
  .badge.empty {{ background:#f3f4f6; color:#6b7280; }}
  pre.recall-body {{ margin:0; padding:8px 10px; font:11.5px/1.4 ui-monospace,Menlo,monospace;
    white-space:pre-wrap; max-height:120px; overflow:auto; }}
  .tools-fold summary {{ cursor:pointer; padding:12px 16px; font-size:13px; font-weight:600; }}
  .tool-trace {{ padding:4px 12px 14px; }}
  .step {{ display:flex; align-items:center; gap:8px; padding:4px 6px; font-size:13px; border-radius:6px; }}
  .step.after-recall {{ background:#f5f3ff; }}
  .step .tool {{ font-weight:600; }}
  .step .arg {{ color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  .dot {{ width:8px; height:8px; border-radius:50%; flex-shrink:0; }}
  .compare {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
    padding:18px 20px; margin-bottom:32px; }}
  .note {{ margin-top:14px; background:#fffbeb; border:1px solid #fde68a; border-radius:10px;
    padding:12px 14px; font-size:13.5px; color:#854d0e; }}
  ul.checks {{ list-style:none; padding:0; margin:0; }}
  ul.checks li {{ padding:8px 12px; border-bottom:1px solid var(--line); font-size:13.5px; }}
  ul.checks li.ok .mark {{ color:#16a34a; }}
  ul.checks li.fail .mark {{ color:#dc2626; }}
  ul.checks .detail {{ color:var(--muted); }}
  .empty {{ color:var(--muted); font-size:13px; padding:8px; }}
  footer {{ text-align:center; color:var(--muted); font-size:12px; margin-top:40px; }}
</style></head>
<body><div class="wrap">
<header class="top">
  <p class="eyebrow">Chorus · Episodic memory probe</p>
  <h1>Backend Engineer — Cross-Beat Memory Report</h1>
  <p>Two continuous-beat sessions: what was <b>stored</b> at beat-end, what was <b>recalled</b> mid-beat,
     how the agent <b>used</b> it, and how <b>TODO.md</b> was read and updated.</p>
  <div class="chips">
    <div class="chip"><span>{len(sessions)}</span>Sessions</div>
    <div class="chip"><span>{total_recall}</span>recall() total</div>
    <div class="chip"><span>{total_query}</span>recall(query=)</div>
    <div class="chip"><span>{total_todo_r}</span>TODO reads</div>
  </div>
</header>
{comparison}
{body}
<footer>Generated by examples/backend_engineer_cross_beat_report.py</footer>
</div></body></html>"""


def _enrich_todo_from_log(session: Session, log_path: Path) -> None:
    """Fill TODO previews from companion log when JSON omits them."""
    if not log_path.is_file():
        return
    previews: list[str] = []
    for raw in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("TODO.md:"):
            previews.append(line.removeprefix("TODO.md:").strip())
    for trace, preview in zip(session.traces, previews, strict=False):
        if not trace.todo_preview:
            trace.todo_preview = preview.replace(" | ", "\n")
            trace.todo_md = trace.todo_preview


def main() -> int:
    sessions: list[Session] = []

    domain_log = _REPORTS / "backend-engineer-cross-beat-probe-run.log"
    domain_json = _REPORTS / "backend-engineer-cross-beat-probe-domain.json"
    domain = _session_from_json(domain_json, name="domain", label="Four domain tasks @ 150s")
    if domain is None:
        domain = _parse_probe_log(domain_log, name="domain", label="Four domain tasks @ 150s")

    mega_json = _REPORTS / "backend-engineer-cross-beat-probe-mega.json"
    if not mega_json.is_file():
        mega_json = _REPORTS / "backend-engineer-cross-beat-probe.json"
    mega = _session_from_json(mega_json, name="mega", label="Mega commerce API @ 90s")

    if domain:
        _enrich_todo_from_log(domain, domain_log)
        sessions.append(domain)
    if mega:
        mega_log = _REPORTS / "backend-engineer-cross-beat-probe-mega.log"
        _enrich_todo_from_log(mega, mega_log)
        sessions.append(mega)

    if not sessions:
        print(
            "No probe artifacts found under reports/ — run backend_engineer_cross_beat_probe.py first"
        )
        return 1

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(build_html(sessions), encoding="utf-8")
    print(f"report: {_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
