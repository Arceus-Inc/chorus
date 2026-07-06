"""Load benchmark cases from a local JSONL file, and import ready-made ones from SWE-bench.

Two sources:
- ``load_jsonl`` / ``save_jsonl`` — the harness's own on-disk format (one ``BenchCase`` per line).
- ``import_swebench_lite`` — pulls Python cases straight from ``princeton-nlp/SWE-bench_Lite`` via
  the HuggingFace *datasets-server* JSON API (so no heavy ``datasets`` dependency; just ``httpx``).

SWE-bench rows map field-for-field onto :class:`BenchCase` (instance_id/base_commit/problem_statement/
patch/test_patch/FAIL_TO_PASS/PASS_TO_PASS), which is why the harness borrowed those names.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from swe_eval.case import BenchCase

_DATASETS_SERVER = "https://datasets-server.huggingface.co/rows"
_HF_PAGE_MAX = 100  # the datasets-server caps ``length`` at 100 rows per request


def load_jsonl(path: str | Path) -> list[BenchCase]:
    """Read a JSONL dataset (one JSON object per line) into ``BenchCase`` objects."""
    cases: list[BenchCase] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cases.append(_case_from_dict(json.loads(line)))
    return cases


def save_jsonl(cases: list[BenchCase], path: str | Path) -> None:
    """Persist cases as JSONL so an imported/curated set can be re-run deterministically."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(c.to_dict()) for c in cases) + "\n", encoding="utf-8")


def _case_from_dict(d: dict) -> BenchCase:
    return BenchCase(
        id=str(d["id"]),
        repo=str(d["repo"]),
        base_commit=str(d["base_commit"]),
        issue_text=str(d["issue_text"]),
        role=str(d.get("role", "engineer")),
        language=str(d.get("language", "python")),
        gold_patch=str(d.get("gold_patch", "")),
        test_patch=str(d.get("test_patch", "")),
        fail_to_pass=tuple(d.get("fail_to_pass", ())),
        pass_to_pass=tuple(d.get("pass_to_pass", ())),
        setup_cmd=str(d.get("setup_cmd", "")),
        test_cmd=str(d.get("test_cmd", "")),
        clone_url=str(d.get("clone_url", "")),
    )


def _as_list(value: object) -> tuple[str, ...]:
    """SWE-bench stores FAIL_TO_PASS/PASS_TO_PASS as a JSON-encoded list *string* — decode leniently."""
    if isinstance(value, list):
        return tuple(str(v) for v in value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return tuple(str(v) for v in parsed)
        except json.JSONDecodeError:
            return ()
    return ()


def import_swebench_lite(
    *, limit: int = 20, split: str = "test", offset: int = 0, timeout_s: float = 60.0
) -> list[BenchCase]:
    """Import up to ``limit`` cases from SWE-bench Lite via the HF datasets-server (Python cases).

    Paginates the datasets-server (100 rows/request). Each row becomes a Python ``BenchCase`` with the
    ``engineer`` role and a ``pytest`` objective oracle; the specific FAIL_TO_PASS/PASS_TO_PASS node ids
    are what the oracle actually runs.
    """
    cases: list[BenchCase] = []
    fetched = 0
    with httpx.Client(timeout=timeout_s) as client:
        while fetched < limit:
            length = min(_HF_PAGE_MAX, limit - fetched)
            resp = client.get(
                _DATASETS_SERVER,
                params={
                    "dataset": "princeton-nlp/SWE-bench_Lite",
                    "config": "default",
                    "split": split,
                    "offset": offset + fetched,
                    "length": length,
                },
            )
            resp.raise_for_status()
            rows = resp.json().get("rows", [])
            if not rows:
                break
            for entry in rows:
                r = entry.get("row", {})
                cases.append(
                    BenchCase(
                        id=str(r.get("instance_id", "")),
                        repo=str(r.get("repo", "")),
                        base_commit=str(r.get("base_commit", "")),
                        issue_text=str(r.get("problem_statement", "")),
                        role="engineer",
                        language="python",
                        gold_patch=str(r.get("patch", "")),
                        test_patch=str(r.get("test_patch", "")),
                        fail_to_pass=_as_list(r.get("FAIL_TO_PASS")),
                        pass_to_pass=_as_list(r.get("PASS_TO_PASS")),
                        setup_cmd="pip install -e .",
                        test_cmd="pytest",
                    )
                )
            fetched += len(rows)
            if len(rows) < length:
                break
    return cases[:limit]
