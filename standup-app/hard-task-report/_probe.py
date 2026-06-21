"""Deep-probe a finished --org run workspace → probe.json.

Usage: python _probe.py <run_home_dir>     # run_home holds meta.env (name, workspace, db, report)

Extracts, with NO mention-of-task bias, the signals that reveal chorus's hard failure modes:
ledger task/role accounting, the landed repo's shape (packaging, duplicate modules, empty exports,
harness-artifact leak, README stub), done-but-not-landed (unmerged author branch), role mis-assignment,
and an actual build/test attempt for the deliverable's language.
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path


# ── helpers ──────────────────────────────────────────────────────────────────────────────────────
def _meta(home: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (home / "meta.env").read_text().splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k] = v
    return out


def _git(repo: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=30
        ).stdout.strip()
    except Exception:
        return ""


def _run(cmd: list[str], cwd: Path, timeout: int = 240) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr)[-4000:]
    except FileNotFoundError:
        return 127, "tool-not-installed"
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except Exception as exc:
        return 1, f"{type(exc).__name__}: {exc}"


# ── ledger probe ─────────────────────────────────────────────────────────────────────────────────
def probe_ledger(db: Path) -> dict:
    if not db.exists():
        return {"error": "no db"}
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    emp = {r["id"]: {"name": r["name"], "role": r["role"]} for r in con.execute(
        "SELECT id,name,role FROM employee")}
    tasks = [dict(r) for r in con.execute(
        "SELECT id,intent,status,assignee_employee_id,assignee_user_id,depth,parent_id FROM task")]
    runs = con.execute("SELECT COUNT(*) c FROM run").fetchone()["c"]
    recov = [dict(r) for r in con.execute(
        "SELECT id,kind,source_task_id,status FROM recovery_action")] if _has(con, "recovery_action") else []
    con.close()

    status_counts: dict[str, int] = {}
    for t in tasks:
        status_counts[t["status"]] = status_counts.get(t["status"], 0) + 1

    roots = [t for t in tasks if (t["depth"] or 0) == 0 or t["parent_id"] is None]
    top = roots[0] if roots else (tasks[0] if tasks else None)

    def role_of(t: dict) -> str | None:
        e = emp.get(t["assignee_employee_id"] or "")
        return e["role"] if e else None

    # BUG-006: a code/deliverable child assigned to a non-engineer, then rejected/blocked.
    # 'manager' is excluded — a blocked/parked manager task is the legitimately-parked director,
    # not a mis-assignment; the real wart is a deliverable handed to pm/analyst/reviewer.
    misassigned = [
        {"id": t["id"], "intent": (t["intent"] or "")[:90], "role": role_of(t), "status": t["status"]}
        for t in tasks
        if role_of(t) in {"pm", "analyst", "reviewer"}
        and t["status"] in {"rejected", "blocked", "cancelled"}
        and (t["parent_id"] is not None)
    ]
    return {
        "employees": [{"id": k, **v} for k, v in emp.items()],
        "emp_by_role": _tally([v["role"] for v in emp.values()]),
        "n_tasks": len(tasks), "n_runs": runs,
        "status_counts": status_counts,
        "top_status": top["status"] if top else None,
        "top_intent": (top["intent"] or "")[:120] if top else None,
        "misassigned": misassigned,
        "recovery_cards": recov,
        "done_tasks": [{"id": t["id"], "intent": (t["intent"] or "")[:90],
                        "role": role_of(t), "emp": t["assignee_employee_id"]}
                       for t in tasks if t["status"] == "done"],
    }


def _has(con: sqlite3.Connection, table: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def _tally(xs: list) -> dict[str, int]:
    out: dict[str, int] = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return out


# ── repo probe ───────────────────────────────────────────────────────────────────────────────────
PACKAGING = {
    "Python": ["pyproject.toml", "setup.py", "setup.cfg"],
    "Rust": ["Cargo.toml"],
    "TypeScript": ["package.json", "tsconfig.json"],
    "Go": ["go.mod"],
    "Full-stack": ["package.json", "pyproject.toml"],
}
HARNESS_LEAK = ("docs/exec-plans/", "docs/evals/", ".harness/", "exec-plans/", "evals/")


def probe_repo(repo: Path, lang: str) -> dict:
    if not repo.exists() or not (repo / ".git").exists():
        return {"error": f"no repo at {repo}"}
    files = [f for f in _git(repo, "ls-files").splitlines() if f]
    log = _git(repo, "log", "--oneline", "-40").splitlines()
    merges = [ln for ln in log if "merge" in ln.lower() or "chorus/" in ln]
    # per-employee merge fingerprint (chorus/<eid> branches)
    merged_eids = set(re.findall(r"chorus/([a-z0-9_]+)", "\n".join(log)))

    sizes = {}
    for f in files:
        p = repo / f
        try:
            sizes[f] = p.stat().st_size
        except OSError:
            sizes[f] = -1

    # duplicate modules: same basename appearing in >1 directory (e.g. root + package)
    from collections import defaultdict
    by_base: dict[str, list[str]] = defaultdict(list)
    for f in files:
        if f.endswith((".py", ".rs", ".ts", ".go")):
            by_base[Path(f).name].append(f)
    duplicates = {b: v for b, v in by_base.items() if len(v) > 1}

    # empty package exports (python __init__/ rust lib.rs / ts index / go: n.a.)
    empty_exports = []
    for f in files:
        if Path(f).name in {"__init__.py", "lib.rs", "index.ts", "mod.rs"} and 0 <= sizes.get(f, 0) <= 40:
            empty_exports.append(f)

    leak = [f for f in files if any(f.startswith(h) or h.strip("/") in f for h in HARNESS_LEAK)]

    readme = next((f for f in files if f.lower() == "readme.md"), None)
    readme_stub = False
    if readme:
        txt = (repo / readme).read_text(errors="ignore").strip()
        readme_stub = len(txt) < 80 or txt.lower() in {"# company repo", "# repo"}

    pkg_present = [m for m in PACKAGING.get(lang, []) if m in files]

    return {
        "n_files": len(files), "files": files[:200], "sizes": sizes,
        "log": log[:40], "merges": merges, "merged_eids": sorted(merged_eids),
        "duplicates": duplicates, "empty_exports": empty_exports,
        "harness_leak": leak, "readme": readme, "readme_stub": readme_stub,
        "packaging_present": pkg_present, "packaging_expected": PACKAGING.get(lang, []),
    }


# ── build/test attempt (real) ──────────────────────────────────────────────────────────────────────
def probe_build(repo: Path, lang: str) -> dict:
    if not repo.exists():
        return {"skipped": "no repo"}
    attempts = []

    def have(tool: str) -> bool:
        return shutil.which(tool) is not None

    if (lang in ("Python", "Full-stack") and any(repo.glob("**/*.py"))
            and (have("python") or have("python3"))):
        py = "python" if have("python") else "python3"
        rc, out = _run([py, "-m", "pytest", "-q", "--no-header"], repo, 180)
        attempts.append({"cmd": "pytest -q", "rc": rc, "tail": out[-1200:]})
    if lang == "Rust":
        if have("cargo"):
            rc, out = _run(["cargo", "build", "--release"], repo, 240)
            attempts.append({"cmd": "cargo build --release", "rc": rc, "tail": out[-1200:]})
            rc2, out2 = _run(["cargo", "test"], repo, 240)
            attempts.append({"cmd": "cargo test", "rc": rc2, "tail": out2[-1200:]})
        else:
            attempts.append({"cmd": "cargo", "rc": 127, "tail": "cargo not installed"})
    if lang in ("TypeScript", "Full-stack") and (repo / "package.json").exists():
        if have("npm"):
            _run(["npm", "install", "--no-audit", "--no-fund"], repo, 300)
            rc, out = _run(["npx", "tsc", "--noEmit"], repo, 180)
            attempts.append({"cmd": "tsc --noEmit", "rc": rc, "tail": out[-1200:]})
        else:
            attempts.append({"cmd": "npm/tsc", "rc": 127, "tail": "npm not installed"})
    if lang == "Go" and (repo / "go.mod").exists():
        if have("go"):
            rc, out = _run(["go", "build", "./..."], repo, 180)
            attempts.append({"cmd": "go build ./...", "rc": rc, "tail": out[-1200:]})
            rc2, out2 = _run(["go", "test", "./..."], repo, 180)
            attempts.append({"cmd": "go test ./...", "rc": rc2, "tail": out2[-1200:]})
        else:
            attempts.append({"cmd": "go", "rc": 127, "tail": "go not installed"})
    return {"attempts": attempts}


# ── derive flaws ────────────────────────────────────────────────────────────────────────────────
def derive_flaws(led: dict, repo: dict, build: dict) -> list[dict]:
    flaws: list[dict] = []

    def add(sev: str, code: str, title: str, detail: str) -> None:
        flaws.append({"sev": sev, "code": code, "title": title, "detail": detail})

    if repo.get("error"):
        add("CRITICAL", "NO-REPO", "Nothing landed on company main", repo["error"])
        return flaws

    if led.get("top_status") and led["top_status"] not in ("done",):
        add("FRAMEWORK", "BUG-007", f"Top goal ended {led['top_status']}, not done",
            "The director hit the integrate cap / deadline without a clean done verdict.")
    if led.get("misassigned"):
        ex = ", ".join(f"{m['id'][:14]}→{m['role']}({m['status']})" for m in led["misassigned"][:4])
        add("FRAMEWORK", "BUG-006", "Deliverable assigned to a non-engineer role", ex)
    # done ≠ landed: employees with done tasks but no merge of their branch
    done_eids = {t["emp"] for t in led.get("done_tasks", []) if t.get("emp")}
    merged = set(repo.get("merged_eids", []))
    unmerged = [e for e in done_eids if not any(e.endswith(m) or m.endswith(e[-6:]) for m in merged)] if merged else []
    if merged and unmerged:
        add("FRAMEWORK", "BUG-005", "done ≠ landed — an author branch never integrated",
            f"{len(unmerged)} employee(s) have done tasks but no merge on main: {unmerged[:4]}")
    if repo.get("duplicates"):
        d = "; ".join(f"{b}: {v}" for b, v in list(repo["duplicates"].items())[:4])
        add("CRITICAL", "DUP", "Two+ copies of one module (no file ownership)", d)
    if repo.get("empty_exports"):
        add("CRITICAL", "EXPORTS", "Package exports nothing", ", ".join(repo["empty_exports"]))
    if not repo.get("packaging_present") and repo.get("packaging_expected"):
        add("CRITICAL", "PKG", "No packaging manifest — not a distributable artifact",
            f"expected one of {repo['packaging_expected']}, found none")
    if repo.get("harness_leak"):
        add("HIGH", "LEAK", "Harness-internal files leaked into the deliverable",
            f"{len(repo['harness_leak'])} files, e.g. {repo['harness_leak'][:3]}")
    if repo.get("readme") is None or repo.get("readme_stub"):
        add("HIGH", "README", "README missing or still a stub",
            repo.get("readme") or "no README.md tracked")
    # build verdict
    for a in build.get("attempts", []):
        if a["rc"] == 127:
            add("INFO", "TOOLCHAIN", f"Could not verify build ({a['cmd']})", a["tail"])
        elif a["rc"] not in (0,):
            add("CRITICAL", "BUILD", f"Deliverable fails `{a['cmd']}` (rc={a['rc']})", a["tail"][-400:])
    return flaws


def main() -> int:
    home = Path(sys.argv[1])
    meta = _meta(home)
    name = meta.get("name", home.name)
    manifest = json.loads(Path("standup-app/hard-task-report/_manifest.json").read_text())
    g = next((x for x in manifest if x["name"] == name), {"lang": "Python", "brief": "", "n": 0})
    lang = g["lang"]
    if int(g.get("n", 0)) >= 11:  # goals 11-15 are full-stack regardless of heading lang
        lang = "Full-stack"
    ws = Path(meta.get("workspace", ""))
    db = Path(meta.get("db", ""))
    # locate landed repo: <ws>/work/**/repo with .git
    repo = next((p.parent for p in ws.glob("work/**/repo/.git")), ws / "missing-repo") if ws.exists() else Path("missing")

    led = probe_ledger(db)
    rep = probe_repo(repo, lang)
    bld = probe_build(repo, lang)
    flaws = derive_flaws(led, rep, bld)

    out = {
        "name": name, "lang": lang, "brief": g.get("brief", ""),
        "meta": meta, "repo_path": str(repo),
        "ledger": led, "repo": rep, "build": bld, "flaws": flaws,
    }
    (home / "probe.json").write_text(json.dumps(out, indent=2, default=str))
    print(f"[{name}] top={led.get('top_status')} files={rep.get('n_files')} "
          f"flaws={len(flaws)} → {home/'probe.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
