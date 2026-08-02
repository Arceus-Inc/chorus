#!/usr/bin/env python3
"""Run 13 paired Hermes/Bex delegation contracts plus live LLM checkpoints."""

from __future__ import annotations

import argparse
import html
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DREAM = ROOT.parent / "Harness"
HERMES = ROOT.parent / "Research-docs" / "vendor" / "hermes-agent"
OUT = ROOT / "reports" / "hermes-bex-parallel-13"
REPORT = OUT / "index.html"


class CaseId(StrEnum):
    SCHEMA_BOUND = "schema-bound"
    CONTEXT_FIREWALL = "context-firewall"
    SYNC_BATCH = "sync-batch"
    FAILURE_AGGREGATION = "failure-aggregation"
    BACKGROUND_HANDLE = "background-handle"
    BACKGROUND_BATCH = "background-batch"
    SESSION_OWNERSHIP = "session-ownership"
    IDLE_REENTRY = "idle-reentry"
    CAPACITY = "capacity"
    UNSUPPORTED_DELIVERY = "unsupported-delivery"
    CANCELLATION = "cancellation"
    TIMEOUT = "timeout"
    SUMMARY_SPILL = "summary-spill"


@dataclass(frozen=True)
class Probe:
    repo: Path
    node: str


@dataclass(frozen=True)
class PairCase:
    id: CaseId
    contract: str
    hermes: Probe
    bex: Probe


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    elapsed_seconds: float
    output: str


@dataclass(frozen=True)
class PairResult:
    case: PairCase
    hermes: ProbeResult
    bex: ProbeResult

    @property
    def ok(self) -> bool:
        return self.hermes.ok and self.bex.ok


@dataclass(frozen=True)
class LiveResult:
    name: str
    ok: bool
    elapsed_seconds: float
    detail: str
    artifact: Path


def _h(node: str) -> Probe:
    return Probe(HERMES, node)


def _d(node: str) -> Probe:
    return Probe(DREAM, node)


CASES = (
    PairCase(
        CaseId.SCHEMA_BOUND,
        "Batch input is schema-bounded and rejects fan-out above the configured limit.",
        _h("tests/tools/test_delegate.py::TestDelegateTask::test_batch_capped_at_3"),
        _d(
            "tests/test_subagents/test_spawn_tool.py::TestSpawnSubagentTool::"
            "test_input_requires_exactly_one_shape_and_bounded_batch"
        ),
    ),
    PairCase(
        CaseId.CONTEXT_FIREWALL,
        "A fresh child receives goal plus packed context, never the parent transcript.",
        _h("tests/tools/test_delegate.py::TestChildSystemPrompt::test_goal_with_context"),
        _d(
            "tests/test_subagents/test_delegate.py::test_build_child_prompt_contains_goal_and_context"
        ),
    ),
    PairCase(
        CaseId.SYNC_BATCH,
        "A synchronous batch joins all children and preserves input order.",
        _h("tests/tools/test_delegate.py::TestDelegateTask::test_batch_mode"),
        _d(
            "tests/test_subagents/test_spawn_tool.py::TestSpawnSubagentTool::"
            "test_sync_tasks_run_concurrently_and_return_input_order"
        ),
    ),
    PairCase(
        CaseId.FAILURE_AGGREGATION,
        "One failed child is reported beside successful siblings without losing either result.",
        _h("tests/tools/test_delegate.py::TestDelegateTask::test_failed_child_included_in_results"),
        _d(
            "tests/test_subagents/test_spawn_tool.py::TestSpawnSubagentTool::"
            "test_batch_preserves_success_and_failure_results"
        ),
    ),
    PairCase(
        CaseId.BACKGROUND_HANDLE,
        "Background dispatch returns a handle before child completion.",
        _h(
            "tests/tools/test_async_delegation.py::test_delegate_task_background_routes_async_and_does_not_block"
        ),
        _d(
            "tests/test_subagents/test_spawn_tool.py::TestSpawnSubagentTool::"
            "test_background_returns_handle_then_queues_completion"
        ),
    ),
    PairCase(
        CaseId.BACKGROUND_BATCH,
        "A background fan-out occupies one slot and produces one ordered completion.",
        _h(
            "tests/tools/test_async_delegation.py::test_delegate_task_background_batch_runs_as_one_unit"
        ),
        _d(
            "tests/test_subagents/test_spawn_tool.py::TestSpawnSubagentTool::"
            "test_background_batch_queues_one_ordered_completion"
        ),
    ),
    PairCase(
        CaseId.SESSION_OWNERSHIP,
        "Completions are visible only to their originating parent session.",
        _h(
            "tests/tools/test_async_delegation.py::test_completion_event_lands_on_shared_queue_with_session_key"
        ),
        _d(
            "tests/test_subagents/test_async_delegation.py::"
            "test_completion_is_owned_by_session_and_preserves_result_order"
        ),
    ),
    PairCase(
        CaseId.IDLE_REENTRY,
        "A completion re-enters through the idle rail as a new message, never mid-tool dispatch.",
        _h(
            "tests/tools/test_async_delegation.py::test_gateway_watch_drain_requeues_async_without_looping"
        ),
        _d(
            "tests/test_engine/test_session.py::test_background_completion_is_injected_as_a_new_user_turn"
        ),
    ),
    PairCase(
        CaseId.CAPACITY,
        "Capacity refusal starts no extra work; the tool-level caller can safely fall back.",
        _h("tests/tools/test_async_delegation.py::test_dispatch_rejected_at_capacity"),
        _d(
            "tests/test_subagents/test_spawn_tool.py::TestSpawnSubagentTool::"
            "test_background_capacity_forces_sync_with_note"
        ),
    ),
    PairCase(
        CaseId.UNSUPPORTED_DELIVERY,
        "A finite session runs synchronously with an explicit note instead of orphaning a result.",
        _h(
            "tests/tools/test_async_delegation.py::test_delegate_task_background_waits_inside_kanban_worker"
        ),
        _d(
            "tests/test_subagents/test_spawn_tool.py::TestSpawnSubagentTool::"
            "test_background_forces_sync_when_delivery_is_unavailable"
        ),
    ),
    PairCase(
        CaseId.CANCELLATION,
        "Parent cancellation soft-interrupts owned children and leaves no active orphan.",
        _h("tests/tools/test_async_delegation.py::test_interrupt_all_signals_running_children"),
        _d(
            "tests/test_subagents/test_async_delegation.py::"
            "test_cancel_session_interrupts_children_without_orphans"
        ),
    ),
    PairCase(
        CaseId.TIMEOUT,
        "A stalled child reaches a terminal timeout/stall result instead of hanging forever.",
        _h(
            "tests/tools/test_async_delegation.py::test_stalled_runner_is_interrupted_then_finalized"
        ),
        _d(
            "tests/test_subagents/test_async_delegation.py::test_timeout_becomes_a_typed_completion"
        ),
    ),
    PairCase(
        CaseId.SUMMARY_SPILL,
        "Oversized summaries are budgeted for the parent and spilled losslessly.",
        _h(
            "tests/tools/test_delegate_summary_budget.py::test_batch_overflow_trimmed_and_spilled_losslessly"
        ),
        _d(
            "tests/test_subagents/test_delegate.py::"
            "test_over_budget_summary_spills_to_scratch_not_the_worktree"
        ),
    ),
)


def _run_probe(probe: Probe) -> ProbeResult:
    started = time.monotonic()
    process = subprocess.run(
        ("uv", "run", "pytest", "-q", probe.node),
        cwd=probe.repo,
        capture_output=True,
        text=True,
        timeout=180,
    )
    output = (process.stdout + process.stderr).strip()
    return ProbeResult(process.returncode == 0, time.monotonic() - started, output[-1600:])


def _load_azure_env() -> tuple[dict[str, str], str, str]:
    env = os.environ.copy()
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    deployment = env.get("AZURE_OPENAI_DEPLOYMENT", "")
    base_url = env.get("AZURE_OPENAI_BASE_URL", "").rstrip("/")
    api_key = env.get("AZURE_OPENAI_API_KEY", "")
    if not deployment or not base_url or not api_key:
        raise RuntimeError("AZURE_OPENAI_DEPLOYMENT, BASE_URL, and API_KEY are required")
    env.update(
        AZURE_FOUNDRY_API_KEY=api_key,
        AZURE_FOUNDRY_BASE_URL=base_url,
        OPENAI_API_KEY=api_key,
        OPENAI_BASE_URL=base_url,
    )
    env.pop("VIRTUAL_ENV", None)
    return env, deployment, base_url


def _run_bex_live() -> LiveResult:
    artifact = ROOT / "reports" / "spawn-enum-e2e-report.html"
    started = time.monotonic()
    process = subprocess.run(
        ("uv", "run", "python", "examples/spawn_enum_e2e.py"),
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    detail = (process.stdout + process.stderr).strip()[-2400:]
    return LiveResult(
        "Bex live LLM (7 checkpoints)",
        process.returncode == 0,
        time.monotonic() - started,
        detail,
        artifact,
    )


def _run_hermes_live() -> LiveResult:
    env, deployment, base_url = _load_azure_env()
    workdir = OUT / "hermes-live-workdir"
    home_temp = tempfile.TemporaryDirectory(prefix="hermes-parity-")
    home = Path(home_temp.name)
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    (home / "config.yaml").write_text(
        "model:\n"
        "  provider: azure-foundry\n"
        f"  default: {deployment}\n"
        f"  base_url: {base_url}\n"
        "  api_mode: chat_completions\n"
        "delegation:\n"
        "  max_concurrent_children: 3\n"
        "display:\n"
        "  skin: mono\n",
        encoding="utf-8",
    )
    env["HERMES_HOME"] = str(home)
    env["TERMINAL_CWD"] = str(workdir)
    prompt = (
        "Call delegate_task exactly once with a tasks array of two children. "
        "Child one must return exact token HERMES_CHILD_A; child two must return exact token "
        "HERMES_CHILD_B. As soon as delegate_task returns its background handle, use the terminal "
        "tool to create parent-kept-working.txt containing exactly HERMES_PARENT_WORKED. Do not "
        "poll. When the consolidated async completion returns as a new message, reply "
        "HERMES_LIVE_OK and include both child tokens."
    )
    started = time.monotonic()
    process = subprocess.run(
        (
            "uv",
            "run",
            "hermes",
            "-z",
            prompt,
            "-m",
            deployment,
            "--provider",
            "azure-foundry",
            "-t",
            "terminal,file,delegation",
            "--yolo",
            "--ignore-user-config",
        ),
        cwd=HERMES,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    log = OUT / "hermes-live.log"
    detail = process.stdout + "\n--- STDERR ---\n" + process.stderr
    log.write_text(detail, encoding="utf-8")
    marker = workdir / "parent-kept-working.txt"
    marker_ok = (
        marker.is_file() and marker.read_text(encoding="utf-8").strip() == "HERMES_PARENT_WORKED"
    )
    output_ok = all(
        token in detail for token in ("HERMES_LIVE_OK", "HERMES_CHILD_A", "HERMES_CHILD_B")
    )
    result = LiveResult(
        "Hermes live LLM (batch + keep-working + re-entry)",
        process.returncode == 0 and marker_ok and output_ok,
        time.monotonic() - started,
        f"exit={process.returncode} marker={marker_ok} tokens={output_ok}\n{detail[-2200:]}",
        log,
    )
    home_temp.cleanup()
    return result


def _write_report(results: tuple[PairResult, ...], live: tuple[LiveResult, ...]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = "".join(
        "<tr>"
        f"<td><code>{result.case.id.value}</code></td>"
        f"<td>{html.escape(result.case.contract)}</td>"
        f"<td class={'pass' if result.hermes.ok else 'fail'}>{'PASS' if result.hermes.ok else 'FAIL'}<br>{result.hermes.elapsed_seconds:.2f}s</td>"
        f"<td class={'pass' if result.bex.ok else 'fail'}>{'PASS' if result.bex.ok else 'FAIL'}<br>{result.bex.elapsed_seconds:.2f}s</td>"
        "</tr>"
        for result in results
    )
    live_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item.name)}</td>"
        f"<td class={'pass' if item.ok else 'fail'}>{'PASS' if item.ok else 'FAIL'}</td>"
        f"<td>{item.elapsed_seconds:.1f}s</td>"
        f"<td><a href='{html.escape(os.path.relpath(item.artifact, OUT))}'>artifact</a><pre>{html.escape(item.detail)}</pre></td>"
        "</tr>"
        for item in live
    )
    passed = sum(result.ok for result in results)
    REPORT.write_text(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Hermes vs Bex parallel-subagent parity</title>
<style>
body{{font:15px system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem;background:#f4f1ea;color:#201b16}}
table{{border-collapse:collapse;width:100%;background:#fff}}th,td{{border:1px solid #cfc7bb;padding:.55rem;text-align:left;vertical-align:top}}
.pass{{color:#176b3a;font-weight:700}}.fail{{color:#a12632;font-weight:700}}pre{{white-space:pre-wrap;max-height:16rem;overflow:auto;font-size:12px}}
</style></head><body>
<h1>Hermes vs Bex parallel-subagent parity</h1>
<p>{passed}/{len(results)} paired deterministic contracts passed. Each row executes one Hermes vendor test and one Bex (Dream/Chorus) test.</p>
<table><thead><tr><th>Case</th><th>Shared contract</th><th>Hermes</th><th>Bex</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Live LLM checkpoints</h2><table><thead><tr><th>Runtime</th><th>Result</th><th>Wall</th><th>Evidence</th></tr></thead><tbody>{live_rows}</tbody></table>
<p>Known policy delta: current Hermes forces top-level model delegation into background mode; the HTML plan and Bex retain explicit sync/background selection.</p>
</body></html>""",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-live", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    results: list[PairResult] = []
    for case in CASES:
        hermes = _run_probe(case.hermes)
        bex = _run_probe(case.bex)
        result = PairResult(case, hermes, bex)
        results.append(result)
        print(
            f"[{case.id.value}] Hermes={'PASS' if hermes.ok else 'FAIL'} Bex={'PASS' if bex.ok else 'FAIL'}",
            flush=True,
        )
    live = () if args.skip_live else (_run_bex_live(), _run_hermes_live())
    _write_report(tuple(results), live)
    print(f"report -> {REPORT}")
    return 0 if all(result.ok for result in results) and all(item.ok for item in live) else 1


if __name__ == "__main__":
    raise SystemExit(main())
