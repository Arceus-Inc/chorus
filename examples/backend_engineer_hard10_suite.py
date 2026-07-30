"""Run all 10 hard Bex multi-beat tickets until each lands (agent_review DoD).

    uv run python examples/backend_engineer_hard10_suite.py

Env:
  CHORUS_PROBE_MAX_TICKS (default 12)
  CHORUS_PROBE_MAX_TURNS (default 24)
  CHORUS_PROBE_MAX_SPRINTS (default 6)
  CHORUS_PROBE_OUTER_RETRIES (default 1) — cold resubmit last resort (Hermes-simple)
  CHORUS_HARD10_ONLY — comma ids to run a subset (e.g. 01-wal-kv,02-job-queue-migrate)

Writes:
  reports/bex-hard10-<ts>/suite.json
  reports/bex-hard10-<ts>/report.html
  reports/bex-hard10-<ts>/<ticket-id>/{run.json,run.log,files/...}
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

# Sibling catalog when run as `uv run python examples/backend_engineer_hard10_suite.py`
sys.path.insert(0, str(Path(__file__).resolve().parent))

_EXAMPLE_COMPANY = str(uuid.uuid5(uuid.NAMESPACE_URL, "chorus-example-hard10"))

from bex_hard10_catalog import TICKETS, HardTicket
from chorus.budgets import BudgetEnforcer
from chorus.events import Event, EventKind
from chorus.heartbeat import Scheduler
from chorus.ledger import Ledger, Task, TaskStatus
from chorus.lifecycle import assign_task
from chorus.observability import EventBus
from chorus.outcomes import Verifier
from chorus.roles import RolePlugin, RoleRegistry, default_roles, role_beat_config
from chorus.workforce import Employee, LedgerWorkforce
from chorus_cli._beats import default_pricing_from_env
from chorus_cli._env import load_env_file
from chorus_employee import default_landers
from chorus_harness import EmployeeHarnessFactory

_MAX_TICKS = int(os.environ.get("CHORUS_PROBE_MAX_TICKS", "12"))
_MAX_TURNS = int(os.environ.get("CHORUS_PROBE_MAX_TURNS", "24"))
_MAX_SPRINTS = int(os.environ.get("CHORUS_PROBE_MAX_SPRINTS", "6"))
# Hermes-simple: demote cold outer resubmits — prefer in-Dream resume (default 1).
_OUTER = int(os.environ.get("CHORUS_PROBE_OUTER_RETRIES", "1"))
_REPORTS = Path(__file__).resolve().parents[1] / "reports"
_AZURE_LOCK = _REPORTS / ".azure-single-flight.lock"


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


@dataclass
class TickRecord:
    n: int
    run_status: str
    dod_status: str
    task_status: str
    tools: Counter = field(default_factory=Counter)
    evaluated: str = ""
    elapsed_s: float = 0.0


@dataclass
class ProbeStats:
    tools: Counter = field(default_factory=Counter)
    ticks: list[TickRecord] = field(default_factory=list)
    spawns: int = 0


class _TraceBus(EventBus):
    def __init__(self, stats: ProbeStats) -> None:
        super().__init__(log_path=None)
        self._stats = stats
        self._tick: TickRecord | None = None

    def bind_tick(self, tick: TickRecord) -> None:
        self._tick = tick

    def emit(self, event: Event) -> None:
        p = event.payload
        if event.kind is EventKind.RUN_TOOL_USE:
            tool = str(p.get("tool", "?"))
            self._stats.tools[tool] += 1
            if self._tick is not None:
                self._tick.tools[tool] += 1
            if tool == "spawn_subagent":
                self._stats.spawns += 1
            _log(f"    → {tool}  {str(p.get('input', ''))[:120]}")
        elif event.kind is EventKind.RUN_TOOL_RESULT:
            _log(f"    ← {p.get('tool', '?')} [{'ERR' if p.get('is_error') else 'ok'}]")
        elif event.kind is EventKind.RUN_EVALUATED:
            outcome = str(p.get("outcome", p))
            if self._tick is not None:
                self._tick.evaluated = outcome
            _log(f"    ⊢ evaluated: {outcome}")


def _registry(max_turns: int, max_sprints: int) -> RoleRegistry:
    plugins: list[RolePlugin] = []
    for plugin in default_roles():
        if plugin.name != "backend_engineer":
            plugins.append(plugin)
            continue
        plugins.append(
            RolePlugin(
                name=plugin.name,
                manifest=replace(
                    plugin.manifest,
                    max_turns=max_turns,
                    max_sprints=max_sprints,
                ),
                dod_generator=plugin.dod_generator,
                outcome_kind=plugin.outcome_kind,
                declared_routines=plugin.declared_routines,
                replace=True,
            )
        )
    return RoleRegistry.from_plugins(plugins)


def _seed(path: Path, ticket: HardTicket) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text(ticket.seed_readme, encoding="utf-8")
    (path / "app.py").write_text(
        '"""Stub."""\n\ndef health() -> str:\n    return "ok"\n',
        encoding="utf-8",
    )
    (path / "test_app.py").write_text(
        "from app import health\n\ndef test_health() -> None:\n    assert health() == 'ok'\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.name=s", "-c", "user.email=s@x", "commit", "-m", "stub"],
        check=True,
        capture_output=True,
    )


def _shipped(company_main: Path, ticket: HardTicket) -> dict[str, bool]:
    out = {f: (company_main / f).exists() for f in ticket.ship_files}
    for path, needle in ticket.ship_hints:
        p = company_main / path
        out[f"hint:{path}:{needle}"] = p.exists() and needle in p.read_text(encoding="utf-8", errors="ignore")
    return out


def _agent_deliverable_root(working_dir: Path) -> Path:
    """Root to judge for ship/land — the harness working_dir (employee worktree).

    First principle: observe where tools wrote. Under Isolation.WORKTREE that is
    the employee worktree, not ``company_root/repo`` (merge target / seed mirror).
    """
    return Path(working_dir)


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    if src.exists():
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".dream", ".harness"))


def _render_html(suite_dir: Path, results: list[dict]) -> None:
    rows = []
    for r in results:
        status = "PASS" if r.get("ok") else ("RUNNING" if r.get("status") == "running" else "FAIL")
        color = "#1d6b3c" if r.get("ok") else ("#8a5200" if status == "RUNNING" else "#8b1e1e")
        rows.append(
            f"<tr><td><code>{r['id']}</code></td><td>{r['title']}</td>"
            f"<td style='color:{color};font-weight:600'>{status}</td>"
            f"<td>{r.get('wall_s','—')}</td><td>{r.get('ticks_used','—')}</td>"
            f"<td>{r.get('spawns',0)}</td><td><a href='#{r['id']}'>detail</a></td></tr>"
        )
    sections = []
    for r in results:
        prompt = (r.get("intent") or "").replace("<", "&lt;")
        rubric = (r.get("rubric") or "").replace("<", "&lt;")
        files = r.get("landed_files") or []
        file_lis = "".join(f"<li><code>{f}</code></li>" for f in files[:40])
        ticks = r.get("tick_detail") or []
        tick_rows = "".join(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}s</td></tr>".format(
                t.get("n"),
                t.get("evaluated"),
                t.get("run_status"),
                t.get("dod_status"),
                t.get("task_status"),
                t.get("elapsed_s"),
            )
            for t in ticks
        )
        sections.append(
            f"""
<section id="{r['id']}">
  <h2>{r['id']} — {r['title']}</h2>
  <p class="meta">skills: {", ".join(r.get("skills") or [])} · ok={r.get("ok")} · attempts={r.get("attempts")}</p>
  <h3>Prompt (intent)</h3>
  <pre class="box">{prompt}</pre>
  <h3>DoD (agent_review rubric)</h3>
  <pre class="box">{rubric}</pre>
  <h3>Run</h3>
  <table><thead><tr><th>tick</th><th>eval</th><th>run</th><th>DoD</th><th>task</th><th>s</th></tr></thead>
  <tbody>{tick_rows or "<tr><td colspan=6>n/a</td></tr>"}</tbody></table>
  <p>tools: <code>{json.dumps(r.get("tools") or {})}</code> · spawns={r.get("spawns", 0)}</p>
  <p>log: <code>{r.get("log", "")}</code></p>
  <h3>Landed files</h3>
  <ul>{file_lis or "<li>(none)</li>"}</ul>
  <p>shipped map: <code>{json.dumps(r.get("shipped") or {})}</code></p>
</section>
"""
        )
    done = sum(1 for r in results if r.get("ok"))
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Bex hard-10 suite</title>
<style>
@import url("https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Source+Sans+3:wght@400;600&family=Instrument+Serif:ital@0;1&display=swap");
:root {{ --bg:#e8e4dc; --ink:#17140f; --muted:#655c52; --card:#faf7f2; --line:#cfc5b8; --accent:#8b3d12; }}
body {{ margin:0; font-family:"Source Sans 3",system-ui,sans-serif; background:var(--bg); color:var(--ink); }}
.wrap {{ max-width:960px; margin:0 auto; padding:2rem 1.2rem 3rem; }}
h1 {{ font-family:"Instrument Serif",Georgia,serif; font-weight:400; font-size:2.2rem; }}
h2 {{ font-family:"Instrument Serif",Georgia,serif; font-weight:400; border-top:1px solid var(--line); padding-top:1rem; margin-top:2rem; }}
h3 {{ font-family:"IBM Plex Mono",monospace; font-size:.75rem; letter-spacing:.06em; text-transform:uppercase; color:var(--muted); }}
table {{ width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); font-size:.88rem; }}
th,td {{ text-align:left; padding:.4rem .5rem; border-bottom:1px solid var(--line); vertical-align:top; }}
th {{ font-family:"IBM Plex Mono",monospace; font-size:.58rem; text-transform:uppercase; color:var(--muted); background:#f0ebe4; }}
pre.box {{ background:#1c1712; color:#f0e6da; padding:1rem; overflow:auto; font-family:"IBM Plex Mono",monospace; font-size:.68rem; line-height:1.45; white-space:pre-wrap; }}
.meta {{ color:var(--muted); font-size:.9rem; }}
code {{ font-family:"IBM Plex Mono",monospace; font-size:.86em; }}
</style></head><body><div class="wrap">
<p class="meta">Bex hard multi-beat suite · agent_review DoD · generator receives REVIEW RUBRIC</p>
<h1>Hard-10 suite — {done}/{len(results)} done</h1>
<table><thead><tr><th>id</th><th>title</th><th>status</th><th>wall</th><th>ticks</th><th>spawns</th><th></th></tr></thead>
<tbody>{"".join(rows)}</tbody></table>
{"".join(sections)}
</div></body></html>
"""
    (suite_dir / "report.html").write_text(html, encoding="utf-8")


def _run_one(
    ticket: HardTicket,
    *,
    out_dir: Path,
    api_key: str,
    base_url: str,
    deployment: str,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "run.log"
    stats = ProbeStats()
    bus = _TraceBus(stats)
    dod = Verifier.agent_review(rubric=ticket.rubric, artifact_class="pr")

    class _Tee:
        def __init__(self, *streams: object) -> None:
            self._streams = streams

        def write(self, data: str) -> int:
            for s in self._streams:
                s.write(data)  # type: ignore[attr-defined]
            return len(data)

        def flush(self) -> None:
            for s in self._streams:
                s.flush()  # type: ignore[attr-defined]

    log_f = log_path.open("w", encoding="utf-8")
    prev = sys.stdout
    sys.stdout = _Tee(prev, log_f)  # type: ignore[assignment]
    t0 = time.perf_counter()
    attempts = 0
    final_payload: dict = {}
    try:
        while attempts < _OUTER:
            attempts += 1
            stats.tools = Counter()
            stats.ticks = []
            stats.spawns = 0
            base = Path(tempfile.mkdtemp(prefix=f"chorus-bex-hard-{ticket.id}-"))
            os.chdir(base)
            seed = base / "source"
            _seed(seed, ticket)
            ledger = Ledger.open(
                os.environ.get("CHORUS_LEDGER_DSN", "postgresql://localhost/chorus"),
                company_id=_EXAMPLE_COMPANY,
            )
            try:
                registry = _registry(_MAX_TURNS, _MAX_SPRINTS)
                factory = EmployeeHarnessFactory(
                    api_key=api_key,
                    base_url=base_url,
                    deployment=deployment,
                    company_id=_EXAMPLE_COMPANY,
                    roles=registry,
                    pricing=default_pricing_from_env(),
                    seed=seed,
                )
                emp_id = f"bex-{ticket.id}"
                if ledger.employees.get(emp_id) is None:
                    ledger.employees.create(Employee(id=emp_id, name=f"Bex-{ticket.id}", role="backend_engineer"))
                cfg = role_beat_config(registry.get("backend_engineer").manifest)
                mat = factory.materialize(ledger.employees.get(emp_id))  # type: ignore[arg-type]
                _log("=" * 72)
                _log(f"TICKET {ticket.id} attempt={attempts}/{_OUTER} — {ticket.title}")
                _log(f"  max_sprints={cfg.max_sprints} max_turns={cfg.max_turns}")
                _log(f"  worktree={mat.working_dir}")
                task_id = str(uuid.uuid4())
                ledger.tasks.submit(Task(id=task_id, intent=ticket.intent))
                assign_task(ledger, task_id, emp_id)
                ledger.dod.create(task_id, dod)
                scheduler = Scheduler(
                    ledger=ledger,
                    workforce=LedgerWorkforce(ledger.employees),
                    beat_runner_for=factory,
                    budget_enforcer=BudgetEnforcer(ledger, company_id=_EXAMPLE_COMPANY),
                    roles=registry,
                    landers=default_landers(factory.company_root),
                    event_bus=bus,
                    max_concurrent_runs=1,
                    max_repair_attempts=max(5, _MAX_TICKS),
                )
                for n in range(1, _MAX_TICKS + 1):
                    task = ledger.tasks.get(task_id)
                    if task is None or task.status in (TaskStatus.DONE, TaskStatus.BLOCKED):
                        break
                    tick = TickRecord(n=n, run_status="-", dod_status="-", task_status="-")
                    bus.bind_tick(tick)
                    _log(f"\n  TICK {n}")
                    t_tick = time.perf_counter()

                    async def _pulse() -> None:
                        await scheduler.tick_once()
                        await scheduler.drain()

                    asyncio.run(_pulse())
                    tick.elapsed_s = round(time.perf_counter() - t_tick, 2)
                    runs = ledger.runs.for_task(task_id)
                    dod_row = ledger.dod.get_for_task(task_id)
                    final = ledger.tasks.get(task_id)
                    tick.run_status = runs[-1].status.value if runs else "?"
                    tick.dod_status = dod_row.status.value if dod_row else "-"
                    tick.task_status = final.status.value if final else "?"
                    stats.ticks.append(tick)
                    _log(
                        f"   run={tick.run_status} DoD={tick.dod_status} "
                        f"task={tick.task_status} eval={tick.evaluated} {tick.elapsed_s}s"
                    )
                    if final is not None and final.status in (TaskStatus.DONE, TaskStatus.BLOCKED):
                        break

                wall = round(time.perf_counter() - t0, 1)
                final = ledger.tasks.get(task_id)
                artifacts = ledger.artifacts.list_for_task(task_id)
                # Observe the agent's worktree (tools write here), not seed repo/.
                deliverable = _agent_deliverable_root(Path(mat.working_dir))
                shipped = _shipped(deliverable, ticket)
                landed = bool(artifacts)
                hints_ok = all(shipped.get(f"hint:{p}:{n}", False) for p, n in ticket.ship_hints)
                files_ok = all(shipped.get(f, False) for f in ticket.ship_files)
                ok = (
                    landed
                    and final is not None
                    and final.status is TaskStatus.DONE
                    and files_ok
                    and hints_ok
                )
                files_dir = out_dir / "files"
                _copy_tree(deliverable, files_dir)
                # also keep worktree snapshot for debugging
                _copy_tree(Path(mat.working_dir), out_dir / "worktree")
                landed_files = sorted(
                    str(p.relative_to(files_dir))
                    for p in files_dir.rglob("*")
                    if p.is_file()
                ) if files_dir.exists() else []
                final_payload = {
                    "id": ticket.id,
                    "title": ticket.title,
                    "skills": list(ticket.skills),
                    "intent": ticket.intent,
                    "rubric": ticket.rubric,
                    "ok": ok,
                    "attempts": attempts,
                    "wall_s": wall,
                    "ticks_used": len(stats.ticks),
                    "spawns": stats.spawns,
                    "tools": dict(stats.tools),
                    "tick_detail": [
                        {
                            "n": t.n,
                            "run_status": t.run_status,
                            "dod_status": t.dod_status,
                            "task_status": t.task_status,
                            "evaluated": t.evaluated,
                            "elapsed_s": t.elapsed_s,
                            "tools": dict(t.tools),
                        }
                        for t in stats.ticks
                    ],
                    "shipped": shipped,
                    "landed": landed,
                    "task_status": final.status.value if final else None,
                    "landed_files": landed_files,
                    "log": str(log_path),
                    "files_dir": str(files_dir),
                }
                _log(f"  → {'PASS' if ok else 'FAIL'} attempt={attempts} wall={wall}s")
                if ok:
                    return final_payload
            finally:
                ledger.close()
        return final_payload
    finally:
        sys.stdout = prev  # type: ignore[assignment]
        log_f.close()


def main() -> int:
    conflicts: list[str] = []
    load_env_file(Path(__file__).resolve().parents[1] / ".env", override=True, on_conflict=conflicts.append)
    if conflicts:
        _log(f"note: .env overrode: {', '.join(conflicts)}")
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        _log("skipping: Azure OpenAI env not set")
        return 0

    only = os.environ.get("CHORUS_HARD10_ONLY", "").strip()
    tickets = list(TICKETS)
    if only:
        want = {x.strip() for x in only.split(",") if x.strip()}
        tickets = [t for t in TICKETS if t.id in want]
        if not tickets:
            _log(f"no tickets match CHORUS_HARD10_ONLY={only!r}")
            return 1

    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    suite_dir = _REPORTS / f"bex-hard10-{ts}"
    suite_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    _log(f"suite dir: {suite_dir}")
    _log(f"budget: ticks={_MAX_TICKS} turns={_MAX_TURNS} sprints={_MAX_SPRINTS} outer={_OUTER}")

    _REPORTS.mkdir(parents=True, exist_ok=True)
    lock_f = _AZURE_LOCK.open("w", encoding="utf-8")
    try:
        import fcntl

        fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
        lock_f.write(f"pid={os.getpid()} started={ts}\n")
        lock_f.flush()
    except OSError as exc:
        _log(f"warn: could not take azure single-flight lock: {exc}")

    try:
        for ticket in tickets:
            placeholder = {
                "id": ticket.id,
                "title": ticket.title,
                "skills": list(ticket.skills),
                "intent": ticket.intent,
                "rubric": ticket.rubric,
                "status": "running",
                "ok": False,
            }
            results.append(placeholder)
            _render_html(suite_dir, results)
            (suite_dir / "suite.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

            out = suite_dir / ticket.id
            payload = _run_one(
                ticket,
                out_dir=out,
                api_key=api_key,
                base_url=base_url,
                deployment=deployment,
            )
            (out / "run.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            results[-1] = payload
            _render_html(suite_dir, results)
            (suite_dir / "suite.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
            if not payload.get("ok"):
                _log(
                    f"FATAL: ticket {ticket.id} did not complete after {_OUTER} attempts — continuing to next"
                )
    finally:
        try:
            import fcntl

            fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        lock_f.close()

    done = sum(1 for r in results if r.get("ok"))
    _log(f"\nSUITE DONE {done}/{len(results)}  report={suite_dir / 'report.html'}")
    return 0 if done == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
