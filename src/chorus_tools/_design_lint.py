"""``design_lint`` — the Design-Critic's deterministic pre-gen scan (designer §08 tool, §10 sandwich).

A read-only verb that scans a drafted ``design.md`` against the project's design system (``DESIGN.md``)
and returns structured findings of three kinds: **off-token colours**, **off-scale spacing**, and
mechanical **accessibility gaps** (an interactive element described with no nearby a11y note). It is
fully deterministic (no model, no network) — the *mechanical* half of the validation sandwich the
Design-Critic reasons over. The "design system" is the local ``DESIGN.md`` (designer §10); there is no
external integration. This is the exact structural analog of ``brand_lint`` re-pointed onto the design
substrate: brand → design system, prohibited-phrase → off-token value, unsubstantiated-claim → a11y gap.

Harness contract (agent-harness-construction): a narrow typed input, a deterministic output shape
(``status`` / ``summary`` / ``findings`` / ``next_actions`` / ``artifacts``), and an explicit recovery
contract (``root_cause`` / ``safe_retry`` / ``stop_condition``) on every error path. The pure helpers
:func:`parse_design_tokens` and :func:`lint_design` carry the logic and are model-free unit-tested.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel, Field, ValidationError

FindingKind = Literal["off_token_color", "off_scale_spacing", "missing_a11y_note"]

# A hex colour literal: #rgb, #rrggbb, or #rrggbbaa (case-insensitive).
_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
# A pixel value stated as a number immediately followed by ``px``.
_PX = re.compile(r"\b(\d+)px\b")
# Interactive elements whose accessibility is not free — a screen with these must say how they behave
# (focus, keyboard, ARIA). Whole-word so "tab" does not fire inside "table", "radio" inside "radios".
_INTERACTIVE = re.compile(
    r"\b(?:button|dialog|modal|input|menu|dropdown|select|checkbox|toggle|tooltip|tab|"
    r"accordion|link|slider|switch|radio|combobox|listbox|popover)\b",
    re.IGNORECASE,
)
# The accessibility cues that discharge the obligation: any of these near the element means the design
# already accounts for it. Deliberately advisory — the Design-Critic adjudicates false positives.
_A11Y_CUE = re.compile(
    r"aria|role\s*=|\blabel|\bfocus|keyboard|tabindex|\balt\s*=|screen\s*reader|sr-only|"
    r"accessible\s+name|\besc\b|dismiss",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class DesignTokens:
    """The machine-readable half of a ``DESIGN.md`` — the contract ``design_lint`` checks against.

    ``colors`` are lower-cased hex literals; ``spacing`` the allowed pixel scale; ``contrast_min`` the
    a11y floor (advisory here — used by the Critic, not mechanically computable from prose).
    """

    colors: frozenset[str] = field(default_factory=frozenset)
    spacing: frozenset[int] = field(default_factory=frozenset)
    contrast_min: float | None = None

    @classmethod
    def empty(cls) -> DesignTokens:
        """A null contract — no system to judge against (a missing/absent ``DESIGN.md``)."""
        return cls()

    @property
    def is_empty(self) -> bool:
        """True when there is no token contract, so off-token/off-scale checks must be skipped."""
        return not self.colors and not self.spacing


@dataclass(frozen=True, slots=True)
class DesignFinding:
    """One deterministic lint finding — immutable, JSON-serialisable via :meth:`as_dict`."""

    kind: FindingKind
    line: int  # 1-based line number in the design.md
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


def parse_design_tokens(system_text: str) -> DesignTokens:
    """Extract the token contract from a ``DESIGN.md``'s leading ``---``-delimited frontmatter block.

    Collects every hex colour in the block into the palette, the ``space.scale: [...]`` list into the
    spacing scale, and ``a11y.contrast.min: N`` into the contrast floor. Only the FIRST ``---`` block is
    the contract — a hex mentioned later in prose is not a token. Returns :meth:`DesignTokens.empty`
    when there is no frontmatter block (a missing contract degrades, never blinds — designer §10).
    """
    block = _first_frontmatter_block(system_text)
    if block is None:
        return DesignTokens.empty()

    colors = frozenset(m.group(0).lower() for m in _HEX.finditer(block))

    spacing: frozenset[int] = frozenset()
    scale_match = re.search(r"space\.scale\s*:\s*\[([^\]]*)\]", block, re.IGNORECASE)
    if scale_match:
        spacing = frozenset(int(tok) for tok in re.findall(r"\d+", scale_match.group(1)))

    contrast_min: float | None = None
    contrast_match = re.search(
        r"a11y\.contrast\.min\s*:\s*([0-9]+(?:\.[0-9]+)?)", block, re.IGNORECASE
    )
    if contrast_match:
        contrast_min = float(contrast_match.group(1))

    return DesignTokens(colors=colors, spacing=spacing, contrast_min=contrast_min)


def _first_frontmatter_block(text: str) -> str | None:
    """Return the body of the first ``---`` ... ``---`` fence, or ``None`` if there isn't one."""
    lines = text.splitlines()
    start: int | None = None
    for i, line in enumerate(lines):
        if line.strip() == "---":
            if start is None:
                start = i
            else:
                return "\n".join(lines[start + 1 : i])
    return None


def lint_design(doc_text: str, tokens: DesignTokens) -> tuple[DesignFinding, ...]:
    """Scan ``doc_text`` line by line against ``tokens``; return findings sorted by (line, kind).

    Deterministic. Off-token colour and off-scale spacing fire only when there IS a contract to judge
    against (``tokens`` non-empty); the a11y heuristic always runs. Mirrors ``brand_lint.lint_text``.
    """
    findings: list[DesignFinding] = []
    for line_no, line in enumerate(doc_text.splitlines(), start=1):
        stripped = line.strip()

        if not tokens.is_empty:
            for hex_match in _HEX.finditer(line):
                literal = hex_match.group(0)
                if literal.lower() not in tokens.colors:
                    findings.append(
                        DesignFinding(
                            kind="off_token_color",
                            line=line_no,
                            quote=stripped,
                            rule=f"colour {literal} is not on the DESIGN.md token scale",
                            fix="use a colour token from DESIGN.md; never hard-code an off-scale hex",
                        )
                    )
            for px_match in _PX.finditer(line):
                value = int(px_match.group(1))
                if tokens.spacing and value not in tokens.spacing:
                    findings.append(
                        DesignFinding(
                            kind="off_scale_spacing",
                            line=line_no,
                            quote=stripped,
                            rule=f"{value}px is not on the DESIGN.md spacing scale",
                            fix="snap to the nearest value on space.scale in DESIGN.md",
                        )
                    )

        if _INTERACTIVE.search(line) and not _A11Y_CUE.search(line):
            findings.append(
                DesignFinding(
                    kind="missing_a11y_note",
                    line=line_no,
                    quote=stripped,
                    rule="an interactive element is described with no accessibility note",
                    fix="state focus order, the ARIA role/label, and keyboard behaviour for it",
                )
            )

    findings.sort(key=lambda f: (f.line, f.kind))
    return tuple(findings)


class DesignLintInput(BaseModel):
    """Typed contract for ``design_lint`` — validated before any file is read."""

    doc: str = Field(min_length=1, description="the drafted design spec to lint, e.g. 'design.md'")
    system: str = Field(
        default="DESIGN.md", description="the design-system contract (tokens + guardrails)"
    )


class DesignLintTool(BaseTool):
    """Deterministically lint a design spec against the design system — read-only, no model, no net."""

    name = "design_lint"
    description = (
        "Deterministically scan a drafted design spec for on-system + accessibility violations: "
        "off-token colours, off-scale spacing, and interactive elements described with no accessibility "
        "note (focus / ARIA / keyboard). Read-only; returns structured findings with line numbers and "
        "fixes. Run this FIRST for the mechanical pass, then reason over its findings. Args: doc (the "
        "design spec), system (default 'DESIGN.md')."
    )
    declaration = ToolDeclaration(risk="safe", tier_required=0, timeout_seconds=15.0)
    input_model = DesignLintInput

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        try:
            args = DesignLintInput.model_validate(input)
        except ValidationError as exc:
            return _rejected(str(exc))

        doc_path = ctx.working_dir / args.doc
        if not doc_path.is_file():
            return ToolResult(
                content=f"design_lint: nothing to lint — {args.doc!r} not found.",
                is_error=True,
                metadata={
                    "root_cause": f"doc {args.doc!r} not found in the worktree",
                    "safe_retry": "write the design spec first, then lint it",
                    "stop_condition": "nothing to lint until the design spec exists",
                },
            )

        system_path = ctx.working_dir / args.system
        if system_path.is_file():
            tokens = parse_design_tokens(system_path.read_text(encoding="utf-8"))
            system_note = (
                ""
                if not tokens.is_empty
                else (f" (system {args.system!r} has no token block — judged a11y only)")
            )
        else:
            tokens = DesignTokens.empty()
            system_note = (
                f" (system {args.system!r} not found — judged a11y only, off-token checks skipped)"
            )

        findings = lint_design(doc_path.read_text(encoding="utf-8"), tokens)
        return _report(args, findings, system_note)


def _report(
    args: DesignLintInput, findings: tuple[DesignFinding, ...], system_note: str
) -> ToolResult:
    color_n = sum(1 for f in findings if f.kind == "off_token_color")
    space_n = sum(1 for f in findings if f.kind == "off_scale_spacing")
    a11y_n = sum(1 for f in findings if f.kind == "missing_a11y_note")
    if findings:
        summary = (
            f"design_lint: {color_n} off-token colour(s), {space_n} off-scale spacing, "
            f"{a11y_n} a11y gap(s) — {len(findings)} finding(s){system_note}"
        )
        hard_n = color_n + space_n
        next_actions = [
            (
                f"HARD findings: fix the {hard_n} off-token colour/off-scale spacing breach(es) — "
                "swap each for a token DESIGN.md declares. These must reach zero."
                if hard_n
                else "No hard on-system breaches — colours and spacing are on-scale."
            ),
            (
                f"ADVISORY: the {a11y_n} a11y finding(s) are heuristic (an interactive element named "
                "with no a11y cue on the same line — it over-fires on prose and won't reach zero on a "
                "rich spec). Clear the genuine gaps, then let the Design-Critic adjudicate the rest — "
                "do NOT loop lint→edit to chase this count to zero."
                if a11y_n
                else "No mechanical a11y gaps flagged."
            ),
        ]
        detail = "\n".join(f"  L{f.line} [{f.kind}] {f.quote}  → {f.fix}" for f in findings)
        content = f"{summary}\n{detail}"
    else:
        summary = f"design_lint: clean — on-system and no mechanical a11y gaps{system_note}"
        next_actions = [
            "Design is mechanically on-system; proceed with the Design-Critic's judgment."
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
            "artifacts": {"doc": args.doc, "system": args.system},
        },
    )


def _rejected(message: str) -> ToolResult:
    return ToolResult(
        content=f"design_lint rejected: {message}",
        is_error=True,
        metadata={
            "root_cause": message,
            "safe_retry": "provide a non-empty 'doc' path (and optional 'system'); both are read from the worktree",
            "stop_condition": "the tool input was invalid",
        },
    )


__all__ = [
    "DesignFinding",
    "DesignLintInput",
    "DesignLintTool",
    "DesignTokens",
    "lint_design",
    "parse_design_tokens",
]
