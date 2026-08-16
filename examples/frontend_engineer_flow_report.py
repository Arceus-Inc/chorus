"""Generate a self-contained, light-theme HTML report of a Frontend Engineer beat's FULL FLOW.

The visual twin of ``designer_flow_report.py``, adapted to the engineer's craft: it parses the per-task
observer trace captured by ``frontend_engineer_hard_tasks.py`` (the ``[tool ->] / [tool <-]`` lines, the
``[EVALUATED] {...}`` sprint verdicts, the ``intent:`` line, and a ``[verdict] key=value`` block),
reconstructs the nested call tree (a ``spawn_subagent`` frame holds every tool the child ran until its
matching close), groups the top-level steps into the engineer's canonical phases (Understand & size ->
Build -> Author tests -> Run & capture -> Review under pressure), and renders it all as one static HTML
file with inline CSS + tiny JS for the collapsibles.

What makes this report different from a transcript: it leads with the **independent re-verification
verdict** — the DoD floor result plus the exit codes of the unit and e2e suites RE-RUN by the harness in
a clean process against the shipped worktree. A green transcript that fails the honest re-run reads
``NOT PROVEN`` here. It also embeds the produced artifacts (the ``package.json`` that reveals the chosen
stack, the app entry + its source/components, the unit + e2e suites, the evidence summary, and the
captured re-run logs) — globbed across whatever layout the stack the engineer picked happens to use.

Usage:
  uv run python examples/frontend_engineer_flow_report.py            # regenerate every task's report
  uv run python examples/frontend_engineer_flow_report.py tip board  # only these task keys

Reads:  reports/frontend-engineer-artifacts/<key>/{flow.log,_meta.txt, + artifacts}
Writes: reports/frontend-engineer-artifacts/<key>/flow-report.html
"""

from __future__ import annotations

import ast
import html
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path("chorus") if Path("chorus").is_dir() else Path(".")
_ART_ROOT = _ROOT / "reports" / "frontend-engineer-artifacts"

_RE_INVOKE = re.compile(r"^\s*\[tool ->\]\s+(\S+)\s*(.*)$")
_RE_RESULT = re.compile(r"^\s*\[tool <-\]\s+(\S+)(\s+\(ERROR\))?\s*$")
_RE_EVAL = re.compile(r"^\s*\[EVALUATED\]\s+(\{.*\})\s*$")
_RE_INTENT = re.compile(r"^intent:\s*(.*)$")
_RE_VERDICT = re.compile(r"^\[verdict\]\s+(\w+)\s*=\s*(.*)$")

# Tool -> (category label, accent colour) for the legend + per-step dot.
_TOOL_META: dict[str, tuple[str, str]] = {
    "spawn_subagent": ("subagent", "#7c3aed"),
    "run_command": ("run", "#0d9488"),
    "bash": ("run", "#0d9488"),
    "git": ("git", "#d97706"),
    "evidence_scan": ("evidence", "#2563eb"),
    "write_file": ("write", "#16a34a"),
    "read_file": ("read", "#6b7280"),
    "skill": ("skill", "#db2777"),
    "web_search": ("web", "#0891b2"),
    "web_extract": ("web", "#0891b2"),
}


@dataclass
class Node:
    tool: str
    payload: str
    children: list[Node] = field(default_factory=list)
    error: bool = False
    is_subagent: bool = False
    subagent_name: str = ""


@dataclass
class Eval:
    sprint: int
    outcome: str
    score: float
    notes: str


def _field(payload: str, key: str) -> str:
    """Extract a single quoted string field from a repr-style dict payload.

    The observer truncates long payloads with an ellipsis, so ``ast.literal_eval`` usually fails — a
    tolerant regex is more robust for the few fields we surface.
    """
    m = re.search(rf"'{key}':\s*'((?:[^'\\]|\\.)*)'", payload)
    return str(m.group(1)) if m else ""


def _short_payload(tool: str, payload: str) -> str:
    """A compact one-line description of a call's key argument(s)."""
    payload = payload.strip()
    if tool == "spawn_subagent":
        return _field(payload, "name")
    if tool in {"read_file", "write_file"}:
        return _field(payload, "path")
    if tool == "skill":
        return _field(payload, "name")
    if tool in {"bash", "run_command"}:
        cmd = _field(payload, "command")
        return cmd if len(cmd) <= 88 else cmd[:88] + "…"
    if tool == "git":
        m = re.search(r"'args':\s*\[([^\]]*)\]", payload)
        if m:
            args = re.findall(r"'((?:[^'\\]|\\.)*)'", m.group(1))
            return "git " + " ".join(args)
        return "git"
    if tool == "evidence_scan":
        return "(scan the worktree)"
    if tool == "web_search":
        return _field(payload, "query")
    if tool == "web_extract":
        urls = re.findall(r"https?://[^'\"\s\\]+", payload)
        if urls:
            extra = f"  +{len(urls) - 1} more" if len(urls) > 1 else ""
            return str(urls[0]) + extra
        return ""
    return ""


def parse_log(text: str) -> tuple[str, list[Node], list[Eval], dict[str, str]]:
    intent = ""
    verdict: dict[str, str] = {}
    root_children: list[Node] = []
    evals: list[Eval] = []
    stack: list[list[Node]] = [root_children]  # each frame is a children-list
    subagent_stack: list[Node] = []
    last_leaf: Node | None = None

    for line in text.splitlines():
        m = _RE_INTENT.match(line)
        if m and not intent:
            intent = m.group(1).strip()
            continue
        m = _RE_VERDICT.match(line)
        if m:
            verdict[m.group(1)] = m.group(2).strip()
            continue
        m = _RE_EVAL.match(line)
        if m:
            try:
                data = ast.literal_eval(m.group(1))
            except (ValueError, SyntaxError):
                data = {}
            evals.append(
                Eval(
                    sprint=int(data.get("sprint_number", 0)),
                    outcome=str(data.get("outcome", "")),
                    score=float(data.get("score", 0.0)),
                    notes=str(data.get("notes", "")),
                )
            )
            continue
        m = _RE_INVOKE.match(line)
        if m:
            tool, payload = m.group(1), m.group(2)
            node = Node(tool=tool, payload=_short_payload(tool, payload))
            stack[-1].append(node)
            if tool == "spawn_subagent":
                node.is_subagent = True
                node.subagent_name = node.payload
                subagent_stack.append(node)
                stack.append(node.children)
                last_leaf = None
            else:
                last_leaf = node
            continue
        m = _RE_RESULT.match(line)
        if m:
            tool, err = m.group(1), bool(m.group(2))
            if tool == "spawn_subagent" and subagent_stack:
                closed = subagent_stack.pop()
                closed.error = err
                stack.pop()
                last_leaf = None
            elif last_leaf is not None and last_leaf.tool == tool:
                last_leaf.error = err
            continue

    return intent, root_children, evals, verdict


# --- phase grouping ---------------------------------------------------------

_PHASES = [
    (
        "Understand &amp; size",
        "Read the intent and any existing code, load the craft <b>skill</b> that fits, <b>choose the stack</b> that suits the job, and pick the smallest slice that <em>actually works</em>.",
    ),
    (
        "Build the slice",
        "Write the running app in the stack it chose — accessible by construction and wired end to end so the behaviour happens in the browser.",
    ),
    (
        "Author the tests",
        "Write <b>unit</b> tests for the logic (in whatever runner the stack uses) and a real-browser <b>Playwright</b> e2e that drives the app the way a user does.",
    ),
    (
        "Run &amp; capture the proof",
        "Install deps, run both suites, and tee the <em>real</em> output into the durable <code>test_evidence/</code> bundle.",
    ),
    (
        "Review under pressure",
        "Spawn the read-only <b>code_reviewer</b>, self-check with <b>evidence_scan</b> and Playwright skills, address every blocker/major, and re-run until green.",
    ),
]


def phase_for(node: Node, current: int) -> int:
    """Monotonic phase pointer — a node can advance the phase, never rewind it."""
    wanted = current
    if node.is_subagent:
        if node.subagent_name == "code_reviewer":
            wanted = 4
    elif node.tool == "evidence_scan":
        wanted = max(wanted, 4)
    elif node.tool in {"bash", "run_command"}:
        cmd = node.payload.lower()
        if any(
            k in cmd
            for k in (
                "npm install",
                "npm test",
                "npm run",
                "playwright test",
                "vitest",
                "jest",
                "node --test",
                "npm ci",
            )
        ):
            wanted = max(wanted, 3)
    elif node.tool == "write_file":
        p = node.payload
        low = p.lower()
        if (
            ".test." in low
            or "/spec" in low
            or ".spec." in low
            or "e2e" in low
            or "playwright.config" in low
            or low.endswith("package.json")
        ):
            wanted = max(wanted, 2)
        elif (
            low.startswith("test_evidence")
            or low.endswith("summary.md")
            or low.endswith("unit.txt")
            or low.endswith("e2e.txt")
        ):
            wanted = max(wanted, 3)
        elif (
            low.endswith(".html")
            or low.endswith(".css")
            or (low.startswith("src/") and low.endswith(".js"))
        ):
            wanted = max(wanted, 1)
    return max(current, wanted)


# --- rendering --------------------------------------------------------------


def _dot(tool: str) -> str:
    _, colour = _TOOL_META.get(tool, ("", "#6b7280"))
    return f'<span class="dot" style="background:{colour}"></span>'


def _err_badge(node: Node) -> str:
    return (
        ' <span class="err" title="benign — usually a retry reading an offloaded scratch file or a Windows-only DoD floor probe">err</span>'
        if node.error
        else ""
    )


def render_node(node: Node) -> str:
    payload = html.escape(node.payload)
    if node.is_subagent:
        inner = "".join(render_node(c) for c in node.children)
        n_calls = len(node.children)
        n_err = sum(1 for c in node.children if c.error)
        err_note = f" · {n_err} benign err" if n_err else ""
        return (
            f'<details class="sub">'
            f"<summary>{_dot('spawn_subagent')}<b>spawn_subagent</b> "
            f'<span class="agent">{html.escape(node.subagent_name)}</span>'
            f'<span class="count">{n_calls} inner call{"s" if n_calls != 1 else ""}{err_note}</span>'
            f"{_err_badge(node)}</summary>"
            f'<div class="subbody">{inner}</div>'
            f"</details>"
        )
    return (
        f'<div class="step">{_dot(node.tool)}'
        f'<span class="tool">{html.escape(node.tool)}</span>'
        f'<span class="arg">{payload}</span>{_err_badge(node)}</div>'
    )


def render_phases(nodes: list[Node]) -> str:
    buckets: list[list[Node]] = [[] for _ in _PHASES]
    current = 0
    for node in nodes:
        current = phase_for(node, current)
        buckets[current].append(node)

    cards = []
    for i, (title, desc) in enumerate(_PHASES):
        body = (
            "".join(render_node(n) for n in buckets[i])
            or '<div class="empty">— no steps recorded —</div>'
        )
        cards.append(
            f'<section class="phase">'
            f'<div class="phase-head"><span class="pnum">{i}</span>'
            f"<div><h3>{title}</h3><p>{desc}</p></div></div>"
            f'<div class="phase-body">{body}</div>'
            f"</section>"
        )
    return "".join(cards)


def tool_counts(nodes: list[Node]) -> dict[str, int]:
    counts: dict[str, int] = {}

    def walk(ns: list[Node]) -> None:
        for n in ns:
            counts[n.tool] = counts.get(n.tool, 0) + 1
            walk(n.children)

    walk(nodes)
    return counts


def count_subagents(nodes: list[Node]) -> dict[str, int]:
    counts: dict[str, int] = {}

    def walk(ns: list[Node]) -> None:
        for n in ns:
            if n.is_subagent:
                counts[n.subagent_name] = counts.get(n.subagent_name, 0) + 1
            walk(n.children)

    walk(nodes)
    return counts


def _read(task_dir: Path, rel: str) -> tuple[str, int]:
    p = task_dir / rel
    if not p.is_file():
        return "", 0
    txt = p.read_text(encoding="utf-8", errors="replace")
    return txt, len(txt.split())


def _artifact_block(task_dir: Path, rel: str, label: str, *, code: bool = True) -> str:
    txt, words = _read(task_dir, rel)
    if not txt:
        return ""
    unit = "lines" if code else "words"
    n = txt.count("\n") + 1 if code else words
    return (
        f'<details class="art"><summary>{html.escape(label)} · {n} {unit}</summary>'
        f"<pre>{html.escape(txt)}</pre></details>"
    )


def _sorted_rel(task_dir: Path, pattern: str) -> list[str]:
    base = task_dir
    return sorted(
        str(p.relative_to(base)).replace("\\", "/") for p in base.glob(pattern) if p.is_file()
    )


def _verdict_row(label: str, value: str, ok: bool, detail: str = "") -> str:
    cls = "ok" if ok else "warn"
    tail = f' <span class="muted">{html.escape(detail)}</span>' if detail else ""
    return (
        f'<div class="vrow"><span class="vlabel">{html.escape(label)}</span>'
        f'<span class="badge {cls}">{html.escape(value)}</span>{tail}</div>'
    )


def build_html(task_dir: Path) -> str:
    key = task_dir.name
    log_p = task_dir / "flow.log"
    text = log_p.read_text(encoding="utf-8", errors="replace") if log_p.is_file() else ""
    intent, nodes, evals, verdict = parse_log(text)

    counts = tool_counts(nodes)
    subs = count_subagents(nodes)
    total_calls = sum(counts.values())
    run_calls = counts.get("bash", 0) + counts.get("run_command", 0)

    dod_pass = verdict.get("dod_floor", "").lower() in {"pass", "true", "passed"}
    unit_exit = verdict.get("unit_reverify_exit", "?")
    e2e_exit = verdict.get("e2e_reverify_exit", "?")
    truly = verdict.get("truly_passed", "").lower() == "true"
    unit_ok = unit_exit == "0"
    e2e_ok = e2e_exit == "0"

    verdict_html = (
        _verdict_row("DoD floor (after-beat gate)", "pass" if dod_pass else "fail", dod_pass)
        + _verdict_row(
            "Independent unit re-run",
            f"exit {unit_exit}",
            unit_ok,
            "npm test, clean process, shipped worktree",
        )
        + _verdict_row(
            "Independent e2e re-run",
            f"exit {e2e_exit}",
            e2e_ok,
            "npx playwright test, real browser",
        )
    )
    overall_cls = "ok" if truly else "warn"
    overall_txt = "TRULY PASSED" if truly else "NOT PROVEN"
    overall_sub = (
        "the shipped code passed the DoD floor AND both suites went green again under the harness's own hands"
        if truly
        else "a suite did not go green when re-run independently — a green transcript is not enough"
    )

    legend = "".join(
        f'<span class="leg">{_dot(t)}{lbl}</span>'
        for t, (lbl, _) in {
            "spawn_subagent": _TOOL_META["spawn_subagent"],
            "run_command": _TOOL_META["run_command"],
            "git": _TOOL_META["git"],
            "evidence_scan": _TOOL_META["evidence_scan"],
            "write_file": _TOOL_META["write_file"],
            "read_file": _TOOL_META["read_file"],
            "skill": _TOOL_META["skill"],
        }.items()
    )

    chips = [
        ("Total tool calls", str(total_calls)),
        ("Subagents spawned", str(sum(subs.values()))),
        ("run_command calls", str(run_calls)),
        ("skills loaded", str(counts.get("skill", 0))),
        ("Sprints", str(len(evals))),
    ]
    chip_html = "".join(f'<div class="chip"><span>{v}</span>{k}</div>' for k, v in chips)
    sub_html = "".join(
        f'<span class="subchip">{html.escape(name)} <b>&times;{n}</b></span>'
        for name, n in sorted(subs.items(), key=lambda kv: -kv[1])
    )

    # Artifacts: the manifest (the stack decision), the app + its source/components, both suites, the
    # evidence summary, and the re-run proof — globbed across whatever layout the chosen stack uses.
    src_exts = ("js", "mjs", "cjs", "ts", "mts", "jsx", "tsx", "vue", "svelte")
    art_parts: list[str] = []
    # the manifest first — it reveals the chosen stack, its dependencies, and the wired scripts.
    art_parts.append(
        _artifact_block(
            task_dir, "package.json", "package.json — the chosen stack + wired scripts", code=False
        )
    )
    # the app entry, if the stack has an HTML entry point.
    art_parts.append(_artifact_block(task_dir, "index.html", "index.html — the app entry"))
    # source modules / components (top-level + under src/ or app/), excluding config + test files.
    src_rels: list[str] = []
    for ext in src_exts:
        for pat in (f"src/**/*.{ext}", f"app/**/*.{ext}", f"*.{ext}"):
            src_rels += _sorted_rel(task_dir, pat)
    for rel in sorted(set(src_rels)):
        low = rel.lower()
        if (
            ".config." in low
            or ".test." in low
            or ".spec." in low
            or "/e2e/" in low
            or low.startswith("e2e/")
        ):
            continue
        art_parts.append(_artifact_block(task_dir, rel, f"{rel} — source"))
    # test suites wherever they live (tests/, test/, e2e/, or co-located *.test.* / *.spec.* under
    # src/). We classify each by CONTENT, not by folder: a spec that imports the neutral e2e harness
    # (Playwright) is an e2e spec; everything else is a unit/component test. That stays correct no
    # matter which layout the chosen stack happens to use.
    test_rels: list[str] = []
    for ext in src_exts:
        for pat in (
            f"tests/**/*.{ext}",
            f"test/**/*.{ext}",
            f"e2e/**/*.{ext}",
            f"src/**/*.test.{ext}",
            f"src/**/*.spec.{ext}",
        ):
            test_rels += _sorted_rel(task_dir, pat)
    for rel in sorted(set(test_rels)):
        body, _ = _read(task_dir, rel)
        is_e2e = (
            "@playwright/test" in body or "/e2e/" in rel.lower() or rel.lower().startswith("e2e/")
        )
        label = "e2e spec" if is_e2e else "unit test"
        art_parts.append(_artifact_block(task_dir, rel, f"{rel} — {label}"))
    # build + e2e config (any extension the stack uses).
    for rel in _sorted_rel(task_dir, "vite.config.*") + _sorted_rel(
        task_dir, "playwright.config.*"
    ):
        art_parts.append(_artifact_block(task_dir, rel, f"{rel} — config"))
    art_parts.append(
        _artifact_block(
            task_dir,
            "test_evidence/summary.md",
            "test_evidence/summary.md — the written proof (incl. the stack decision)",
            code=False,
        )
    )
    art_parts.append(
        _artifact_block(
            task_dir, "reverify_unit.txt", "reverify_unit.txt — the harness's OWN unit re-run"
        )
    )
    art_parts.append(
        _artifact_block(
            task_dir, "reverify_e2e.txt", "reverify_e2e.txt — the harness's OWN e2e re-run"
        )
    )
    artifacts_html = "".join(p for p in art_parts if p)

    eval_html = ""
    for e in evals:
        pct = max(0, min(100, round(e.score * 100)))
        badge = "ok" if e.outcome == "pass" else "warn"
        eval_html += (
            f'<div class="eval"><div class="eval-top">'
            f'<span class="badge {badge}">sprint {e.sprint}: {html.escape(e.outcome)}</span>'
            f'<span class="score">score {e.score:.2f}</span></div>'
            f'<div class="bar"><span style="width:{pct}%"></span></div>'
            f'<p class="notes">{html.escape(e.notes)}</p></div>'
        )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Frontend Engineer — Run Flow Report ({html.escape(key)})</title>
<style>
  :root {{
    --bg:#f6f8fa; --card:#ffffff; --ink:#1f2328; --muted:#57606a; --line:#d0d7de;
    --accent:#0d9488; --accent-soft:#ecfeff;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }}
  .wrap {{ max-width:960px; margin:0 auto; padding:32px 20px 80px; }}
  header.top {{ background:linear-gradient(135deg,#ecfeff,#f6f8fa); border:1px solid var(--line);
    border-radius:16px; padding:28px 28px 22px; margin-bottom:22px; }}
  header.top .eyebrow {{ color:var(--accent); font-weight:700; letter-spacing:.06em;
    text-transform:uppercase; font-size:12px; }}
  header.top h1 {{ margin:.2em 0 .3em; font-size:26px; }}
  header.top .intent {{ color:var(--muted); margin:0; }}
  header.top .intent b {{ color:var(--ink); }}
  .badge {{ font-size:12px; font-weight:700; padding:3px 10px; border-radius:999px; }}
  .badge.ok {{ background:#dcfce7; color:#166534; }}
  .badge.warn {{ background:#fef9c3; color:#854d0e; }}
  .badge.info {{ background:var(--accent-soft); color:#0e7490; }}
  .reverify {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
    padding:6px 20px 18px; margin:22px 0; }}
  .reverify h2 {{ font-size:13px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted);
    margin:16px 0 6px; }}
  .vrow {{ display:flex; align-items:center; gap:12px; padding:8px 0; border-bottom:1px dashed var(--line); }}
  .vrow:last-of-type {{ border-bottom:none; }}
  .vlabel {{ min-width:230px; font-weight:600; font-size:14px; }}
  .vrow .muted {{ color:var(--muted); font-size:12.5px; }}
  .overall {{ display:flex; align-items:center; gap:14px; margin-top:14px; padding:14px 16px;
    border-radius:12px; }}
  .overall.ok {{ background:#f0fdf4; border:1px solid #bbf7d0; }}
  .overall.warn {{ background:#fffbeb; border:1px solid #fde68a; }}
  .overall .big {{ font-size:18px; font-weight:800; letter-spacing:.02em; }}
  .overall.ok .big {{ color:#166534; }}
  .overall.warn .big {{ color:#854d0e; }}
  .overall p {{ margin:0; color:var(--muted); font-size:13px; }}
  .chips {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin:22px 0; }}
  .chip {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px;
    color:var(--muted); font-size:12.5px; }}
  .chip span {{ display:block; font-size:24px; font-weight:750; color:var(--ink); line-height:1.1; }}
  .subchips {{ display:flex; flex-wrap:wrap; gap:8px; margin:-6px 0 22px; }}
  .subchip {{ background:#f3e8ff; color:#6b21a8; border:1px solid #e9d5ff; border-radius:999px;
    padding:4px 12px; font-size:13px; }}
  h2.sec {{ font-size:15px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted);
    margin:34px 0 12px; }}
  .legend {{ display:flex; flex-wrap:wrap; gap:14px; margin-bottom:14px; font-size:12.5px; color:var(--muted); }}
  .leg {{ display:inline-flex; align-items:center; gap:6px; }}
  .dot {{ width:9px; height:9px; border-radius:50%; display:inline-block; flex:0 0 auto; }}
  .phase {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
    margin-bottom:16px; overflow:hidden; }}
  .phase-head {{ display:flex; gap:14px; align-items:flex-start; padding:18px 20px 14px;
    border-bottom:1px solid var(--line); background:#fbfcfe; }}
  .pnum {{ flex:0 0 auto; width:30px; height:30px; border-radius:50%; background:var(--accent);
    color:#fff; font-weight:750; display:grid; place-items:center; }}
  .phase-head h3 {{ margin:2px 0 3px; font-size:17px; }}
  .phase-head p {{ margin:0; color:var(--muted); font-size:13.5px; }}
  .phase-body {{ padding:12px 16px 16px; display:flex; flex-direction:column; gap:5px; }}
  .step {{ display:flex; align-items:center; gap:9px; padding:5px 8px; border-radius:8px; font-size:13.5px; }}
  .step:hover {{ background:#f6f8fa; }}
  .step .tool {{ font-weight:650; }}
  .step .arg {{ color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
    font:12.5px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }}
  .err {{ font-size:10.5px; font-weight:700; color:#b91c1c; background:#fee2e2; border-radius:5px;
    padding:1px 6px; }}
  details.sub {{ border:1px solid #e9d5ff; border-radius:10px; background:#faf5ff; margin:3px 0; }}
  details.sub > summary {{ cursor:pointer; list-style:none; padding:8px 12px; display:flex;
    align-items:center; gap:9px; font-size:13.5px; }}
  details.sub > summary::-webkit-details-marker {{ display:none; }}
  details.sub > summary::before {{ content:"▶"; font-size:9px; color:#a855f7; transition:transform .15s; }}
  details.sub[open] > summary::before {{ transform:rotate(90deg); }}
  details.sub .agent {{ font-weight:750; color:#6b21a8; }}
  details.sub .count {{ margin-left:auto; color:var(--muted); font-size:12px; }}
  .subbody {{ padding:2px 12px 12px 26px; display:flex; flex-direction:column; gap:3px;
    border-top:1px dashed #e9d5ff; }}
  .empty {{ color:var(--muted); font-size:13px; padding:6px; }}
  .eval {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px 18px;
    margin-bottom:12px; }}
  .eval-top {{ display:flex; align-items:center; gap:12px; }}
  .eval-top .score {{ margin-left:auto; color:var(--muted); font-size:13px; }}
  .bar {{ height:8px; background:#eaeef2; border-radius:999px; margin:10px 0 8px; overflow:hidden; }}
  .bar span {{ display:block; height:100%; background:linear-gradient(90deg,#14b8a6,#0d9488); }}
  .notes {{ margin:0; color:var(--muted); font-size:13px; }}
  details.art {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
    margin-bottom:12px; }}
  details.art > summary {{ cursor:pointer; padding:14px 18px; font-weight:650; }}
  details.art pre {{ margin:0; padding:0 18px 18px; white-space:pre-wrap; word-wrap:break-word;
    font:12.5px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; color:#24292f; }}
  .note {{ background:#fffbeb; border:1px solid #fde68a; border-radius:12px; padding:14px 18px;
    color:#854d0e; font-size:13.5px; margin-top:8px; }}
  footer {{ color:var(--muted); font-size:12px; text-align:center; margin-top:40px; }}
</style></head>
<body><div class="wrap">

<header class="top">
  <div class="eyebrow">Chorus · Frontend Engineer (Finn) · task &ldquo;{html.escape(key)}&rdquo;</div>
  <h1>Run Flow Report</h1>
  <p class="intent"><b>Intent:</b> {html.escape(intent)}</p>
</header>

<div class="reverify">
  <h2>Independent verification — did the shipped code actually work?</h2>
  {verdict_html}
  <div class="overall {overall_cls}"><span class="big">{overall_txt}</span><p>{overall_sub}</p></div>
</div>

<div class="chips">{chip_html}</div>
<div class="subchips">{sub_html}</div>

<h2 class="sec">The flow, phase by phase</h2>
<div class="legend">{legend}</div>
{render_phases(nodes)}

<h2 class="sec">Sprint evaluations</h2>
{eval_html or '<div class="empty">— no sprint verdicts recorded —</div>'}

<h2 class="sec">Artifacts produced</h2>
{artifacts_html}

<div class="note"><b>Reading the errors:</b> most <span class="err">err</span> markers are benign — the
model retrying a <code>read_file</code> against an offloaded scratch path, a reviewer probing a file
that doesn't exist, or the DoD oracle's Windows-only floor probe. The engineering flow itself completed:
size → build → unit + e2e tests → run &amp; capture → review under pressure. The verdict box at the top
is the honest answer: it re-runs the shipped suites in a clean process.</div>

<footer>Generated from reports/frontend-engineer-artifacts/{html.escape(key)}/flow.log — Frontend Engineer beat, model gpt-5.2 (Azure). Press E to expand all, C to collapse subagents.</footer>
</div>

<script>
  document.addEventListener('keydown', e => {{
    if (e.key === 'e' || e.key === 'E') document.querySelectorAll('details').forEach(d => d.open = true);
    if (e.key === 'c' || e.key === 'C') document.querySelectorAll('details.sub').forEach(d => d.open = false);
  }});
</script>
</body></html>
"""


def write_report_for_task(task_dir: Path) -> Path:
    """Build ``<task_dir>/flow-report.html`` from the captured ``flow.log`` + artifacts. Returns the path."""
    out = task_dir / "flow-report.html"
    out.write_text(build_html(task_dir), encoding="utf-8")
    return out


def main() -> int:
    if not _ART_ROOT.is_dir():
        print(f"no artifacts dir yet: {_ART_ROOT}")
        return 0
    wanted = {a.strip() for a in sys.argv[1:] if a.strip()}
    dirs = sorted(d for d in _ART_ROOT.iterdir() if d.is_dir() and (d / "flow.log").is_file())
    dirs = [d for d in dirs if not wanted or d.name in wanted]
    if not dirs:
        print(
            f"no task dirs with a flow.log under {_ART_ROOT}"
            + (f" matching {sorted(wanted)}" if wanted else "")
        )
        return 0
    for d in dirs:
        out = write_report_for_task(d)
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
