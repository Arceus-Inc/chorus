"""Export one chorus run's observability into a self-contained bundle for manual walk-through.

Reads a finished run's ``company.db`` (the single source of truth) and emits, for a goal:
  - ``<goal>.html``  — a standalone page: a Mermaid decomposition+dependency GRAPH (status-coloured),
                       the full EVENT TIMELINE (every activity + each beat's verdict), and a task table.
  - ``events.json``  — the raw ledger dump (tasks, runs, dod verdicts, activities, deps, cost).
Plus the caller copies the deliverable repo + run.log alongside and zips it.
"""

from __future__ import annotations

import html
import json
import sqlite3
import sys
from pathlib import Path

_STATUS_COLOR = {
    "done": "#1a7f37", "blocked": "#cf222e", "rejected": "#bc4c00", "cancelled": "#6e7781",
    "in_progress": "#0969da", "todo": "#9a6700", "backlog": "#57606a",
}


def _rows(con: sqlite3.Connection, sql: str) -> list[dict]:
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute(sql)]


def _short(s: object, n: int = 90) -> str:
    t = str(s or "").replace("\n", " ").strip()
    return t[:n] + ("…" if len(t) > n else "")


def export(db_path: Path, out_dir: Path, goal_name: str) -> None:
    con = sqlite3.connect(str(db_path))
    emps = {e["id"]: e for e in _rows(con, "select id,name,role,reports_to from employee")}
    tasks = _rows(con, "select * from task order by depth, created_at")
    deps = _rows(con, "select task_id, depends_on_id from task_dependency")
    runs = _rows(con, "select task_id,status,outcome,started_at,finished_at from run order by created_at")
    dods = {d["task_id"]: d for d in _rows(con, "select task_id,kind,status,verdict from dod")}
    acts = _rows(con, "select verb,actor_employee_id,subject_id,payload,occurred_at from activity order by id")
    costs = _rows(con, "select task_id,sum(input_tokens) i,sum(output_tokens) o,sum(cost_cents) c from cost_event group by task_id")

    # ---- raw dump -------------------------------------------------------------
    (out_dir / "events.json").write_text(
        json.dumps(
            {"goal": goal_name, "employees": list(emps.values()), "tasks": tasks,
             "dependencies": deps, "runs": runs, "dods": list(dods.values()),
             "activities": acts, "cost_by_task": costs},
            indent=2, default=str,
        ),
        encoding="utf-8",
    )

    beats_by_task: dict[str, int] = {}
    for r in runs:
        beats_by_task[r["task_id"]] = beats_by_task.get(r["task_id"], 0) + 1
    label_of = {t["id"]: (t["origin_fingerprint"] or t["id"][:10]) for t in tasks}

    # ---- mermaid graph --------------------------------------------------------
    g = ["graph TD"]
    for t in tasks:
        tid, st = t["id"], t["status"]
        who = emps.get(t["assignee_employee_id"] or "", {})
        sub = f"{st} · {who.get('id','?')}({who.get('role','?')[:3]})"
        node = f'{tid}["<b>{html.escape(label_of[tid])}</b><br/>{html.escape(sub)}<br/>{beats_by_task.get(tid,0)} beats"]'
        g.append(f"    {node}")
        g.append(f"    class {tid} s_{st}")
    for t in tasks:
        if t["parent_id"]:
            g.append(f"    {t['parent_id']} --> {t['id']}")
    for d in deps:
        g.append(f"    {d['depends_on_id']} -.->|needs| {d['task_id']}")
    for st, col in _STATUS_COLOR.items():
        g.append(f"    classDef s_{st} fill:{col}22,stroke:{col},stroke-width:2px,color:#111;")
    mermaid = "\n".join(g)

    # ---- event timeline -------------------------------------------------------
    tl: list[str] = []
    for a in acts:
        payload = ""
        try:
            p = json.loads(a["payload"]) if a["payload"] else {}
            payload = _short(", ".join(f"{k}={v}" for k, v in p.items()), 140)
        except Exception:
            payload = _short(a["payload"], 140)
        tl.append(
            f'<tr><td class="t">{html.escape(str(a["occurred_at"]))}</td>'
            f'<td class="v">{html.escape(a["verb"])}</td>'
            f'<td>{html.escape(a["actor_employee_id"] or "—")}</td>'
            f'<td>{html.escape(label_of.get(a["subject_id"], a["subject_id"] or ""))}</td>'
            f'<td class="p">{html.escape(payload)}</td></tr>'
        )

    # ---- task table (with verdict) -------------------------------------------
    rowsx: list[str] = []
    for t in tasks:
        d = dods.get(t["id"], {})
        verdict = ""
        if d.get("verdict"):
            try:
                vj = json.loads(d["verdict"])
                verdict = _short(vj.get("notes") or vj.get("summary") or json.dumps(vj), 120)
            except Exception:
                verdict = _short(d["verdict"], 120)
        cost = next((c for c in costs if c["task_id"] == t["id"]), {})
        col = _STATUS_COLOR.get(t["status"], "#57606a")
        rowsx.append(
            f'<tr><td>{html.escape(label_of[t["id"]])}</td>'
            f'<td style="color:{col};font-weight:600">{html.escape(t["status"])}</td>'
            f'<td>{html.escape(t["assignee_employee_id"] or "—")}</td>'
            f'<td>{beats_by_task.get(t["id"],0)}</td>'
            f'<td>{(d.get("status") or "—")}</td>'
            f'<td class="p">{html.escape(verdict)}</td>'
            f'<td>{html.escape(_short(t["intent"],80))}</td></tr>'
        )

    html_doc = _TEMPLATE.format(
        goal=html.escape(goal_name),
        mermaid=mermaid,
        timeline="\n".join(tl),
        tasktable="\n".join(rowsx),
        n_tasks=len(tasks),
        n_acts=len(acts),
        n_emps=len(emps),
    )
    (out_dir / f"{goal_name}.html").write_text(html_doc, encoding="utf-8")
    con.close()


_TEMPLATE = """<!doctype html><html><head><meta charset="utf-8"><title>{goal} — run walkthrough</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<script>mermaid.initialize({{startOnLoad:true, theme:'neutral', maxTextSize:200000, flowchart:{{useMaxWidth:false}}}});</script>
<style>
 body{{font:14px -apple-system,system-ui,sans-serif;margin:24px;color:#1f2328;background:#fff}}
 h1{{margin:0 0 4px}} .sub{{color:#57606a;margin-bottom:18px}}
 h2{{border-bottom:2px solid #d0d7de;padding-bottom:6px;margin-top:32px}}
 .mermaid{{background:#f6f8fa;border:1px solid #d0d7de;border-radius:8px;padding:16px;overflow:auto}}
 table{{border-collapse:collapse;width:100%;font-size:13px}}
 th,td{{border:1px solid #d0d7de;padding:5px 8px;text-align:left;vertical-align:top}}
 th{{background:#f6f8fa;position:sticky;top:0}} td.t{{white-space:nowrap;color:#57606a}}
 td.v{{font-weight:600}} td.p{{color:#57606a;max-width:560px}}
 .wrap{{max-height:560px;overflow:auto;border:1px solid #d0d7de;border-radius:8px}}
</style></head><body>
<h1>{goal} — run walkthrough</h1>
<div class="sub">{n_tasks} tasks · {n_emps} employees · {n_acts} observability events. Open the graph below; hover/scroll. Full raw trail in <code>events.json</code>; deliverable in <code>repo/</code>; raw beats in <code>run.log</code>.</div>
<h2>Decomposition + dependency graph</h2>
<div class="mermaid">{mermaid}</div>
<h2>Task table (status · beats · DoD verdict)</h2>
<table><tr><th>module</th><th>status</th><th>owner</th><th>beats</th><th>dod</th><th>verdict</th><th>intent</th></tr>
{tasktable}</table>
<h2>Event timeline ({n_acts} events)</h2>
<div class="wrap"><table><tr><th>when</th><th>verb</th><th>actor</th><th>subject</th><th>payload</th></tr>
{timeline}</table></div>
</body></html>"""


if __name__ == "__main__":
    export(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
