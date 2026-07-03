"""``brand_lint`` — the Brand-Critic's deterministic pre-gen scan (design doc §08 tool, §10 sandwich).

A read-only verb that scans a drafted content file against the brand voice rules and returns structured
findings of two kinds: **prohibited phrases** and **unsubstantiated claims**. It is fully deterministic
(no model, no network) — the *mechanical* half of the validation sandwich the Brand-Critic reasons
over. The "brand kit" is the local ``brand_spec.md``; there is no external integration.

Harness contract (agent-harness-construction): a narrow typed input, a deterministic output shape
(``status`` / ``summary`` / ``findings`` / ``next_actions`` / ``artifacts``), and an explicit recovery
contract (``root_cause`` / ``safe_retry`` / ``stop_condition``) on every error path. The pure helpers
:func:`parse_prohibited_phrases` and :func:`lint_text` carry the logic and are model-free unit-tested.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel, Field, ValidationError

FindingKind = Literal["prohibited_phrase", "unsubstantiated_claim"]

# Fallback when the spec has no ``## Prohibited Phrases`` section — a missing brand kit should degrade,
# never blind the critic.
_DEFAULT_PROHIBITED: tuple[str, ...] = (
    "revolutionary",
    "game-changing",
    "10x",
    "unlock",
    "supercharge",
    "best-in-class",
    "cutting-edge",
    "seamless",
    "effortless",
)

# Claim heuristic (deliberately advisory — the Brand-Critic adjudicates false positives).
_METRIC = re.compile(r"\d+%|\$\s?\d|\b\d+(?:\.\d+)?x\b|\b\d{2,}\b")
_GUARANTEE = re.compile(
    r"\b(?:will|guarantees?|ensures?|eliminates?|never|always)\b", re.IGNORECASE
)
_HEDGE = re.compile(
    r"we believe|early results suggest|designed to|aims? to|can help|\b(?:may|could|might)\b",
    re.IGNORECASE,
)
_CITATION = re.compile(
    r"\[\d+\]|https?://|according to|\(source|\b\w+\.(?:com|io|org|ai|dev)\b", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class BrandFinding:
    """One deterministic lint finding — immutable, JSON-serialisable via :meth:`as_dict`."""

    kind: FindingKind
    line: int  # 1-based line number in the draft
    quote: str  # the offending text
    rule: str  # which rule fired
    fix: str  # a concrete, actionable remedy

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "line": self.line,
            "quote": self.quote,
            "rule": self.rule,
            "fix": self.fix,
        }


def parse_prohibited_phrases(spec_text: str) -> tuple[str, ...]:
    """Extract the prohibited-phrase list from a brand spec's ``## Prohibited Phrases`` section.

    Collects the comma-separated bullets under that heading (case-insensitive), de-duplicated and
    lower-cased. Falls back to :data:`_DEFAULT_PROHIBITED` when the section is absent.
    """
    collected: dict[str, None] = {}
    in_section = False
    for line in spec_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("##"):
            in_section = stripped.lstrip("#").strip().lower() == "prohibited phrases"
            continue
        if in_section and stripped:
            for token in stripped.lstrip("-*").strip().split(","):
                phrase = token.strip().lower()
                if phrase:
                    collected.setdefault(phrase, None)
    return tuple(collected) if collected else _DEFAULT_PROHIBITED


def _contains_phrase(lower_line: str, phrase: str) -> bool:
    """Whole-token, case-insensitive match (so 'unlock' does not fire on 'unlockable')."""
    return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", lower_line) is not None


def _is_unsubstantiated(line: str) -> bool:
    """A metric or an outcome guarantee, stated with neither a hedge nor a citation."""
    if _HEDGE.search(line) or _CITATION.search(line):
        return False
    return bool(_METRIC.search(line) or _GUARANTEE.search(line))


def lint_text(doc_text: str, phrases: tuple[str, ...]) -> tuple[BrandFinding, ...]:
    """Scan ``doc_text`` line by line; return findings sorted by (line, kind). Deterministic."""
    findings: list[BrandFinding] = []
    for line_no, line in enumerate(doc_text.splitlines(), start=1):
        lower = line.lower()
        for phrase in phrases:
            if _contains_phrase(lower, phrase):
                findings.append(
                    BrandFinding(
                        kind="prohibited_phrase",
                        line=line_no,
                        quote=line.strip(),
                        rule=f"prohibited phrase {phrase!r}",
                        fix=f"remove or replace {phrase!r} with a plain, specific description",
                    )
                )
        if _is_unsubstantiated(line):
            findings.append(
                BrandFinding(
                    kind="unsubstantiated_claim",
                    line=line_no,
                    quote=line.strip(),
                    rule="a metric or outcome is stated as fact without a hedge or a source",
                    fix="hedge it ('we believe' / 'early results suggest') or cite the source inline",
                )
            )
    findings.sort(key=lambda f: (f.line, f.kind))
    return tuple(findings)


class BrandLintInput(BaseModel):
    """Typed contract for ``brand_lint`` — validated before any file is read."""

    doc: str = Field(
        min_length=1, description="the drafted content file to lint, e.g. 'content_draft.md'"
    )
    spec: str = Field(
        default="brand_spec.md", description="the brand-voice spec (the local brand kit)"
    )


class BrandLintTool(BaseTool):
    """Deterministically lint a draft against the brand voice rules — read-only, no model, no net."""

    name = "brand_lint"
    description = (
        "Deterministically scan a drafted content file for brand violations: prohibited/hype phrases "
        "and unsubstantiated claims (a metric or outcome stated as fact without a hedge or a source). "
        "Read-only; returns structured findings with line numbers and fixes. Run this FIRST for the "
        "mechanical pass, then reason over its findings. Args: doc (the draft), spec (default "
        "'brand_spec.md')."
    )
    declaration = ToolDeclaration(risk="safe", tier_required=0, timeout_seconds=15.0)
    input_model = BrandLintInput

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        try:
            args = BrandLintInput.model_validate(input)
        except ValidationError as exc:
            return _rejected(str(exc))

        doc_path = ctx.working_dir / args.doc
        if not doc_path.is_file():
            return ToolResult(
                content=f"brand_lint: nothing to lint — {args.doc!r} not found.",
                is_error=True,
                metadata={
                    "root_cause": f"doc {args.doc!r} not found in the worktree",
                    "safe_retry": "write the draft first, then lint it",
                    "stop_condition": "nothing to lint until the draft exists",
                },
            )

        spec_path = ctx.working_dir / args.spec
        if spec_path.is_file():
            phrases = parse_prohibited_phrases(spec_path.read_text(encoding="utf-8"))
            spec_note = ""
        else:
            phrases = _DEFAULT_PROHIBITED
            spec_note = (
                f" (spec {args.spec!r} not found — used the built-in prohibited-phrase list)"
            )

        findings = lint_text(doc_path.read_text(encoding="utf-8"), phrases)
        return _report(args, findings, spec_note)


def _report(args: BrandLintInput, findings: tuple[BrandFinding, ...], spec_note: str) -> ToolResult:
    phrase_n = sum(1 for f in findings if f.kind == "prohibited_phrase")
    claim_n = sum(1 for f in findings if f.kind == "unsubstantiated_claim")
    if findings:
        summary = (
            f"brand_lint: {phrase_n} prohibited phrase(s), {claim_n} unsubstantiated claim(s) — "
            f"{len(findings)} finding(s){spec_note}"
        )
        next_actions = [
            "Fix each finding, then re-lint.",
            "Remove prohibited phrases; hedge or cite any flagged claim.",
        ]
        detail = "\n".join(f"  L{f.line} [{f.kind}] {f.quote}  → {f.fix}" for f in findings)
        content = f"{summary}\n{detail}"
    else:
        summary = f"brand_lint: clean — no prohibited phrases or unsubstantiated claims{spec_note}"
        next_actions = [
            "Draft is mechanically clean; proceed with the Brand-Critic's voice judgment."
        ]
        content = summary
    return ToolResult(
        content=content,
        is_error=False,
        metadata={
            "status": "warning" if findings else "success",
            "summary": summary,
            "findings": [f.as_dict() for f in findings],
            "next_actions": next_actions,
            "artifacts": {"doc": args.doc, "spec": args.spec},
        },
    )


def _rejected(message: str) -> ToolResult:
    return ToolResult(
        content=f"brand_lint rejected: {message}",
        is_error=True,
        metadata={
            "root_cause": message,
            "safe_retry": "provide a non-empty 'doc' path (and optional 'spec'); both are read from the worktree",
            "stop_condition": "the tool input was invalid",
        },
    )


__all__ = [
    "BrandFinding",
    "BrandLintInput",
    "BrandLintTool",
    "lint_text",
    "parse_prohibited_phrases",
]
