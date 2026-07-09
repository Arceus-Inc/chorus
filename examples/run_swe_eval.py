"""SWE-Eval CLI — benchmark Chorus code employees on real issue->fix cases.

Examples:
  # import 5 Python cases from SWE-bench Lite and run them through the engineer
  uv run --directory chorus python examples/run_swe_eval.py --import-swebench 5

  # run a curated local dataset (JSONL), only two ids, with a wider per-case budget
  uv run --directory chorus python examples/run_swe_eval.py --dataset examples/swe_eval/datasets/curated.jsonl --ids id-a,id-b --timeout 2400

Skips cleanly (exit 0) when AZURE_OPENAI_* is unset. Writes reports/swe-eval/{results.jsonl,report.html}.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

# Put examples/ on sys.path so ``from swe_eval import ...`` resolves this sibling package,
# and make python/node/npx resolve to this interpreter's dir first (mirrors the other runners).
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")

from swe_eval.dataset import import_swebench_lite, load_jsonl, save_jsonl  # noqa: E402
from swe_eval.env import load_env, model_creds  # noqa: E402
from swe_eval.evaluate import evaluate  # noqa: E402
from swe_eval.prepare import PrepareError, export_base_state  # noqa: E402
from swe_eval.report import print_summary, write_html_report, write_results_jsonl  # noqa: E402
from swe_eval.runner import plugins_by_name, run_case  # noqa: E402


def _workdir() -> Path:
    return Path("chorus") if Path("chorus").is_dir() else Path(".")


async def _amain(args: argparse.Namespace) -> int:
    load_env()
    creds = model_creds()
    if creds is None:
        print("skipping: set AZURE_OPENAI_API_KEY / AZURE_OPENAI_BASE_URL / AZURE_OPENAI_DEPLOYMENT")
        return 0

    # --- load cases -------------------------------------------------------------------------------
    if args.dataset:
        cases = load_jsonl(args.dataset)
    elif args.import_swebench:
        print(f"importing {args.import_swebench} case(s) from SWE-bench Lite ...")
        cases = import_swebench_lite(limit=args.import_swebench)
        saved = _workdir() / "examples" / "swe_eval" / "datasets" / "swebench_lite_import.jsonl"
        save_jsonl(cases, saved)
        print(f"  saved imported dataset -> {saved}")
    else:
        print("nothing to run: pass --dataset <file.jsonl> or --import-swebench <N>")
        return 2

    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",") if i.strip()}
        cases = [c for c in cases if c.id in wanted]
    if args.limit:
        cases = cases[: args.limit]

    available = set(plugins_by_name())
    runnable = [c for c in cases if c.role in available]
    for c in cases:
        if c.role not in available:
            print(f"  SKIP {c.id}: role {c.role!r} not registered (known: {sorted(available)})")
    if not runnable:
        print("no runnable cases (check --ids / roles).")
        return 2

    workdir = _workdir()
    cache_root = workdir / ".chorus" / "swe-eval-cache"
    seeds_root = workdir / ".chorus" / "swe-eval-seeds"

    cases_by_id = {}
    candidates = {}
    results = []
    for i, case in enumerate(runnable, 1):
        print("\n" + "=" * 92)
        print(f"[{i}/{len(runnable)}] {case.id}  (role={case.role}, lang={case.language})")
        print(f"  repo={case.repo}  base={case.base_commit[:12]}  objective={case.has_objective_oracle}")
        cases_by_id[case.id] = case
        # --- prepare the base state ---
        try:
            seed = export_base_state(
                case.effective_clone_url, case.repo, case.base_commit,
                cache_root=cache_root, seed_dir=seeds_root / _safe(case.id),
            )
        except PrepareError as exc:
            print(f"  PREPARE FAILED: {exc}")
            continue
        # --- run the employee ---
        candidate = await run_case(
            case, creds=creds, seed_dir=seed, workdir=workdir,
            timeout_s=args.timeout, on_event=lambda ln: print(f"    {ln}"),
        )
        candidates[case.id] = candidate
        print(f"  beat_passed={candidate.beat_passed}  produced_diff={candidate.produced_diff}"
              + (f"  ERROR={candidate.error[:120]}" if candidate.error else ""))
        # --- evaluate ---
        result = evaluate(case, candidate, creds)
        results.append(result)
        print(f"  -> {result.method}: {'RESOLVED' if result.resolved else 'unresolved'}  ({result.detail[:80]})")

    # --- reports ---------------------------------------------------------------------------------
    out = workdir / "reports" / "swe-eval"
    write_results_jsonl(results, out / "results.jsonl")
    report = write_html_report(cases_by_id, candidates, results, out / "report.html")
    print_summary(results)
    print(f"\nreport -> {report}")
    resolved = sum(1 for r in results if r.resolved)
    return 0 if resolved == len(results) and results else 1


def _safe(s: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-")[:60] or "case"


def main() -> int:
    ap = argparse.ArgumentParser(description="Benchmark Chorus code employees on issue->fix cases.")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--dataset", help="path to a JSONL dataset of BenchCases")
    src.add_argument("--import-swebench", type=int, metavar="N", help="import N cases from SWE-bench Lite")
    ap.add_argument("--ids", help="comma-separated case ids to run (subset)")
    ap.add_argument("--limit", type=int, help="cap the number of cases run")
    ap.add_argument("--timeout", type=float, default=1800.0, help="per-case beat wall-clock (seconds)")
    args = ap.parse_args()
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
