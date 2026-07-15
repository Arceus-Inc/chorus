from __future__ import annotations

from pathlib import Path

from examples.render_live_run_report import parse_report, render


def _report(path: Path, label: str, result: str) -> Path:
    path.write_text(
        f"""# {label} report

**Result:** {result}
**Model deployment:** `gpt-5.2`
**Run directory:** `runs/{label.lower()}`
**Scope:** {label} acceptance

## Invariants

| Check | Result | Evidence |
| --- | --- | --- |
| exact behavior | {"PASS" if result == "PASS" else "FAIL"} | <unsafe> & complete |

## Full Detail

Every source line is preserved.
""",
        encoding="utf-8",
    )
    return path


def test_render_preserves_all_reports_and_builds_collapsible_dashboard(tmp_path: Path) -> None:
    sources = (
        _report(tmp_path / "T1-latest.md", "T1", "PASS"),
        _report(tmp_path / "T2-latest.md", "T2", "PASS"),
        _report(tmp_path / "T3-latest.md", "T3", "STOPPED / NEEDS FIX"),
    )
    reports = tuple(parse_report(f"T{index}", source) for index, source in enumerate(sources, 1))

    output = render(reports)

    assert output.count('class="run-panel"') == 3
    assert output.count('class="source-report"') == 3
    assert 'id="run-t3" open' in output
    assert "2/3</strong> runs passed" in output
    assert "&lt;unsafe&gt; &amp; complete" in output
    assert "Every source line is preserved." in output
    assert f'href="{tmp_path.name}/T1-latest.md"' in output
    assert "5vw" not in output
    assert 'new URLSearchParams(window.location.search).get("scoutTheme")' in output
    assert "--cp-accent: #b11f4b" in output
