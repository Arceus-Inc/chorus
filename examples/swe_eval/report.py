"""Aggregate the run into a console summary, a machine-readable ``results.jsonl``, and an HTML report."""

from __future__ import annotations

import html
import json
from pathlib import Path

from swe_eval.case import BenchCase, CandidateSolution, EvalResult


def print_summary(results: list[EvalResult]) -> None:
    """Print a compact console verdict table + the headline resolved rate."""
    print("\n" + "=" * 92)
    print("SWE-EVAL — RESOLVED VERDICT")
    print("=" * 92)
    print(f"{'case':<40} {'role via':<10} {'method':<10} {'resolved':<9} {'detail'}")
    print("-" * 92)
    for r in results:
        print(
            f"{r.case_id[:39]:<40} "
            f"{'':<10}"
            f"{r.method:<10} "
            f"{('YES' if r.resolved else 'no'):<9} "
            f"{r.detail[:30]}"
        )
    resolved = sum(1 for r in results if r.resolved)
    print("-" * 92)
    rate = (resolved / len(results) * 100) if results else 0.0
    print(f"RESOLVED {resolved}/{len(results)}  ({rate:.1f}%)")


def write_results_jsonl(results: list[EvalResult], dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(json.dumps(r.to_dict()) for r in results) + "\n", encoding="utf-8")
    return dest


def write_html_report(
    cases: dict[str, BenchCase],
    candidates: dict[str, CandidateSolution],
    results: list[EvalResult],
    dest: Path,
) -> Path:
    """Render a self-contained HTML report (light theme, matching the flow-report aesthetic)."""
    resolved = sum(1 for r in results if r.resolved)
    total = len(results)
    rate = (resolved / total * 100) if total else 0.0
    by_method: dict[str, int] = {}
    for r in results:
        by_method[r.method] = by_method.get(r.method, 0) + 1

    rows = []
    for r in results:
        c = cases.get(r.case_id)
        cand = candidates.get(r.case_id)
        badge = "ok" if r.resolved else "warn"
        method_detail = (
            f"FAIL_TO_PASS {r.fail_to_pass_passed}/{r.fail_to_pass_total}"
            if r.method == "objective"
            else (f"{r.judge_verdict} · score {r.judge_score:.2f}" if r.judge_score is not None else r.judge_verdict)
        )
        rows.append(
            "<tr>"
            f"<td class='mono'>{html.escape(r.case_id)}</td>"
            f"<td>{html.escape(c.role if c else '')}</td>"
            f"<td>{html.escape(c.language if c else '')}</td>"
            f"<td><span class='badge {badge}'>{'RESOLVED' if r.resolved else 'unresolved'}</span></td>"
            f"<td>{html.escape(r.method)}</td>"
            f"<td class='mono'>{html.escape(method_detail)}</td>"
            f"<td>{r.files_overlap:.0%}</td>"
            f"<td>{'yes' if (cand and cand.produced_diff) else 'no'}</td>"
            f"<td class='muted'>{html.escape(r.detail[:120])}</td>"
            "</tr>"
        )

    method_chips = "".join(
        f"<div class='chip'><span>{n}</span>{html.escape(m)}</div>" for m, n in sorted(by_method.items())
    )
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SWE-Eval Report</title>
<style>
 :root {{ --bg:#f6f8fa; --card:#fff; --ink:#1f2328; --muted:#57606a; --line:#d0d7de; --accent:#0d9488; }}
 * {{ box-sizing:border-box; }}
 body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif; }}
 .wrap {{ max-width:1040px; margin:0 auto; padding:32px 20px 80px; }}
 header.top {{ background:linear-gradient(135deg,#ecfeff,#f6f8fa); border:1px solid var(--line); border-radius:16px; padding:26px 26px 20px; margin-bottom:20px; }}
 .eyebrow {{ color:var(--accent); font-weight:700; letter-spacing:.06em; text-transform:uppercase; font-size:12px; }}
 h1 {{ margin:.2em 0 .3em; font-size:25px; }}
 .sub {{ color:var(--muted); margin:0; }}
 .overall {{ display:flex; align-items:center; gap:14px; margin:20px 0; padding:16px 18px; border-radius:12px; background:#f0fdf4; border:1px solid #bbf7d0; }}
 .overall .big {{ font-size:22px; font-weight:800; color:#166534; }}
 .overall p {{ margin:0; color:var(--muted); font-size:13.5px; }}
 .chips {{ display:flex; flex-wrap:wrap; gap:12px; margin:16px 0; }}
 .chip {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px 16px; color:var(--muted); font-size:12.5px; }}
 .chip span {{ display:block; font-size:22px; font-weight:750; color:var(--ink); }}
 table {{ width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:12px; overflow:hidden; }}
 th, td {{ text-align:left; padding:10px 12px; border-bottom:1px solid var(--line); font-size:13px; vertical-align:top; }}
 th {{ background:#fbfcfe; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; font-size:11px; }}
 tr:last-child td {{ border-bottom:none; }}
 .mono {{ font:12px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }}
 .muted {{ color:var(--muted); }}
 .badge {{ font-size:11.5px; font-weight:700; padding:2px 9px; border-radius:999px; }}
 .badge.ok {{ background:#dcfce7; color:#166534; }}
 .badge.warn {{ background:#fef9c3; color:#854d0e; }}
 footer {{ color:var(--muted); font-size:12px; text-align:center; margin-top:34px; }}
</style></head><body><div class="wrap">
<header class="top">
 <div class="eyebrow">Chorus · SWE-Eval · code-employee benchmark</div>
 <h1>Issue-to-fix benchmark report</h1>
 <p class="sub">Each case clones a repo at the commit before a human PR, submits the issue as the task, and scores the employee's candidate fix against the human PR (objective test-patch where available, else an LLM judge).</p>
</header>
<div class="overall"><span class="big">{resolved}/{total} resolved</span><p>{rate:.1f}% of cases genuinely fixed · methods: {html.escape(", ".join(f"{m}×{n}" for m, n in sorted(by_method.items())))}</p></div>
<div class="chips">{method_chips}</div>
<table>
 <thead><tr><th>case</th><th>role</th><th>lang</th><th>verdict</th><th>method</th><th>oracle detail</th><th>file overlap</th><th>diff?</th><th>notes</th></tr></thead>
 <tbody>{"".join(rows)}</tbody>
</table>
<footer>Chorus · SWE-Eval — generated from an issue→fix benchmark run.</footer>
</div></body></html>"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(doc, encoding="utf-8")
    return dest
