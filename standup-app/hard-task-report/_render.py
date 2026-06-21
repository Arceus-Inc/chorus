"""Render probe.json files → per-task <name>.html + a holistic index.html (grpo.html aesthetic).

Usage:
  python _render.py one <run_home>     # render standup-app/hard-task-report/<name>.html
  python _render.py index              # aggregate every runs/*/probe.json → index.html
"""
from __future__ import annotations

import contextlib
import html
import json
import sys
from pathlib import Path

ROOT = Path("standup-app/hard-task-report")
RUNS = ROOT / "runs"

SEV = {
    "CRITICAL": ("crit", "var(--red)"),
    "HIGH": ("crit", "var(--red)"),
    "FRAMEWORK": ("fwk", "var(--amber)"),
    "INFO": ("info", "var(--muted)"),
}

CSS = """
:root{--bg:#0d1117;--panel:#161b22;--panel2:#1c2330;--border:#30363d;--fg:#e6edf3;--muted:#8b949e;
--accent:#58a6ff;--mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;--red:#f85149;
--redbg:#2d1518;--amber:#d29922;--amberbg:#2a230f;--green:#3fb950;--greenbg:#12261a;--purple:#bc8cff;}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased}
.wrap{max-width:980px;margin:0 auto;padding:48px 24px 96px}
header{border-bottom:1px solid var(--border);padding-bottom:28px;margin-bottom:36px}
.eyebrow{font:600 12px/1 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--accent)}
h1{margin:14px 0 8px;font-size:30px;letter-spacing:-.02em}
.sub{color:var(--muted);font-size:15px;max-width:74ch}
.meta{display:flex;flex-wrap:wrap;gap:10px;margin-top:20px}
.chip{font:600 12px/1 var(--mono);color:var(--muted);background:var(--panel);border:1px solid var(--border);
border-radius:999px;padding:7px 12px}.chip b{color:var(--fg)}
.ok{color:var(--green)}.bad{color:var(--red)}.warn{color:var(--amber)}
h2{font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin:44px 0 18px;
padding-bottom:10px;border-bottom:1px solid var(--border)}
.card{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:18px 20px;margin:12px 0;
position:relative;overflow:hidden}.card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--red)}
.card.fwk::before{background:var(--amber)}.card.info::before{background:var(--muted)}
.card-head{display:flex;align-items:baseline;gap:12px;margin-bottom:6px}
.code{flex:none;font:700 11px/1 var(--mono);color:var(--bg);background:var(--red);border-radius:6px;padding:5px 8px}
.card.fwk .code{background:var(--amber)}.card.info .code{background:var(--muted)}
.title{font-size:15px;font-weight:650}
.detail{color:#c2ccd6;font-size:13.5px;margin-top:4px;font-family:var(--mono);white-space:pre-wrap;word-break:break-word}
table{border-collapse:collapse;width:100%;margin:10px 0;font-size:13.5px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--border)}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.06em}
td code,code.k{font:12.5px/1.5 var(--mono);background:var(--panel2);border:1px solid var(--border);border-radius:5px;
padding:1px 6px;color:#d2a8ff}
.pill{display:inline-block;font:600 11px/1 var(--mono);border-radius:5px;padding:4px 8px}
.pill.done{color:var(--green);background:var(--greenbg);border:1px solid #1c5a32}
.pill.blocked,.pill.rejected{color:var(--red);background:var(--redbg);border:1px solid #5c2326}
.pill.other{color:var(--amber);background:var(--amberbg);border:1px solid #5a4818}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin:8px 0}
.stat{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:14px}
.stat .n{font-size:22px;font-weight:700}.stat .l{color:var(--muted);font-size:12px;margin-top:2px}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
footer{margin-top:56px;padding-top:22px;border-top:1px solid var(--border);color:var(--muted);font-size:13px}
pre.log{background:#0b0f14;border:1px solid var(--border);border-radius:8px;padding:12px;overflow:auto;
font:12px/1.5 var(--mono);color:#9db1c5;max-height:240px}
"""


def esc(x) -> str:
    return html.escape(str(x))


def pill(status: str) -> str:
    cls = status if status in ("done", "blocked", "rejected") else "other"
    return f'<span class="pill {cls}">{esc(status)}</span>'


def render_one(home: Path) -> Path:
    p = json.loads((home / "probe.json").read_text())
    name, lang = p["name"], p["lang"]
    led, rep, bld, flaws = p["ledger"], p["repo"], p["build"], p["flaws"]
    meta = p["meta"]
    sc = led.get("status_counts", {}) if isinstance(led, dict) else {}
    top = led.get("top_status")
    crit = sum(1 for f in flaws if f["sev"] in ("CRITICAL", "HIGH", "INFO"))
    fwk = sum(1 for f in flaws if f["sev"] == "FRAMEWORK")

    def _cards(items: list, start: int = 1, force_cls: str = "") -> str:
        out = []
        for i, f in enumerate(items, start):
            cls = force_cls or SEV.get(f.get("sev", "CRITICAL"), ("crit", ""))[0]
            out.append(
                f'<div class="card {cls}"><div class="card-head">'
                f'<span class="code">{i}</span>'
                f'<span class="title">{esc(f["title"])}</span>'
                f'<span style="margin-left:auto;font:600 10px/1 var(--mono);color:var(--muted)">{esc(f.get("code",""))}</span>'
                f'</div><div class="detail">{esc(f["detail"])}</div></div>'
            )
        return "\n".join(out)

    # grpo.html structure: A = deliverable defects, B = chorus orchestration behaviours.
    # Prefer a hand-authored findings.json (deep file-level dissection); fall back to auto-probe flaws.
    fpath = home / "findings.json"
    if fpath.exists():
        cur = json.loads(fpath.read_text())
        deliverable, framework = cur.get("deliverable", []), cur.get("framework", [])
    else:
        deliverable = [f for f in flaws if f["sev"] in ("CRITICAL", "HIGH", "INFO")]
        framework = [f for f in flaws if f["sev"] == "FRAMEWORK"]
    none_card = ('<div class="card info"><div class="card-head"><span class="code">—</span>'
                 '<span class="title">none found</span></div></div>')
    deliverable_cards = _cards(deliverable) or none_card
    framework_cards = _cards(framework, len(deliverable) + 1, force_cls="fwk") or none_card
    crit, fwk = len(deliverable), len(framework)

    status_rows = "".join(f"<td>{pill(k)} <b>{v}</b></td>" for k, v in sorted(sc.items()))

    def _verdict(rc: int) -> str:
        if rc == 0:
            return '<span class="ok">pass</span>'
        if rc == 127:
            return '<span class="warn">toolchain n/a</span>'
        if rc == 124:
            return '<span class="bad">timeout</span>'
        return f'<span class="bad">fail (rc={rc})</span>'

    _battempts = bld.get("attempts", []) if isinstance(bld, dict) else []
    build_rows = "\n".join(
        f'<tr><td><code>{esc(a["cmd"])}</code></td><td>{_verdict(a["rc"])}</td>'
        f'<td class="detail">{esc((a.get("tail") or "")[-220:])}</td></tr>'
        for a in _battempts
    ) or '<tr><td colspan="3" class="detail">no build attempted</td></tr>'

    files = rep.get("files", []) if isinstance(rep, dict) else []
    file_list = "".join(f"<code class=k>{esc(f)}</code> " for f in files[:60]) or "<i>(empty)</i>"
    log_txt = "\n".join(rep.get("log", [])) if isinstance(rep, dict) else ""

    doc = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{esc(name)} — Hard-Task Report</title><style>{CSS}</style></head><body><div class="wrap">
<header><div class="eyebrow">Hard-Task Report · {esc(lang)}</div>
<h1><code class="k" style="font-size:26px;color:var(--fg)">{esc(name)}</code></h1>
<p class="sub">{esc(p.get("brief",""))}</p>
<div class="meta">
<span class="chip">goal: {'<b class=ok>done</b>' if top=='done' else f'<b class=bad>{esc(top)}</b>'}</span>
<span class="chip">tasks: <b>{led.get('n_tasks','?')}</b></span>
<span class="chip">runs: <b>{led.get('n_runs','?')}</b></span>
<span class="chip">elapsed: <b>{meta.get('elapsed_s','?')}s</b></span>
<span class="chip">deliverable flaws: <b class=bad>{crit}</b></span>
<span class="chip">framework flaws: <b class=warn>{fwk}</b></span>
</div></header>

<h2>Run accounting</h2>
<table><tr><th>top goal</th><td>{pill(top) if top else '—'}</td></tr>
<tr><th>task statuses</th><tr>{status_rows or '<td>—</td>'}</tr></table>
<div class="grid">
<div class="stat"><div class="n">{len(led.get('employees',[])) if isinstance(led,dict) else '?'}</div><div class="l">employees</div></div>
<div class="stat"><div class="n">{rep.get('n_files','?') if isinstance(rep,dict) else '?'}</div><div class="l">files landed</div></div>
<div class="stat"><div class="n">{len(rep.get('merges',[])) if isinstance(rep,dict) else '?'}</div><div class="l">merges on main</div></div>
<div class="stat"><div class="n">{len(rep.get('duplicates',{})) if isinstance(rep,dict) else '?'}</div><div class="l">duplicate modules</div></div>
</div>

<h2>Build / test verification</h2>
<table><tr><th>command</th><th>result</th><th>output tail</th></tr>{build_rows}</table>

<h2><span style="color:var(--accent)">A.</span> Deliverable flaws — the <code class="k">{esc(name)}</code> deliverable ({len(deliverable)})</h2>
<p class="detail" style="font-family:inherit;color:var(--muted)">Defects in what the org actually produced — is it a real, usable, distributable artifact?</p>
{deliverable_cards}

<h2><span style="color:var(--accent)">B.</span> Framework / orchestration flaws — chorus behaviours this run exposed ({len(framework)})</h2>
<p class="detail" style="font-family:inherit;color:var(--muted)">Not the deliverable's fault — kernel/orchestration behaviours the run made visible.</p>
{framework_cards}

<h2>Landed repo</h2>
<p class="detail" style="font-family:inherit">Packaging expected: {esc(rep.get('packaging_expected','?') if isinstance(rep,dict) else '?')} ·
present: {esc(rep.get('packaging_present','?') if isinstance(rep,dict) else '?')}</p>
<p style="margin:10px 0">{file_list}</p>
<h2>git log (company main)</h2>
<pre class="log">{esc(log_txt) or '(nothing landed)'}</pre>

<footer>Generated by <code class="k">_probe.py</code> + <code class="k">_render.py</code> from a live
<code class="k">Chorus.build --org</code> run. Workspace: <code class="k">{esc(meta.get('workspace',''))}</code>.
Flaw codes cross-reference <a href="../post-dev-wiring.md">post-dev-wiring.md</a> (BUG-005/006/007).</footer>
</div></body></html>"""
    out = ROOT / f"{name}.html"
    out.write_text(doc)
    return out


def render_index() -> Path:
    probes = []
    for d in sorted(RUNS.glob("*/probe.json")):
        with contextlib.suppress(Exception):
            probes.append(json.loads(d.read_text()))
    rows = []
    tot_crit = tot_fwk = done_n = 0
    for p in probes:
        led = p["ledger"] if isinstance(p["ledger"], dict) else {}
        top = led.get("top_status")
        crit = sum(1 for f in p["flaws"] if f["sev"] in ("CRITICAL", "HIGH"))
        fwk = sum(1 for f in p["flaws"] if f["sev"] == "FRAMEWORK")
        tot_crit += crit
        tot_fwk += fwk
        done_n += 1 if top == "done" else 0
        rep = p["repo"] if isinstance(p["repo"], dict) else {}
        rows.append(
            f'<tr><td><a href="{esc(p["name"])}.html"><code class="k">{esc(p["name"])}</code></a></td>'
            f'<td>{esc(p["lang"])}</td><td>{pill(top) if top else "—"}</td>'
            f'<td>{rep.get("n_files","?")}</td>'
            f'<td class="bad">{crit}</td><td class="warn">{fwk}</td>'
            f'<td>{p["meta"].get("elapsed_s","?")}s</td></tr>'
        )
    body = "\n".join(rows) or '<tr><td colspan="7">no runs probed yet</td></tr>'
    doc = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Hard Tasks — Holistic Report</title><style>{CSS}</style></head><body><div class="wrap">
<header><div class="eyebrow">Hard-Task Org Stress · Holistic Report</div>
<h1>15 hard goals through <code class="k" style="font-size:24px;color:var(--fg)">Chorus.build --org</code></h1>
<p class="sub">Each goal was driven end-to-end by a live 3-level org (director → leads → engineers + reviewer).
Every run was deep-probed: ledger accounting, the landed repo's shape, an actual build/test of the
deliverable, and the recurring framework failure modes. One row per goal — click through for the full dissection.</p>
<div class="grid">
<div class="stat"><div class="n">{len(probes)}/15</div><div class="l">runs probed</div></div>
<div class="stat"><div class="n {'ok' if done_n else 'bad'}">{done_n}</div><div class="l">closed <code>done</code></div></div>
<div class="stat"><div class="n bad">{tot_crit}</div><div class="l">deliverable flaws</div></div>
<div class="stat"><div class="n warn">{tot_fwk}</div><div class="l">framework flaws</div></div>
</div></header>
<h2>Per-goal results</h2>
<table><tr><th>goal</th><th>lang</th><th>top status</th><th>files</th><th>deliv. flaws</th><th>fwk flaws</th><th>elapsed</th></tr>
{body}</table>
<footer>Holistic view; see <a href="../HARD_TASKS.md">HARD_TASKS.md</a> for the briefs and
<a href="grpo.html">grpo.html</a> for the original probe that seeded this catalogue.</footer>
</div></body></html>"""
    out = ROOT / "index.html"
    out.write_text(doc)
    return out


def main() -> int:
    if sys.argv[1] == "one":
        print("wrote", render_one(Path(sys.argv[2])))
    else:
        print("wrote", render_index())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
