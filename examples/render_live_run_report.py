"""Render the latest T1/T2/T3 Markdown reports as one self-contained HTML dashboard."""

from __future__ import annotations

import argparse
import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final


@dataclass(frozen=True)
class Invariant:
    check: str
    result: str
    evidence: str


@dataclass(frozen=True)
class RunReport:
    label: str
    title: str
    result: str
    model: str
    run_directory: str
    scope: str
    source_path: Path
    markdown: str
    invariants: tuple[Invariant, ...]

    @property
    def passed(self) -> bool:
        return self.result.upper() == "PASS"


_REPORT_FILES: Final = (
    ("T1", Path("t1-live-runs/T1-latest.md")),
    ("T2", Path("t2-live-runs/T2-latest.md")),
    ("T3", Path("t3-live-runs/T3-latest.md")),
)


def _bold_value(markdown: str, label: str) -> str:
    match = re.search(rf"^\*\*{re.escape(label)}:\*\*\s*(.+?)\s*$", markdown, re.MULTILINE)
    return match.group(1).strip().strip("`") if match else "Not recorded"


def _invariants(markdown: str) -> tuple[Invariant, ...]:
    match = re.search(r"^## Invariants\s*$", markdown, re.MULTILINE)
    if match is None:
        return ()
    rows: list[Invariant] = []
    for line in markdown[match.end() :].splitlines():
        if line.startswith("## "):
            break
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|", 2)]
        if len(cells) != 3 or cells[0] in {"Check", "---"} or set(cells[0]) == {"-"}:
            continue
        rows.append(Invariant(*cells))
    return tuple(rows)


def parse_report(label: str, source_path: Path) -> RunReport:
    markdown = source_path.read_text(encoding="utf-8")
    title_match = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
    return RunReport(
        label=label,
        title=title_match.group(1).strip() if title_match else label,
        result=_bold_value(markdown, "Result"),
        model=_bold_value(markdown, "Model deployment"),
        run_directory=_bold_value(markdown, "Run directory"),
        scope=_bold_value(markdown, "Scope"),
        source_path=source_path,
        markdown=markdown,
        invariants=_invariants(markdown),
    )


def _result_class(value: str) -> str:
    return "pass" if value.upper() == "PASS" else "fail"


def _summary_card(report: RunReport) -> str:
    passed = sum(item.result.upper() == "PASS" for item in report.invariants)
    return f"""
      <button class="summary-card" type="button" data-target="run-{report.label.lower()}">
        <span class="run-label">{html.escape(report.label)}</span>
        <strong>{html.escape(report.result)}</strong>
        <span>{passed}/{len(report.invariants)} invariants passed</span>
      </button>"""


def _invariant_rows(report: RunReport) -> str:
    return "\n".join(
        "<tr>"
        f"<td>{html.escape(item.check)}</td>"
        f'<td><span class="badge {_result_class(item.result)}">{html.escape(item.result)}</span></td>'
        f"<td>{html.escape(item.evidence)}</td>"
        "</tr>"
        for item in report.invariants
    )


def _run_section(report: RunReport, *, open_by_default: bool) -> str:
    relative_source = f"{report.source_path.parent.name}/{report.source_path.name}"
    open_attribute = " open" if open_by_default else ""
    return f"""
    <details class="run-panel" id="run-{report.label.lower()}"{open_attribute}>
      <summary>
        <span class="chevron" aria-hidden="true"></span>
        <span class="run-label">{html.escape(report.label)}</span>
        <span class="run-title">{html.escape(report.title)}</span>
        <span class="badge {_result_class(report.result)}">{html.escape(report.result)}</span>
      </summary>
      <div class="run-content">
        <dl class="metadata">
          <div><dt>Model</dt><dd>{html.escape(report.model)}</dd></div>
          <div><dt>Scope</dt><dd>{html.escape(report.scope)}</dd></div>
          <div><dt>Run directory</dt><dd><code>{html.escape(report.run_directory)}</code></dd></div>
          <div><dt>Source</dt><dd><a href="{html.escape(relative_source)}">{html.escape(relative_source)}</a></dd></div>
        </dl>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Invariant</th><th>Result</th><th>Evidence</th></tr></thead>
            <tbody>{_invariant_rows(report)}</tbody>
          </table>
        </div>
        <details class="source-report">
          <summary><span class="chevron" aria-hidden="true"></span> Complete source report</summary>
          <p class="muted">Every line from the latest Markdown report is preserved below.</p>
          <pre>{html.escape(report.markdown)}</pre>
        </details>
      </div>
    </details>"""


def render(reports: tuple[RunReport, ...]) -> str:
    passed_runs = sum(report.passed for report in reports)
    total_invariants = sum(len(report.invariants) for report in reports)
    passed_invariants = sum(
        item.result.upper() == "PASS" for report in reports for item in report.invariants
    )
    cards = "".join(_summary_card(report) for report in reports)
    sections = "".join(
        _run_section(report, open_by_default=not report.passed) for report in reports
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>M8 Live Qualification Report</title>
  <script>
  (() => {{
    const param = new URLSearchParams(window.location.search).get("scoutTheme");
    const theme =
      param || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    document.documentElement.setAttribute("data-theme", theme);
  }})();
  </script>
  <style>
  :root {{
    color-scheme: light;
    --cp-bg: #f7f4ef;
    --cp-bg-elevated: #fcfbf8;
    --cp-surface: #ffffff;
    --cp-surface-soft: #f5f5f5;
    --cp-border: #dedede;
    --cp-border-strong: #919191;
    --cp-text: #242424;
    --cp-text-muted: #5c5c5c;
    --cp-text-soft: #6f6f6f;
    --cp-accent: #b11f4b;
    --cp-accent-hover: #9a1a41;
    --cp-accent-soft: rgba(177, 31, 75, 0.08);
    --cp-accent-fg: #ffffff;
    --cp-success: #16a34a;
    --cp-danger: #dc2626;
    --cp-warning: #f59e0b;
    --cp-link: #0078d4;
    --cp-shadow: 0 18px 48px rgba(0, 0, 0, 0.12);
    --cp-overlay: rgba(255, 255, 255, 0.8);
    --cp-panel: rgba(255, 255, 255, 0.86);
    --cp-panel-strong: rgba(255, 255, 255, 0.96);
    --cp-sheen: rgba(255, 255, 255, 0.55);
    --cp-highlight: rgba(177, 31, 75, 0.12);
  }}
  html[data-theme="dark"] {{
    color-scheme: dark;
    --cp-bg: #3d3b3a;
    --cp-bg-elevated: #343231;
    --cp-surface: #292929;
    --cp-surface-soft: #2e2e2e;
    --cp-border: #474747;
    --cp-border-strong: #5f5f5f;
    --cp-text: #dedede;
    --cp-text-muted: #919191;
    --cp-text-soft: #b0b0b0;
    --cp-accent: #fd8ea1;
    --cp-accent-hover: #fb7b91;
    --cp-accent-soft: rgba(253, 142, 161, 0.14);
    --cp-accent-fg: #1a1a1a;
    --cp-success: #4ade80;
    --cp-danger: #f87171;
    --cp-warning: #fbbf24;
    --cp-link: #4da6ff;
    --cp-shadow: 0 18px 48px rgba(0, 0, 0, 0.32);
    --cp-overlay: rgba(41, 41, 41, 0.88);
    --cp-panel: rgba(41, 41, 41, 0.72);
    --cp-panel-strong: rgba(41, 41, 41, 0.96);
    --cp-sheen: rgba(255, 255, 255, 0.04);
    --cp-highlight: rgba(253, 142, 161, 0.12);
  }}
  * {{ box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; }}
  body {{
    margin: 0;
    background: var(--cp-bg);
    color: var(--cp-text);
    font-family: "Segoe UI", Aptos, Calibri, -apple-system, BlinkMacSystemFont, sans-serif;
    letter-spacing: 0;
  }}
  body::before {{
    content: "";
    position: fixed;
    inset: 0;
    pointer-events: none;
    background: repeating-linear-gradient(90deg, var(--cp-bg), var(--cp-bg) 47px, var(--cp-sheen) 48px);
  }}
  main {{ position: relative; width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 48px 0 80px; }}
  header {{ border-top: 4px solid var(--cp-accent); padding: 28px 0 24px; }}
  .eyebrow, .run-label {{ color: var(--cp-accent); font-weight: 700; text-transform: uppercase; }}
  .eyebrow {{ margin: 0 0 8px; font-size: 13px; }}
  h1 {{ margin: 0; font-size: 48px; line-height: 1; }}
  .lede {{ max-width: 760px; color: var(--cp-text-muted); font-size: 18px; line-height: 1.6; }}
  .toolbar {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 20px; }}
  button {{ font: inherit; }}
  .command {{
    border: 1px solid var(--cp-border-strong);
    border-radius: 6px;
    background: var(--cp-surface);
    color: var(--cp-text);
    padding: 8px 12px;
    cursor: pointer;
  }}
  .command:hover {{ border-color: var(--cp-accent); color: var(--cp-accent); }}
  .overview {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 12px 0 28px; }}
  .summary-card {{
    display: grid;
    gap: 8px;
    min-height: 132px;
    padding: 18px;
    text-align: left;
    border: 1px solid var(--cp-border);
    border-radius: 8px;
    background: var(--cp-surface);
    color: var(--cp-text);
    cursor: pointer;
    box-shadow: 0 1px 2px var(--cp-border);
  }}
  .summary-card:hover {{ border-color: var(--cp-accent); background: var(--cp-accent-soft); }}
  .summary-card strong {{ font-size: 22px; }}
  .summary-card span:last-child, .muted {{ color: var(--cp-text-muted); }}
  .rollup {{
    display: flex;
    gap: 24px;
    flex-wrap: wrap;
    margin-bottom: 28px;
    padding: 14px 16px;
    border-left: 3px solid var(--cp-accent);
    background: var(--cp-surface-soft);
  }}
  .rollup strong {{ font-size: 20px; }}
  .run-panel {{ margin: 12px 0; border: 1px solid var(--cp-border); border-radius: 8px; background: var(--cp-surface); }}
  .run-panel > summary {{
    display: grid;
    grid-template-columns: 18px 48px minmax(0, 1fr) auto;
    align-items: center;
    gap: 12px;
    min-height: 64px;
    padding: 12px 16px;
    cursor: pointer;
    list-style: none;
  }}
  summary::-webkit-details-marker {{ display: none; }}
  .chevron {{ width: 9px; height: 9px; border-right: 2px solid var(--cp-text-muted); border-bottom: 2px solid var(--cp-text-muted); transform: rotate(-45deg); transition: transform 160ms ease; }}
  details[open] > summary .chevron {{ transform: rotate(45deg); }}
  .run-title {{ font-weight: 650; }}
  .badge {{ display: inline-block; width: max-content; padding: 4px 8px; border: 1px solid currentColor; border-radius: 6px; font-size: 12px; font-weight: 700; }}
  .badge.pass {{ color: var(--cp-success); }}
  .badge.fail {{ color: var(--cp-danger); }}
  .run-content {{ border-top: 1px solid var(--cp-border); padding: 18px; }}
  .metadata {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin: 0 0 20px; }}
  .metadata div {{ min-width: 0; padding: 12px; border: 1px solid var(--cp-border); background: var(--cp-surface-soft); }}
  dt {{ color: var(--cp-text-muted); font-size: 12px; font-weight: 700; text-transform: uppercase; }}
  dd {{ margin: 5px 0 0; overflow-wrap: anywhere; }}
  code, pre {{ font-family: Consolas, "Courier New", Courier, monospace; }}
  a {{ color: var(--cp-link); }}
  .table-wrap {{ overflow-x: auto; border: 1px solid var(--cp-border); }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ padding: 11px 12px; border-bottom: 1px solid var(--cp-border); text-align: left; vertical-align: top; line-height: 1.45; }}
  th {{ background: var(--cp-surface-soft); font-size: 12px; text-transform: uppercase; }}
  td:first-child {{ width: 25%; font-weight: 650; }}
  td:nth-child(2) {{ width: 88px; }}
  .source-report {{ margin-top: 16px; border: 1px solid var(--cp-border); background: var(--cp-bg-elevated); }}
  .source-report > summary {{ display: flex; align-items: center; gap: 12px; padding: 14px; cursor: pointer; font-weight: 650; }}
  .source-report > p {{ margin: 0; padding: 0 14px 14px; }}
  pre {{ margin: 0; padding: 16px; max-height: 70vh; overflow: auto; border-top: 1px solid var(--cp-border); background: var(--cp-surface-soft); color: var(--cp-text); font-size: 12px; line-height: 1.5; white-space: pre-wrap; overflow-wrap: anywhere; }}
  footer {{ margin-top: 32px; padding-top: 16px; border-top: 1px solid var(--cp-border); color: var(--cp-text-muted); }}
  @media (max-width: 760px) {{
    main {{ width: min(100% - 20px, 1180px); padding-top: 20px; }}
    h1 {{ font-size: 36px; }}
    .overview, .metadata {{ grid-template-columns: 1fr; }}
    .run-panel > summary {{ grid-template-columns: 18px 42px minmax(0, 1fr); }}
    .run-panel > summary .badge {{ grid-column: 3; }}
    th, td {{ min-width: 180px; }}
  }}
  </style>
</head>
<body>
  <main>
    <header>
      <p class="eyebrow">M8 management hierarchy and delegation</p>
      <h1>Live qualification</h1>
      <p class="lede">Three real Azure OpenAI gpt-5.2 runs. T1 proves atomic delivery, T2 proves human-gated formation, and T3 records the current parallel-delegation stopping point without hiding the failure.</p>
      <div class="toolbar">
        <button class="command" id="expand-all" type="button">Expand all runs</button>
        <button class="command" id="collapse-all" type="button">Collapse all runs</button>
      </div>
    </header>
    <section class="overview" aria-label="Run outcomes">{cards}
    </section>
    <div class="rollup">
      <span><strong>{passed_runs}/{len(reports)}</strong> runs passed</span>
      <span><strong>{passed_invariants}/{total_invariants}</strong> invariants passed</span>
      <span><strong>gpt-5.2</strong> live provider</span>
    </div>
    <section aria-label="Detailed run reports">{sections}
    </section>
    <footer>Generated from the committed T1-latest.md, T2-latest.md, and T3-latest.md reports. Full source details are embedded in this file.</footer>
  </main>
  <script>
  const runs = [...document.querySelectorAll(".run-panel")];
  document.getElementById("expand-all").addEventListener("click", () => runs.forEach(run => run.open = true));
  document.getElementById("collapse-all").addEventListener("click", () => runs.forEach(run => run.open = false));
  document.querySelectorAll("[data-target]").forEach(card => card.addEventListener("click", () => {{
    const run = document.getElementById(card.dataset.target);
    run.open = true;
    run.scrollIntoView({{ behavior: "smooth", block: "start" }});
  }}));
  </script>
</body>
</html>
"""


def _parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-root", type=Path, default=root / "reports")
    parser.add_argument(
        "--output", type=Path, default=root / "reports" / "M8-live-qualification.html"
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    reports = tuple(
        parse_report(label, (args.reports_root / relative_path).resolve())
        for label, relative_path in _REPORT_FILES
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(reports), encoding="utf-8")
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
