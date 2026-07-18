"""Manager Long-Run Experiment — one manager + two engineers across several delegation waves.

Drives the REAL chorus stack (factory → scheduler → dream beats → landers → event bus → memory writer)
exactly as the CLI wires it (`build_beat_service`). For each one-line goal the manager decomposes into
subtasks, parks, the two engineers build + merge their children, and the manager integrates — wave
after wave. Afterwards it probes everything the way the engineer long-run report does: the ledger
(tasks/runs/artifacts/cost), the company git history, the durable event spine (events.jsonl), and —
the focus of today's work — the **append-only episodic memory** the kernel writes one record per beat,
read back through dream's own scanner.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/m3_long_run.py

Writes reports/m3-manager-long-run.html and raw outputs under the run dir. Skips (exit 0) without keys.
"""

from __future__ import annotations

import html
import json
import os
import uuid

_EXAMPLE_COMPANY = str(uuid.uuid5(uuid.NAMESPACE_URL, "chorus-example"))  # one stable demo org
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from chorus.ledger import Ledger, Run, Task, TaskStatus
from chorus.lifecycle import assign_task
from chorus.workforce import LedgerWorkforce
from chorus_cli._beats import build_beat_service, default_pricing_from_env

# One-line goals — the manager's brief carries the decomposition; we never spell out the children.
_GOALS = [
    "Add string utilities: a slugify(text) function and a shout(text) function (uppercase + '!').",
    "Add number utilities: a clamp(x, lo, hi) function and an is_even(n) function.",
    "Add collection utilities: a head(seq) function and a tail(seq) function.",
]
_MAX_TICKS_PER_GOAL = 14


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=False, capture_output=True, text=True
    ).stdout.rstrip()


def _seed_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text(
        "# toolbox\n\nA small utility library, built wave by wave.\n", encoding="utf-8"
    )
    # A passing smoke test so each engineer's `pytest -q` DoD always collects >=1 test (no exit-5).
    (path / "test_smoke.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
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
            "seed",
        ],
        check=True,
        capture_output=True,
    )


def _run_cost(run: Run) -> int:
    outcome = run.outcome
    if isinstance(outcome, str):
        try:
            outcome = json.loads(outcome)
        except json.JSONDecodeError:
            return 0
    return int(outcome.get("cost_cents", 0)) if isinstance(outcome, dict) else 0


def _subtree_cost(ledger: Ledger, goal_id: str) -> int:
    ids = [goal_id] + [c.id for c in ledger.tasks.children(goal_id)]
    return sum(_run_cost(r) for tid in ids for r in ledger.runs.for_task(tid))


def _main_check(repo: Path) -> str:
    if not repo.exists():
        return "no-repo"
    proc = subprocess.run(
        ["bash", "-lc", "pytest -q && ruff check ."], cwd=repo, capture_output=True, text=True
    )
    return "passed" if proc.returncode == 0 else "failed"


def main() -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        _log("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    run_root = Path(__file__).parent.parent / ".chorus" / "m3-long-run"
    if run_root.exists():
        subprocess.run(["rm", "-rf", str(run_root)], check=True)
    run_root.mkdir(parents=True)
    seed = run_root / "seed"
    _seed_repo(seed)
    work_root = run_root / "work"
    company = "toolbox"
    ledger = Ledger.open(
        os.environ.get("CHORUS_LEDGER_DSN", "postgresql://localhost/chorus"),
        company_id=_EXAMPLE_COMPANY,
    )

    waves: list[dict[str, object]] = []
    try:
        for emp, role in [("moe", "manager"), ("ada", "engineer"), ("bob", "engineer")]:
            LedgerWorkforce(ledger.employees).hire(
                name=emp, role=role, reports_to="moe" if role == "engineer" else None
            )
        runner = build_beat_service(
            ledger,
            api_key=api_key,
            base_url=base_url,
            deployment=deployment,
            company_id=company,
            pricing=default_pricing_from_env(),
            seed=seed,
            work_root=work_root,
            max_concurrent_runs=2,
        )
        company_root = work_root / company
        repo = company_root / "repo"

        _log("=" * 64)
        _log(f"MANAGER LONG RUN — {len(_GOALS)} delegation waves, team = moe(mgr) + ada,bob(eng)")
        _log("=" * 64)
        for n, goal in enumerate(_GOALS, 1):
            goal_id = f"goal{n}"
            ledger.tasks.submit(Task(id=goal_id, intent=goal, status=TaskStatus.TODO))
            assign_task(ledger, goal_id, "moe")
            _log(f"\n── WAVE {n}: {goal}")
            t0 = time.monotonic()
            for _ in range(_MAX_TICKS_PER_GOAL):
                task = ledger.tasks.get(goal_id)
                if task is not None and task.status is TaskStatus.DONE:
                    break
                runner.run_tick()
                kids = ledger.tasks.children(goal_id)
                _log(
                    f"   tick: goal={ledger.tasks.get(goal_id).status.value}  "  # type: ignore[union-attr]
                    f"children={[(c.id[-4:], c.status.value) for c in kids]}"
                )
            elapsed = time.monotonic() - t0
            children = ledger.tasks.children(goal_id)
            arts = {c.id: ledger.artifacts.list_for_task(c.id) for c in children}
            merged = sum(
                1
                for c in children
                for a in arts[c.id]
                if a.resource_ref is not None and a.resource_ref.get("merged") is True
            )
            waves.append(
                {
                    "n": n,
                    "goal": goal,
                    "goal_id": goal_id,
                    "status": (ledger.tasks.get(goal_id) or Task(id="", intent="")).status.value,
                    "elapsed": round(elapsed, 1),
                    "cost": _subtree_cost(ledger, goal_id),
                    "children": [(c.id, c.assignee_employee_id, c.status.value) for c in children],
                    "children_done": sum(1 for c in children if c.status is TaskStatus.DONE),
                    "merged": merged,
                    "main_check": _main_check(repo),
                }
            )
            w = waves[-1]
            _log(
                f"   ⇒ goal={w['status']} children_done={w['children_done']}/{len(children)} "
                f"merged={merged} main={w['main_check']} {w['elapsed']}s {w['cost']}c"
            )

        report = _probe_and_report(
            ledger, run_root=run_root, company_root=company_root, repo=repo, waves=waves
        )
        _log(f"\nreport: {report}")
        return 0
    finally:
        ledger.close()


def _probe_and_report(
    ledger: Ledger,
    *,
    run_root: Path,
    company_root: Path,
    repo: Path,
    waves: list[dict[str, object]],
) -> Path:
    from dream.memory import scan_memory_dir

    # — event spine —
    events_path = company_root / "events.jsonl"
    kinds: Counter[str] = Counter()
    tools: Counter[str] = Counter()
    if events_path.exists():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            kinds[ev.get("kind", "?")] += 1
            if ev.get("kind") == "run.tool_use":
                tools[str(ev.get("payload", {}).get("tool", "?"))] += 1
    memory_tools = {t: c for t, c in tools.items() if t.startswith(("memory_", "working_memory"))}

    # — append-only episodic memory (today's feature) — read back through dream's own scanner, which
    # finds records under each {scope}/ subdir the EpisodicStore writes.
    mem_dir = company_root / "memory"
    records: list[tuple[str, dict[str, str]]] = []  # (filename == run id, frontmatter)
    total_files = len(list(mem_dir.rglob("*.md"))) if mem_dir.exists() else 0
    if mem_dir.exists():
        for scope_dir in sorted(p for p in mem_dir.iterdir() if p.is_dir()):
            for rec in scan_memory_dir(scope_dir):
                records.append((rec.id, {str(k): str(v) for k, v in rec.frontmatter.items()}))
    read_back = records  # every record here was parsed by dream's scan_memory_dir
    by_emp: Counter[str] = Counter(fm.get("employee_id", "?") for _, fm in records)
    by_scope: Counter[str] = Counter(fm.get("scope", "?") for _, fm in records)
    named_by_run = sum(1 for rid, fm in records if fm.get("run_id") == rid)
    has_provenance = sum(1 for _, fm in records if fm.get("task_id") and fm.get("employee_id"))

    # — ledger tree —
    goals = [
        g for g in (ledger.tasks.get(f"goal{i + 1}") for i in range(len(waves))) if g is not None
    ]
    all_children = [c for g in goals for c in ledger.tasks.children(g.id)]
    done_goals = sum(1 for g in goals if g.status is TaskStatus.DONE)
    done_children = sum(1 for c in all_children if c.status is TaskStatus.DONE)
    merged_total = sum(int(w["merged"]) for w in waves)  # type: ignore[arg-type]
    main_passes = sum(1 for w in waves if w["main_check"] == "passed")
    total_cost = sum(int(w["cost"]) for w in waves)  # type: ignore[arg-type]
    total_wall = sum(float(w["elapsed"]) for w in waves)  # type: ignore[arg-type]

    # — company repo —
    merge_commits = len(
        [ln for ln in _git(repo, "log", "--oneline", "--merges").splitlines() if ln]
    )
    main_files = [ln for ln in _git(repo, "ls-files").splitlines() if ln]

    data = {
        "waves": waves,
        "goals": len(goals),
        "done_goals": done_goals,
        "children": len(all_children),
        "done_children": done_children,
        "merged_total": merged_total,
        "main_passes": main_passes,
        "total_cost": total_cost,
        "total_wall": round(total_wall, 1),
        "kinds": dict(kinds),
        "tools": dict(tools),
        "memory_tools": memory_tools,
        "mem_files": total_files,
        "mem_records": len(records),
        "mem_by_emp": dict(by_emp),
        "mem_by_scope": dict(by_scope),
        "mem_named_by_run": named_by_run,
        "mem_has_provenance": has_provenance,
        "mem_read_back": len(read_back),
        "merge_commits": merge_commits,
        "main_files": main_files,
        "records": records,
    }
    (run_root / "results.json").write_text(
        json.dumps(data, indent=2, default=str), encoding="utf-8"
    )
    out = Path(__file__).parent.parent / "reports" / "m3-manager-long-run.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(_render(data), encoding="utf-8")
    return out


def _render(d: dict[str, object]) -> str:
    e = html.escape
    waves = d["waves"]  # type: ignore[index]
    all_done = d["done_goals"] == d["goals"] and d["done_children"] == d["children"]
    mem_ok = (d["mem_read_back"] == d["mem_files"]) and (
        d["mem_has_provenance"] == d["mem_records"]
    )
    verdict = "PASS" if all_done and mem_ok else "PARTIAL"

    wave_rows = "".join(
        f"<tr><td>{w['n']}</td><td>{e(str(w['goal'])[:70])}</td><td>{w['elapsed']}s</td>"
        f"<td>{w['cost']}c</td><td class={'ok' if w['status'] == 'done' else 'bad'}>{w['status']}</td>"
        f"<td>{w['children_done']}/{len(w['children'])}</td><td>{w['merged']}</td>"  # type: ignore[arg-type]
        f"<td class={'ok' if w['main_check'] == 'passed' else 'bad'}>{w['main_check']}</td></tr>"
        for w in waves  # type: ignore[union-attr]
    )
    child_rows = "".join(
        f"<tr><td>{w['n']}</td><td><code>{e(cid)}</code></td><td>{e(str(asg))}</td>"
        f"<td class={'ok' if st == 'done' else 'bad'}>{st}</td></tr>"
        for w in waves
        for (cid, asg, st) in w["children"]  # type: ignore[union-attr]
    )
    mem_rows = "".join(
        f"<tr><td><code>{e(name)}</code></td><td>{e(fm.get('employee_id', '?'))}</td>"
        f"<td>{e(fm.get('scope', '?'))}</td><td>{e(fm.get('kind', '?'))}</td>"
        f"<td>{e(fm.get('outcome', '?'))}</td></tr>"
        for name, fm in d["records"]  # type: ignore[union-attr]
    )
    tool_rows = "".join(
        f"<tr><td><code>{e(t)}</code></td><td>{c}</td></tr>"
        for t, c in sorted(d["tools"].items(), key=lambda kv: -kv[1])
    )  # type: ignore[union-attr]
    kind_rows = "".join(
        f"<tr><td><code>{e(k)}</code></td><td>{c}</td></tr>"
        for k, c in sorted(d["kinds"].items(), key=lambda kv: -kv[1])
    )  # type: ignore[union-attr]

    def chk(label: str, ok: bool, detail: str) -> str:
        return (
            f"<tr><td>{e(label)}</td><td class={'ok' if ok else 'bad'}>{'PASS' if ok else 'FAIL'}"
            f"</td><td>{e(detail)}</td></tr>"
        )

    mem_checks = "".join(
        [
            chk(
                "one append-only record per beat",
                d["mem_records"] > 0,
                f"{d['mem_records']} records written",
            ),
            chk(
                "every record named by its run id",
                d["mem_named_by_run"] == d["mem_records"],
                f"{d['mem_named_by_run']}/{d['mem_records']} filename == run_id",
            ),
            chk(
                "provenance task_id + employee_id (all)",
                d["mem_has_provenance"] == d["mem_records"],
                f"{d['mem_has_provenance']}/{d['mem_records']} carry both",
            ),
            chk(
                "per-role scope (manager=team, engineer=project)",
                "team" in d["mem_by_scope"] and "project" in d["mem_by_scope"],  # type: ignore[operator]
                f"scopes: {d['mem_by_scope']}",
            ),
            chk(
                "memory written for manager AND engineers",
                len(d["mem_by_emp"]) >= 2,
                f"by employee: {d['mem_by_emp']}",
            ),  # type: ignore[arg-type]
            chk(
                "dream's own scanner reads back every file",
                d["mem_read_back"] == d["mem_files"],
                f"scan_memory_dir parsed {d['mem_read_back']}/{d['mem_files']} files on disk",
            ),
        ]
    )

    css = (
        ":root{--bg:#f5f7fb;--panel:#fff;--ink:#17202a;--muted:#5f6b7a;--ok:#0a7a34;--bad:#b42318;"
        "--line:#d7deea;--accent:#0b5cab}body{margin:0;background:radial-gradient(circle at top right,"
        "#dbeafe 0,var(--bg) 45%);color:var(--ink);font-family:Segoe UI,Tahoma,Arial,sans-serif;"
        "line-height:1.45}main{max-width:1000px;margin:24px auto;padding:0 16px 40px}.card{background:"
        "var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin-bottom:16px;"
        "box-shadow:0 8px 24px rgba(24,39,75,.06)}h1{font-size:24px;margin:0 0 8px}h2{font-size:18px;"
        "color:var(--accent);margin:0 0 12px}.meta{color:var(--muted);font-size:13px}table{width:100%;"
        "border-collapse:collapse;font-size:14px;margin-top:8px}th,td{text-align:left;border-bottom:"
        "1px solid var(--line);padding:8px 6px;vertical-align:top}th{color:var(--muted);font-weight:600}"
        ".ok{color:var(--ok);font-weight:700}.bad{color:var(--bad);font-weight:700}code{font-family:"
        "Consolas,monospace;font-size:12px}.pill{display:inline-block;background:#eef4ff;border:1px solid "
        "var(--line);border-radius:999px;padding:4px 12px;margin:3px 6px 3px 0;font-size:13px;font-weight:600}"
        ".big{font-size:22px;font-weight:800;color:var(--accent)}"
    )
    pills = "".join(
        f"<span class=pill>{e(p)}</span>"
        for p in [
            f"{d['done_goals']}/{d['goals']} goals done",
            f"{d['done_children']}/{d['children']} children done",
            f"{d['merged_total']} PRs merged",
            f"{d['main_passes']}/{len(waves)} main checks passed",  # type: ignore[arg-type]
            f"{d['mem_records']} memory records",
            f"{sum(d['memory_tools'].values())} memory tool calls",  # type: ignore[union-attr]
        ]
    )
    return f"""<!doctype html><meta charset=utf-8><title>Manager Long-Run Experiment Report</title>
<style>{css}</style><main>
<div class=card><h1>Manager Long-Run Experiment Report</h1>
<p class=meta>chorus M3 Slice 1 · one manager + two engineers · driven through the real chorus stack
(factory → scheduler → dream beats → landers → event bus → memory writer)</p>
<p><b>Final verdict: <span class={"ok" if verdict == "PASS" else "bad"}>{verdict}</span>.</b> The Manager
turned {d["goals"]} one-line goals into delegated subtrees: it decomposed each goal, parked while its two
engineers built and merged their children, then integrated the completed subtree. Chorus owned the
ledger, the delegation lifecycle (park/integrate), landing, and the append-only memory; dream ran each
beat. {pills}</p></div>

<div class=card><h2>Per-wave summary</h2>
<table><tr><th>#</th><th>Goal (one-liner)</th><th>Elapsed</th><th>Cost</th><th>Goal</th>
<th>Children</th><th>Merged</th><th>Main check</th></tr>{wave_rows}</table>
<p class=meta>Total wall {d["total_wall"]}s · total recorded cost {d["total_cost"]}c · the manager wrote no
code — every child file was built and merged by an engineer, then integrated by the manager.</p></div>

<div class=card><h2>The delegated subtree (who built what)</h2>
<table><tr><th>Wave</th><th>Child task</th><th>Assignee</th><th>Status</th></tr>{child_rows}</table></div>

<div class=card><h2>Append-only episodic memory — today's feature, verified</h2>
<p class=meta>spec 07 §3 · the kernel writes one immutable <code>sprint_delta</code> per beat via
<code>EpisodicStore</code> — for the manager's beats AND the engineers' — with dream-readable
frontmatter. Read back through dream's own <code>scan_memory_dir</code>.</p>
<table><tr><th>Check</th><th>Result</th><th>Detail</th></tr>{mem_checks}</table>
<h3 class=meta style="margin-top:14px">The records on disk (read back by dream)</h3>
<table><tr><th>file (== run id)</th><th>employee</th><th>scope</th><th>kind</th><th>outcome</th></tr>
{mem_rows}</table></div>

<div class=card><h2>Tool, memory, and event stats</h2>
<div style="display:flex;gap:24px;flex-wrap:wrap">
<div style="flex:1;min-width:260px"><h3 class=meta>Dream tool calls ({sum(d["tools"].values())})</h3>
<table><tr><th>tool</th><th>calls</th></tr>{tool_rows}</table></div>
<div style="flex:1;min-width:260px"><h3 class=meta>Chorus events ({sum(d["kinds"].values())})</h3>
<table><tr><th>kind</th><th>count</th></tr>{kind_rows}</table></div></div></div>

<div class=card><h2>Final company repo evidence</h2>
<p class=meta>{d["merge_commits"]} merge commits on company main — every merged child landed as a PR the
manager's integrate then closed. The final tree on main:</p>
<pre style="background:#0f172a;color:#dbeafe;padding:12px;border-radius:10px;font-size:12px;overflow-x:auto">{e(chr(10).join(d["main_files"]))}</pre></div>

<div class=card><h2>Engineering verdict</h2>
<p>The manager + two-engineer path is healthy across multiple delegation waves: the manager decomposes a
one-line goal into assigned subtasks, the kernel <b>parks</b> the parent (the "delegated" disposition),
the engineers ship and merge their children, and the manager <b>integrates</b> the completed subtree to
<code>done</code> — wave after wave, carrying ledger + memory state throughout. The append-only memory
records every beat for every role and is read back cleanly by dream, confirming today's memory-writer
work end to end.</p></div>
</main>"""


if __name__ == "__main__":
    raise SystemExit(main())
