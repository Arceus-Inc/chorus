"""Evaluate a candidate solution against the human PR — the benchmark oracle.

Three signals, in priority order:
1. **Objective** (when the case ships a test patch + expected tests): apply the PR's TEST patch on top
   of the candidate, run the repo's tests, and require the ``FAIL_TO_PASS`` set to go green while
   ``PASS_TO_PASS`` stays green. This is the rigorous SWE-bench signal. It is best-effort: if the repo's
   environment can't be built here (no Docker, missing deps), it reports *infeasible* and we fall back.
2. **LLM judge** (fallback / non-test cases): a model compares the candidate diff to the gold diff + the
   issue and returns RESOLVED / PARTIAL / UNRESOLVED + a 0..1 score.
3. **File overlap** (always): the fraction of gold-patch files the candidate also touched — a cheap,
   model-free sanity signal shown alongside whichever verdict was used.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

import httpx

from swe_eval.case import BenchCase, CandidateSolution, EvalResult
from swe_eval.env import ModelCreds

_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$", re.MULTILINE)


def files_in_patch(patch: str) -> set[str]:
    """The set of file paths a unified diff touches (from its ``+++ b/<path>`` headers)."""
    return {m.strip() for m in _FILE_RE.findall(patch) if m.strip() and m.strip() != "/dev/null"}


def files_overlap(gold_patch: str, candidate_diff: str) -> float:
    """Fraction of gold-patch files the candidate also touched (0..1); 0 when gold lists none."""
    gold = files_in_patch(gold_patch)
    if not gold:
        return 0.0
    cand = files_in_patch(candidate_diff)
    return len(gold & cand) / len(gold)


# --------------------------------------------------------------------------- objective oracle


def _run(cmd: list[str], cwd: Path, timeout_s: float) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout_s)


def _apply_test_patch(worktree: Path, test_patch: str) -> bool:
    """Apply the PR's test patch onto the candidate worktree. Returns True on success."""
    with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False, encoding="utf-8") as fh:
        fh.write(test_patch)
        patch_path = fh.name
    try:
        for extra in ([], ["--3way"], ["-C1"]):
            res = _run(["git", "apply", *extra, patch_path], worktree, 120)
            if res.returncode == 0:
                return True
        return False
    finally:
        Path(patch_path).unlink(missing_ok=True)


def objective_score(case: BenchCase, candidate: CandidateSolution) -> EvalResult | None:
    """Run the objective oracle; return an ``EvalResult`` or ``None`` if the env is infeasible here."""
    wt = Path(candidate.working_dir)
    if not wt.exists() or not case.has_objective_oracle:
        return None
    if not _apply_test_patch(wt, case.test_patch):
        return None  # can't apply the tests here -> fall back to the judge

    # Best-effort environment setup (e.g. `pip install -e .` / `npm ci`). Non-fatal: many repos need a
    # Docker image we don't have; if tests then can't run we return infeasible.
    if case.setup_cmd:
        try:
            _run(case.setup_cmd.split(), wt, 900)
        except Exception:
            pass

    f2p_pass = _run_tests(case, wt, case.fail_to_pass)
    p2p_pass = _run_tests(case, wt, case.pass_to_pass) if case.pass_to_pass else {}
    if f2p_pass is None:
        return None  # the test runner itself couldn't execute -> infeasible

    f2p_passed = sum(1 for ok in f2p_pass.values() if ok)
    p2p_passed = sum(1 for ok in p2p_pass.values() if ok)
    resolved = f2p_passed == len(case.fail_to_pass) and p2p_passed == len(p2p_pass)
    return EvalResult(
        case_id=case.id,
        resolved=resolved,
        method="objective",
        produced_diff=candidate.produced_diff,
        fail_to_pass_passed=f2p_passed,
        fail_to_pass_total=len(case.fail_to_pass),
        pass_to_pass_passed=p2p_passed,
        pass_to_pass_total=len(p2p_pass),
        files_overlap=files_overlap(case.gold_patch, candidate.diff),
        detail=f"FAIL_TO_PASS {f2p_passed}/{len(case.fail_to_pass)}, PASS_TO_PASS {p2p_passed}/{len(p2p_pass)}",
    )


def _run_tests(case: BenchCase, wt: Path, test_ids: tuple[str, ...]) -> dict[str, bool] | None:
    """Run the given tests; map id->passed. ``None`` if the runner couldn't execute at all."""
    if not test_ids:
        return {}
    if case.language == "python" or case.test_cmd.startswith("pytest"):
        # Run each id and read the return code, so a collection error on one doesn't sink the batch.
        results: dict[str, bool] = {}
        ran_any = False
        for tid in test_ids:
            res = _run(["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", tid], wt, 600)
            combined = (res.stdout or "") + (res.stderr or "")
            if (
                "no tests ran" in combined.lower()
                and "error" in combined.lower()
                and res.returncode != 0
                and not ran_any
            ):
                # first test can't even be collected — likely a broken env
                if "ModuleNotFoundError" in combined or "ImportError" in combined:
                    return None
            ran_any = True
            results[tid] = res.returncode == 0
        return results
    # generic (JS/other): run the project's test command once; treat exit 0 as all listed tests passing
    if case.test_cmd:
        res = _run(case.test_cmd.split(), wt, 600)
        return dict.fromkeys(test_ids, res.returncode == 0)
    return None


# --------------------------------------------------------------------------- LLM judge

_JUDGE_SYSTEM = (
    "You are a rigorous software-engineering evaluator. Given a GitHub issue, the reference human fix, "
    "and a candidate patch produced by an AI engineer, decide whether the candidate genuinely resolves "
    "the issue. Judge behavior and correctness, not stylistic similarity to the reference — a different "
    "but correct fix is RESOLVED. Reply with ONLY a JSON object: "
    '{"verdict": "RESOLVED"|"PARTIAL"|"UNRESOLVED", "score": 0.0-1.0, "reason": "<one sentence>"}.'
)


def _judge_prompt(case: BenchCase, candidate: CandidateSolution) -> str:
    return (
        f"# Issue\n{case.issue_text[:6000]}\n\n"
        f"# Reference human fix (the merged PR)\n```diff\n{case.gold_patch[:8000]}\n```\n\n"
        f"# Candidate patch (AI engineer)\n```diff\n{(candidate.diff or '(empty diff)')[:8000]}\n```\n\n"
        "Does the candidate patch resolve the issue? Reply with the JSON object only."
    )


def judge_candidate(case: BenchCase, candidate: CandidateSolution, creds: ModelCreds) -> EvalResult:
    """Ask the model to judge the candidate against the issue + reference fix."""
    overlap = files_overlap(case.gold_patch, candidate.diff)
    if not candidate.produced_diff:
        return EvalResult(
            case_id=case.id,
            resolved=False,
            method="judge",
            produced_diff=False,
            judge_score=0.0,
            judge_verdict="UNRESOLVED",
            files_overlap=overlap,
            detail="empty candidate diff — nothing to judge",
        )
    url = creds.base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": creds.deployment,
        "messages": [
            {"role": "system", "content": _JUDGE_SYSTEM},
            {"role": "user", "content": _judge_prompt(case, candidate)},
        ],
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {creds.api_key}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        return EvalResult(
            case_id=case.id,
            resolved=False,
            method="judge",
            produced_diff=True,
            judge_verdict="ERROR",
            files_overlap=overlap,
            detail=f"judge call failed: {exc!r}"[:300],
        )
    verdict, score, reason = _parse_judge(content)
    return EvalResult(
        case_id=case.id,
        resolved=verdict == "RESOLVED",
        method="judge",
        produced_diff=True,
        judge_score=score,
        judge_verdict=verdict,
        files_overlap=overlap,
        detail=reason[:300],
    )


def _parse_judge(content: str) -> tuple[str, float, str]:
    """Extract the verdict JSON from the model reply (tolerating markdown fences / stray prose)."""
    text = content.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            verdict = str(obj.get("verdict", "")).upper()
            if verdict not in {"RESOLVED", "PARTIAL", "UNRESOLVED"}:
                verdict = "UNRESOLVED"
            score = obj.get("score")
            score = float(score) if isinstance(score, (int, float)) else None
            return (
                verdict,
                score if score is not None else (1.0 if verdict == "RESOLVED" else 0.0),
                str(obj.get("reason", "")),
            )
        except (json.JSONDecodeError, ValueError):
            pass
    upper = text.upper()
    verdict = "RESOLVED" if "RESOLVED" in upper and "UNRESOLVED" not in upper else "UNRESOLVED"
    return verdict, 1.0 if verdict == "RESOLVED" else 0.0, text[:200]


# --------------------------------------------------------------------------- orchestrator


def evaluate(case: BenchCase, candidate: CandidateSolution, creds: ModelCreds) -> EvalResult:
    """Score the candidate: objective oracle when feasible, else the LLM judge."""
    if case.has_objective_oracle:
        objective = objective_score(case, candidate)
        if objective is not None:
            return objective
    return judge_candidate(case, candidate, creds)
