#!/usr/bin/env python3
"""Run hard-10 tickets 01 + 02 through Hermes oneshot; compare to Bex artifacts.

Uses process env for Azure keys (never written to HERMES_HOME/.env).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples"))
from bex_hard10_catalog import TICKETS  # noqa: E402

HERMES_VENDOR = Path("/Users/divyansh/Research-docs/vendor/hermes-agent")
OUT = ROOT / "reports" / "hermes-vs-bex-20260730"
HERMES_HOME = OUT / "hermes-home"
BEX_SUITE = ROOT / "reports" / "bex-hard10-20260730-065643"
TICKET_IDS = ("01-wal-kv", "02-job-queue-migrate")


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
    base = (az.get("AZURE_OPENAI_BASE_URL") or env.get("AZURE_OPENAI_BASE_URL", "")).rstrip(
        "/"
    )
    dep = az.get("AZURE_OPENAI_DEPLOYMENT") or env.get("AZURE_OPENAI_DEPLOYMENT", "")
    if not key or not base:
        raise SystemExit("Need AZURE_OPENAI_API_KEY + AZURE_OPENAI_BASE_URL from chorus/.env")
    env["HERMES_HOME"] = str(HERMES_HOME)
    # azure-foundry path (smoke-proven)
    env["AZURE_FOUNDRY_API_KEY"] = key
    env["AZURE_FOUNDRY_BASE_URL"] = base
    env["OPENAI_API_KEY"] = key
    env["OPENAI_BASE_URL"] = base
    return env, dep, base


def _write_config(dep: str, base: str) -> None:
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
    # URLs only — keys stay in process env
    (HERMES_HOME / ".env").write_text(
        f"AZURE_FOUNDRY_BASE_URL={base}\nOPENAI_BASE_URL={base}\n"
    )


def _prompt() -> str:
    return (
        "Read TASK.md in the current working directory. "
        "Implement the FULL Intent and meet every Acceptance criterion. "
        "Stdlib/sqlite only as specified. Write real tests. Keep running "
        "`python -m pytest -q` until green. Do not invent a thinner API. "
        "Do not stop until Acceptance holds."
    )


def _seed(ticket_id: str, readme: str, intent: str, rubric: str) -> Path:
    wt = OUT / "hermes-worktrees" / ticket_id
    if wt.exists():
        shutil.rmtree(wt)
    wt.mkdir(parents=True)
    (wt / "README.md").write_text(readme)
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
        "terminal,file",
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
    log.write_text(proc.stdout + "\n---STDERR---\n" + proc.stderr)
    landed = sorted(
        str(p.relative_to(wt))
        for p in wt.rglob("*")
        if p.is_file() and p.suffix in {".py", ".sql", ".md"} and ".venv" not in p.parts
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
        pytest_out = (p2.stdout + p2.stderr)[-2000:]
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
        "stdout_tail": (proc.stdout or "")[-2000:],
        "error_hint": (proc.stdout or "").splitlines()[-1] if proc.stdout else "",
    }


def _bex_summary(ticket_id: str) -> dict:
    p = BEX_SUITE / ticket_id / "run.json"
    if not p.is_file():
        return {}
    d = json.loads(p.read_text())
    return {
        "ok": d.get("ok"),
        "attempts": d.get("attempts"),
        "wall_s": d.get("wall_s"),
        "ticks_used": d.get("ticks_used"),
        "spawns": d.get("spawns"),
        "tools": d.get("tools"),
        "landed_files": d.get("landed_files"),
        "shipped": d.get("shipped"),
    }


def main() -> int:
    env, dep, base = _hermes_env()
    if not HERMES_VENDOR.is_dir():
        raise SystemExit(f"missing hermes vendor: {HERMES_VENDOR}")
    _write_config(dep, base)
    OUT.mkdir(parents=True, exist_ok=True)
    by_id = {t.id: t for t in TICKETS}
    results = []
    for tid in TICKET_IDS:
        t = by_id[tid]
        print(f"=== Hermes oneshot {tid} ===", flush=True)
        wt = _seed(tid, t.seed_readme, t.intent, t.rubric)
        r = _run_hermes(wt, _prompt(), dep, env)
        r["id"] = tid
        r["title"] = t.title
        r["bex"] = _bex_summary(tid)
        results.append(r)
        print(
            f"  exit={r['exit_code']} wall={r['wall_s']}s pytest={r['pytest_ok']} "
            f"files={len(r['landed_files'])} hint={r.get('error_hint','')[:80]!r}",
            flush=True,
        )

    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "provider": "azure-foundry",
        "model": dep,
        "toolsets": "terminal,file",
        "results": results,
        "note": "Hard-10 suite paused during this run to avoid Azure contention.",
    }
    (OUT / "compare.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"wrote {OUT / 'compare.json'}")
    return 0 if all(r.get("pytest_ok") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
