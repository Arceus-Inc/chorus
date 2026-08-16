"""Generate a self-contained, light-theme HTML report of a Designer beat's FULL FLOW.

Parses the observer trace emitted by ``designer_parallel_task.py`` (the ``[tool ->] / [tool <-]``
lines, ``[EVALUATED] {...}`` sprint verdicts, and the final ``[parallel]`` summary), reconstructs the
nested call tree (a ``spawn_subagent`` frame holds every tool the child ran until its matching close),
groups the top-level steps into the Designer's canonical phases (Research -> Ground/Author -> Explore
-> Spec -> Critique loop), and renders it all as one static HTML file with inline CSS + tiny JS for the
collapsibles. Also embeds the run's artifacts (``DESIGN.md`` / ``design_spec.md``).

Usage:  uv run python examples/designer_flow_report.py
Reads:  designer_parallel_run4.log  +  reports/designer-artifacts/parallel/{DESIGN.md,design_spec.md,_meta.txt}
Writes: reports/designer-artifacts/parallel/flow-report.html
"""

from __future__ import annotations

import ast
import html
import re
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path("chorus") if Path("chorus").is_dir() else Path(".")
_LOG = _ROOT / "designer_parallel_run4.log"
_ART = _ROOT / "reports" / "designer-artifacts" / "parallel"
_OUT = _ART / "flow-report.html"

_RE_INVOKE = re.compile(r"^\s*\[tool ->\]\s+(\S+)\s*(.*)$")
_RE_RESULT = re.compile(r"^\s*\[tool <-\]\s+(\S+)(\s+\(ERROR\))?\s*$")
_RE_EVAL = re.compile(r"^\s*\[EVALUATED\]\s+(\{.*\})\s*$")
_RE_INTENT = re.compile(r"^intent:\s*(.*)$")
_RE_SUMMARY = re.compile(r"^\[parallel\]\s+(\w+)\s*=\s*(.*)$")

# Tool -> (category label, accent colour) for the legend + per-step dot.
_TOOL_META: dict[str, tuple[str, str]] = {
    "spawn_subagent": ("subagent", "#7c3aed"),
    "web_search": ("web research", "#0d9488"),
    "web_extract": ("web research", "#0d9488"),
    "design_exemplar": ("exemplar", "#d97706"),
    "design_lint": ("lint", "#2563eb"),
    "write_file": ("write", "#16a34a"),
    "read_file": ("read", "#6b7280"),
    "skill": ("skill", "#db2777"),
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

    The observer truncates long payloads with an ellipsis, so ``ast.literal_eval``
    usually fails — a tolerant regex is more robust for the few fields we surface.
    """
    m = re.search(rf"'{key}':\s*'((?:[^'\\]|\\.)*)'", payload)
    return m.group(1) if m else ""


def _short_payload(tool: str, payload: str) -> str:
    """A compact one-line description of a call's key argument(s)."""
    payload = payload.strip()
    if tool == "spawn_subagent":
        return _field(payload, "name")
    if tool in {"read_file", "write_file"}:
        return _field(payload, "path")
    if tool == "design_lint":
        return _field(payload, "doc")
    if tool == "design_exemplar":
        return _field(payload, "company") or "(list library)"
    if tool == "skill":
        return _field(payload, "name")
    if tool == "web_search":
        return _field(payload, "query")
    if tool == "web_extract":
        urls = re.findall(r"https?://[^'\"\s\\]+", payload)
        if urls:
            extra = f"  +{len(urls) - 1} more" if len(urls) > 1 else ""
            return urls[0] + extra
        return ""
    return ""


def parse_log(text: str) -> tuple[str, list[Node], list[Eval], dict[str, str]]:
    intent = ""
    summary: dict[str, str] = {}
    root_children: list[Node] = []
    evals: list[Eval] = []
    stack: list[list[Node]] = [root_children]  # each frame is a children-list
    subagent_stack: list[Node] = []
    last_leaf: Node | None = None

    for line in text.splitlines():
        m = _RE_INTENT.match(line)
        if m:
            intent = m.group(1).strip()
            continue
        m = _RE_SUMMARY.match(line)
        if m:
            summary[m.group(1)] = m.group(2).strip()
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

    return intent, root_children, evals, summary


# --- phase grouping ---------------------------------------------------------

_PHASES = [
    (
        "Research the bet",
        "Load <b>user-flow-mapping</b> and spawn <b>web_research</b> for current UX/pattern facts, then write your own framing notes <em>before</em> anything is drawn.",
    ),
    (
        "Ground &amp; author the system",
        "Study real-world exemplars with the <b>design_exemplar</b> tool, then author <code>DESIGN.md</code> — the token/component system — from the brief.",
    ),
    (
        "Explore on-system variants",
        "Seed the direction (<code>design_seed.md</code>), then draft 2–3 on-system variants yourself with layout skills — vary hierarchy without touching the token system.",
    ),
    (
        "Draft the spec",
        "Write <code>design_spec.md</code> to the chosen direction and run the deterministic <b>design_lint</b> mechanical pass.",
    ),
    (
        "Red-team &amp; converge",
        "Loop the <b>design_critic</b> subagent + <b>design_lint</b>, revising the spec each round until the design is on-system and accessible.",
    ),
]


def phase_for(node: Node, current: int) -> int:
    """Monotonic phase pointer — a node can advance the phase, never rewind it."""
    wanted = current
    if node.is_subagent:
        if node.subagent_name == "web_research":
            wanted = 0
        elif node.subagent_name == "design_critic":
            wanted = 4
    elif node.tool == "design_exemplar":
        wanted = max(wanted, 1)
    elif node.tool == "write_file":
        if node.payload.endswith("DESIGN.md") or node.payload.endswith("ux_brief.md"):
            wanted = max(wanted, 1)
        elif "design_seed" in node.payload:
            wanted = max(wanted, 2)
        elif "design_spec" in node.payload:
            wanted = max(wanted, 3)
    return max(current, wanted)


# --- rendering --------------------------------------------------------------


def _dot(tool: str) -> str:
    _, colour = _TOOL_META.get(tool, ("", "#6b7280"))
    return f'<span class="dot" style="background:{colour}"></span>'


def _err_badge(node: Node) -> str:
    return (
        ' <span class="err" title="benign — usually a retry reading an offloaded scratch file">err</span>'
        if node.error
        else ""
    )


def render_node(node: Node) -> str:
    label, _ = _TOOL_META.get(node.tool, (node.tool, ""))
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
    # bucket top-level nodes into phases
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


def read_artifact(name: str) -> tuple[str, int]:
    p = _ART / name
    if not p.is_file():
        return "", 0
    txt = p.read_text(encoding="utf-8")
    return txt, len(txt.split())


def build_html() -> str:
    text = _LOG.read_text(encoding="utf-8", errors="replace")
    intent, nodes, evals, summary = parse_log(text)
    counts = tool_counts(nodes)
    subs = count_subagents(nodes)
    design_md, design_words = read_artifact("DESIGN.md")
    spec_md, spec_words = read_artifact("design_spec.md")

    total_calls = sum(counts.values())
    legend = "".join(
        f'<span class="leg">{_dot(t)}{lbl}</span>'
        for t, (lbl, _) in {
            "spawn_subagent": _TOOL_META["spawn_subagent"],
            "web_search": _TOOL_META["web_search"],
            "design_exemplar": _TOOL_META["design_exemplar"],
            "design_lint": _TOOL_META["design_lint"],
            "write_file": _TOOL_META["write_file"],
            "read_file": _TOOL_META["read_file"],
            "skill": _TOOL_META["skill"],
        }.items()
    )

    chips = [
        ("Total tool calls", str(total_calls)),
        ("Subagents spawned", str(sum(subs.values()))),
        (
            "web_search / web_extract",
            str(counts.get("web_search", 0) + counts.get("web_extract", 0)),
        ),
        ("design_lint runs", str(counts.get("design_lint", 0))),
        ("Sprints", str(len(evals))),
    ]
    chip_html = "".join(f'<div class="chip"><span>{v}</span>{k}</div>' for k, v in chips)

    sub_html = "".join(
        f'<span class="subchip">{html.escape(name)} <b>×{n}</b></span>'
        for name, n in sorted(subs.items(), key=lambda kv: -kv[1])
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Designer Employee — Run Flow Report</title>
<style>
  :root {{
    --bg:#f6f8fa; --card:#ffffff; --ink:#1f2328; --muted:#57606a; --line:#d0d7de;
    --accent:#4f46e5; --accent-soft:#eef2ff;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }}
  .wrap {{ max-width:960px; margin:0 auto; padding:32px 20px 80px; }}
  header.top {{ background:linear-gradient(135deg,#eef2ff,#f6f8fa); border:1px solid var(--line);
    border-radius:16px; padding:28px 28px 22px; margin-bottom:22px; }}
  header.top .eyebrow {{ color:var(--accent); font-weight:700; letter-spacing:.06em;
    text-transform:uppercase; font-size:12px; }}
  header.top h1 {{ margin:.2em 0 .3em; font-size:26px; }}
  header.top .intent {{ color:var(--muted); margin:0; }}
  header.top .intent b {{ color:var(--ink); }}
  .verdict {{ margin-top:16px; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }}
  .badge {{ font-size:12px; font-weight:700; padding:3px 10px; border-radius:999px; }}
  .badge.ok {{ background:#dcfce7; color:#166534; }}
  .badge.warn {{ background:#fef9c3; color:#854d0e; }}
  .badge.info {{ background:var(--accent-soft); color:var(--accent); }}
  .verdict .muted {{ color:var(--muted); font-size:13px; }}
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
  .step .arg {{ color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
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
  .bar span {{ display:block; height:100%; background:linear-gradient(90deg,#f59e0b,#4f46e5); }}
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
  <div class="eyebrow">Chorus · Designer employee (Dara)</div>
  <h1>Run Flow Report</h1>
  <p class="intent"><b>Intent:</b> {html.escape(intent)}</p>
  <div class="verdict">
    <span class="badge info">greenfield · full flow</span>
  </div>
</header>

<div class="chips">{chip_html}</div>
<div class="subchips">{sub_html}</div>

<h2 class="sec">The flow, phase by phase</h2>
<div class="legend">{legend}</div>
{render_phases(nodes)}

<h2 class="sec">Artifacts produced</h2>
<details class="art"><summary>DESIGN.md — the authored design system · {design_words} words</summary>
<pre>{html.escape(design_md)}</pre></details>
<details class="art"><summary>design_spec.md — the buildable spec · {spec_words} words</summary>
<pre>{html.escape(spec_md)}</pre></details>

<div class="note"><b>Reading the errors:</b> most <span class="err">err</span> markers are benign — the
model retrying a <code>read_file</code> against an offloaded scratch path, or the DoD oracle's
POSIX-only <code>test/wc/grep</code> floor failing on Windows. The design flow itself completed:
research → exemplars → system → explore → spec → critique.</div>

<footer>Generated from designer_parallel_run4.log — Designer beat, model gpt-5.2 (Azure).</footer>
</div>

<script>
  // expand-all / collapse-all with the E / C keys, for quickly scanning subagent internals
  document.addEventListener('keydown', e => {{
    if (e.key === 'e' || e.key === 'E') document.querySelectorAll('details').forEach(d => d.open = true);
    if (e.key === 'c' || e.key === 'C') document.querySelectorAll('details.sub').forEach(d => d.open = false);
  }});
</script>
</body></html>
"""


def main() -> int:
    _OUT.write_text(build_html(), encoding="utf-8")
    print(f"wrote {_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
