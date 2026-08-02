#!/usr/bin/env python3
"""Hermes vs Bex hard-10 — one ticket at a time (or a subset).

  uv run python examples/hermes_vs_bex_hard10.py --ticket 01-wal-kv
  uv run python examples/hermes_vs_bex_hard10.py --all

For each ticket:
  1. Hermes oneshot (azure-foundry, terminal+file, yolo)
  2. Bex hard10 suite for that id only
  3. Write reports/hermes-vs-bex-hard10/<id>/compare.json + side-by-side log pointers

Keys stay in process env (never written to HERMES_HOME/.env).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples"))
from bex_hard10_catalog import TICKETS  # noqa: E402

HERMES_VENDOR = Path("/Users/divyansh/Research-docs/vendor/hermes-agent")
OUT = ROOT / "reports" / "hermes-vs-bex-hard10"
HERMES_HOME = OUT / "hermes-home"


def _load_chorus_azure() -> dict[str, str]:
    env_path = ROOT / ".env"
    vals: dict[str, str] = {}
    if not env_path.is_file():
        return vals
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


def _hermes_env() -> tuple[dict[str, str], str, str]:
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    az = _load_chorus_azure()
    key = az.get("AZURE_OPENAI_API_KEY") or env.get("AZURE_OPENAI_API_KEY", "")
    base = (az.get("AZURE_OPENAI_BASE_URL") or env.get("AZURE_OPENAI_BASE_URL", "")).rstrip("/")
    dep = az.get("AZURE_OPENAI_DEPLOYMENT") or env.get("AZURE_OPENAI_DEPLOYMENT", "")
    if not key or not base:
        raise SystemExit("Need AZURE_OPENAI_API_KEY + AZURE_OPENAI_BASE_URL from chorus/.env")
    env["HERMES_HOME"] = str(HERMES_HOME)
    env["AZURE_FOUNDRY_API_KEY"] = key
    env["AZURE_FOUNDRY_BASE_URL"] = base
    env["OPENAI_API_KEY"] = key
    env["OPENAI_BASE_URL"] = base
    return env, dep, base


def _redact(text: str, secret: str) -> str:
    return text.replace(secret, "[REDACTED]") if secret else text


def _write_hermes_config(dep: str, base: str) -> None:
    HERMES_HOME.mkdir(parents=True, exist_ok=True)
    (HERMES_HOME / "config.yaml").write_text(
        "model:\n"
        "  provider: azure-foundry\n"
        f"  default: {dep}\n"
        f"  base_url: {base}\n"
        "  api_mode: chat_completions\n"
        "terminal:\n"
        "  cwd: .\n"
        "display:\n"
        "  skin: mono\n"
    )
    (HERMES_HOME / ".env").write_text(
        f"AZURE_FOUNDRY_BASE_URL={base}\nOPENAI_BASE_URL={base}\n"
    )


def _prompt() -> str:
    return (
        "Read TASK.md in the current working directory. "
        "Implement the FULL Intent and meet every Acceptance criterion. "
        "Stdlib/sqlite only as specified. Write real tests. Keep running "
        "`python -m pytest -q` until green. Do not invent a thinner API. "
        "Stay inside this worktree — do not read or copy other report/worktree trees. "
        "Do not stop until Acceptance holds."
    )


def _seed_hermes(ticket_id: str, readme: str, intent: str, rubric: str) -> Path:
    wt = OUT / "hermes-worktrees" / ticket_id
    if wt.exists():
        shutil.rmtree(wt)
    wt.mkdir(parents=True)
    (wt / "README.md").write_text(readme)
    # Seed stub files from catalog if present in seed_readme only —
    # tickets that need app.py stubs: write minimal health stub when mentioned.
    (wt / "TASK.md").write_text(
        f"# Task\n\n## Intent\n\n{intent}\n\n## Acceptance criteria\n\n{rubric}\n"
    )
    return wt


def _run_hermes(wt: Path, prompt: str, dep: str, env: dict[str, str]) -> dict:
    log = OUT / "hermes-worktrees" / f"{wt.name}.log"
    t0 = time.time()
    run_env = dict(env)
    run_env["TERMINAL_CWD"] = str(wt)
    run_env.pop("VIRTUAL_ENV", None)
    cmd = [
        "uv",
        "run",
        "hermes",
        "-z",
        prompt,
        "-m",
        dep,
        "--provider",
        "azure-foundry",
        "-t",
        "terminal,file,delegation",
        "--yolo",
        "--ignore-user-config",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(HERMES_VENDOR),
        env=run_env,
        capture_output=True,
        text=True,
        timeout=2400,
    )
    wall = round(time.time() - t0, 1)
    log.write_text(_redact(proc.stdout + "\n---STDERR---\n" + proc.stderr, env["AZURE_FOUNDRY_API_KEY"]))
    landed = sorted(
        str(p.relative_to(wt))
        for p in wt.rglob("*")
        if p.is_file()
        and p.suffix in {".py", ".sql", ".md", ".toml", ".yaml", ".yml"}
        and ".venv" not in p.parts
        and p.name != "TASK.md"
    )
    pytest_ok = None
    pytest_out = ""
    try:
        p2 = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=str(wt),
            capture_output=True,
            text=True,
            timeout=180,
        )
        pytest_ok = p2.returncode == 0
        pytest_out = (p2.stdout + p2.stderr)[-3000:]
    except Exception as e:  # noqa: BLE001
        pytest_out = str(e)
    return {
        "exit_code": proc.returncode,
        "wall_s": wall,
        "landed_files": landed,
        "pytest_ok": pytest_ok,
        "pytest_tail": pytest_out,
        "log": str(log),
        "worktree": str(wt),
        "stdout_tail": (proc.stdout or "")[-3000:],
    }


def _run_bex(ticket_id: str) -> dict:
    """Run Bex hard10 suite for one ticket; return run.json summary + paths."""
    env = os.environ.copy()
    env["CHORUS_HARD10_ONLY"] = ticket_id
    env["CHORUS_PROBE_OUTER_RETRIES"] = env.get("CHORUS_PROBE_OUTER_RETRIES", "1")
    env["CHORUS_PROBE_MAX_TICKS"] = env.get("CHORUS_PROBE_MAX_TICKS", "12")
    env["CHORUS_PROBE_MAX_TURNS"] = env.get("CHORUS_PROBE_MAX_TURNS", "24")
    env["CHORUS_PROBE_MAX_SPRINTS"] = env.get("CHORUS_PROBE_MAX_SPRINTS", "6")
    t0 = time.time()
    proc = subprocess.run(
        ["uv", "run", "python", "examples/backend_engineer_hard10_suite.py"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=3600,
    )
    wall = round(time.time() - t0, 1)
    # Parse suite dir from stdout
    suite_dir = None
    for line in (proc.stdout or "").splitlines():
        if line.startswith("suite dir:"):
            suite_dir = Path(line.split(":", 1)[1].strip())
            break
    ticket_out = OUT / "bex-runs" / ticket_id
    ticket_out.mkdir(parents=True, exist_ok=True)
    (ticket_out / "suite.stdout.log").write_text(_redact(proc.stdout or "", env["AZURE_FOUNDRY_API_KEY"]))
    (ticket_out / "suite.stderr.log").write_text(_redact(proc.stderr or "", env["AZURE_FOUNDRY_API_KEY"]))
    summary: dict = {
        "exit_code": proc.returncode,
        "wall_s_suite": wall,
        "suite_dir": str(suite_dir) if suite_dir else None,
        "ok": False,
    }
    if suite_dir and (suite_dir / ticket_id / "run.json").is_file():
        # Copy artifacts for stable pointers
        dest = ticket_out / "latest"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(suite_dir / ticket_id, dest)
        run = json.loads((dest / "run.json").read_text())
        summary.update(
            {
                "ok": bool(run.get("ok")),
                "attempts": run.get("attempts"),
                "wall_s": run.get("wall_s"),
                "ticks_used": run.get("ticks_used"),
                "spawns": run.get("spawns"),
                "tools": run.get("tools"),
                "shipped": run.get("shipped"),
                "landed_files": run.get("landed_files"),
                "task_status": run.get("task_status"),
                "output": run.get("output", ""),
                "stdout_tail": str(run.get("output", ""))[-3000:],
                "run_json": str(dest / "run.json"),
                "run_log": str(dest / "run.log"),
            }
        )
    return summary


def _gap(hermes: dict, bex: dict) -> dict:
    return {
        "hermes_pytest": hermes.get("pytest_ok"),
        "bex_ok": bex.get("ok"),
        "hermes_wall_s": hermes.get("wall_s"),
        "bex_wall_s": bex.get("wall_s"),
        "bex_spawns": bex.get("spawns"),
        "bex_behind": (not bex.get("ok")) and bool(hermes.get("pytest_ok")),
        "bex_slower": (
            isinstance(hermes.get("wall_s"), (int, float))
            and isinstance(bex.get("wall_s"), (int, float))
            and bex["wall_s"] > hermes["wall_s"] * 1.25
        ),
    }


def _collect_summary(out: Path = OUT) -> list[dict]:
    """Return every persisted comparison in catalog order."""
    tickets = []
    for ticket in TICKETS:
        path = out / ticket.id / "compare.json"
        if not path.is_file():
            continue
        comparison = json.loads(path.read_text())
        tickets.append(
            {
                "id": ticket.id,
                "gap": comparison.get("gap", {}),
                "hermes_pytest": comparison.get("hermes", {}).get("pytest_ok"),
                "bex_ok": comparison.get("bex", {}).get("ok"),
            }
        )
    return tickets


def _scoreboard(tickets: list[dict]) -> dict[str, object]:
    """Aggregate persisted ticket comparisons into a small benchmark scoreboard."""
    hermes_pass = sum(bool(ticket.get("hermes_pytest")) for ticket in tickets)
    bex_pass = sum(bool(ticket.get("bex_ok")) for ticket in tickets)
    bex_walls = [
        float(ticket["gap"]["bex_wall_s"])
        for ticket in tickets
        if isinstance(ticket.get("gap", {}).get("bex_wall_s"), (int, float))
    ]
    hermes_walls = [
        float(ticket["gap"]["hermes_wall_s"])
        for ticket in tickets
        if isinstance(ticket.get("gap", {}).get("hermes_wall_s"), (int, float))
    ]
    return {
        "tickets_compared": len(tickets),
        "hermes_pass_at_1": hermes_pass,
        "bex_pass_at_1": bex_pass,
        "bex_completion_rate": (bex_pass / len(tickets)) if tickets else 0.0,
        "bex_spawn_total": sum(int(ticket["gap"].get("bex_spawns") or 0) for ticket in tickets),
        "bex_median_wall_s": median(bex_walls) if bex_walls else None,
        "hermes_median_wall_s": median(hermes_walls) if hermes_walls else None,
        "bex_slower_count": sum(bool(ticket["gap"].get("bex_slower")) for ticket in tickets),
    }


def _clean_hard10_ledger() -> None:
    """Drop stuck runs/wakes for the hard10 company so ticks dispatch."""
    try:
        from chorus.ledger import Ledger, TaskStatus

        company = str(uuid.uuid5(uuid.NAMESPACE_URL, "chorus-example-hard10"))
        # Load .env into process for DSN
        for k, v in _load_chorus_azure().items():
            os.environ.setdefault(k, v)
        dsn = os.environ.get("CHORUS_LEDGER_DSN", "postgresql://localhost/chorus")
        ledger = Ledger.open(dsn, company_id=company)
        ledger.runs.cancel_running()
        ledger.wakes.drop_queued()
        conn = ledger._conn
        for r in conn.execute(
            "SELECT id, checkout_run_id FROM task "
            "WHERE status IN ('todo', 'in_progress', 'blocked')"
        ).fetchall():
            rid = r["checkout_run_id"] or "orphan"
            try:
                ledger.tasks.release_locks(r["id"], run_id=rid)
            except Exception:
                pass
            try:
                ledger.tasks.set_status(r["id"], TaskStatus.CANCELLED)
            except Exception:
                conn.execute(
                    "UPDATE task SET status='cancelled', checkout_run_id=NULL, "
                    "execution_run_id=NULL, cancelled_at=NOW(), updated_at=NOW() WHERE id=?",
                    (r["id"],),
                )
                conn.commit()
        print(f"ledger cleaned company={company}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"ledger clean skipped: {e}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticket", action="append", dest="tickets", help="Ticket id (repeatable)")
    ap.add_argument("--all", action="store_true", help="All 10 hard tickets")
    ap.add_argument("--skip-hermes", action="store_true")
    ap.add_argument("--skip-bex", action="store_true")
    ap.add_argument("--no-clean", action="store_true")
    args = ap.parse_args()

    if args.all:
        ids = [t.id for t in TICKETS]
    elif args.tickets:
        ids = args.tickets
    else:
        ap.error("pass --ticket ID or --all")

    by_id = {t.id: t for t in TICKETS}
    for tid in ids:
        if tid not in by_id:
            raise SystemExit(f"unknown ticket {tid}")

    if not args.no_clean:
        _clean_hard10_ledger()

    env, dep, base = _hermes_env()
    if not args.skip_hermes and not HERMES_VENDOR.is_dir():
        raise SystemExit(f"missing hermes vendor: {HERMES_VENDOR}")
    if not args.skip_hermes:
        _write_hermes_config(dep, base)

    OUT.mkdir(parents=True, exist_ok=True)
    rc = 0
    for tid in ids:
        t = by_id[tid]
        ticket_dir = OUT / tid
        ticket_dir.mkdir(parents=True, exist_ok=True)
        print("=" * 72, flush=True)
        print(f"TICKET {tid} — {t.title}", flush=True)

        hermes: dict = {}
        if not args.skip_hermes:
            print(f"  → Hermes oneshot…", flush=True)
            required_paths = "Required paths: " + ", ".join(t.ship_files) + "."
            wt = _seed_hermes(
                tid,
                t.seed_readme,
                f"{t.intent}\n\n{required_paths}",
                f"{t.rubric}\n{required_paths}",
            )
            hermes = _run_hermes(wt, _prompt(), dep, env)
            print(
                f"  ← Hermes exit={hermes['exit_code']} wall={hermes['wall_s']}s "
                f"pytest={hermes['pytest_ok']} files={len(hermes['landed_files'])}",
                flush=True,
            )
            previous = {}
            if (ticket_dir / "compare.json").is_file():
                previous = json.loads((ticket_dir / "compare.json").read_text())
            previous.update(
                {
                    "id": tid,
                    "title": t.title,
                    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "model": dep,
                    "hermes": hermes,
                }
            )
            (ticket_dir / "compare.json").write_text(json.dumps(previous, indent=2) + "\n")
        else:
            # reuse prior if present
            prev = ticket_dir / "compare.json"
            if prev.is_file():
                hermes = json.loads(prev.read_text()).get("hermes") or {}

        bex: dict = {}
        if not args.skip_bex:
            if not args.no_clean:
                _clean_hard10_ledger()
            print(f"  → Bex suite…", flush=True)
            bex = _run_bex(tid)
            print(
                f"  ← Bex ok={bex.get('ok')} wall={bex.get('wall_s')} "
                f"ticks={bex.get('ticks_used')} spawns={bex.get('spawns')}",
                flush=True,
            )
        else:
            prev = ticket_dir / "compare.json"
            if prev.is_file():
                bex = json.loads(prev.read_text()).get("bex") or {}

        gap = _gap(hermes, bex)
        compare = {
            "id": tid,
            "title": t.title,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "model": dep,
            "hermes": hermes,
            "bex": bex,
            "gap": gap,
        }
        (ticket_dir / "compare.json").write_text(json.dumps(compare, indent=2) + "\n")
        print(f"  gap: {json.dumps(gap)}", flush=True)
        print(f"  wrote {ticket_dir / 'compare.json'}", flush=True)
        if gap.get("bex_behind") or not bex.get("ok"):
            rc = 1

    tickets = _collect_summary()
    (OUT / "summary.json").write_text(
        json.dumps(
            {
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "scoreboard": _scoreboard(tickets),
                "tickets": tickets,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"SUMMARY {OUT / 'summary.json'} rc={rc}", flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
