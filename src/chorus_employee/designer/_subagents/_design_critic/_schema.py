"""The Design-Critic subagent's typed return contract (designer §06, §10).

The Design-Critic judges the Designer's ``design_spec.md`` against ``DESIGN.md`` and returns a
:class:`DesignVerdict` — a decisive ``PASS``/``FAIL`` plus one :class:`DesignViolation` per real
breach it found (each naming the offending ``element``, the ``rule`` it breaks, and a concrete
``fix``). ``violations`` is empty on ``PASS``; ``notes`` carries a concise summary (e.g. "no
DESIGN.md found" on a fail-closed miss).

Pydantic models are the single source of truth (mirroring the Brand-Critic's contract):
:func:`design_verdict_output_schema` *derives* the JSON schema the subagent's ``output_schema``
enforces via :meth:`~pydantic.BaseModel.model_json_schema` (dream's ``jsonschema`` validator
resolves its ``$ref``/``$defs``), and a caller parses the raw return with
:meth:`DesignVerdict.model_validate` — no hand-written schema to drift.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DesignViolation(BaseModel):
    """One real design breach — the offending element, the rule, its severity, and a concrete fix."""

    model_config = ConfigDict(str_strip_whitespace=True)

    element: str = Field(
        min_length=1,
        description="the offending element, token, or line quoted verbatim from the spec",
    )
    rule: str = Field(
        min_length=1,
        description="the design-system or accessibility rule this element breaches",
    )
    severity: Literal["blocker", "major", "minor"] = Field(
        description=(
            "how much it matters: 'blocker' ships a broken or inaccessible screen (off-system value "
            "where a token exists, a control with no a11y treatment, a WCAG contrast failure); 'major' "
            "is a missing state or a structural breach of the system; 'minor' is advisory polish. Any "
            "open blocker or major forces a FAIL."
        )
    )
    fix: str = Field(min_length=1, description="a concrete suggested fix for the element")


class DesignVerdict(BaseModel):
    """Design-Critic's return value: the decisive verdict plus every real violation behind it."""

    model_config = ConfigDict(str_strip_whitespace=True)

    verdict: Literal["PASS", "FAIL"] = Field(
        description=(
            "FAIL when any blocker or major violation is open; PASS when only minors remain or none "
            "do — the bar is 'on-system and accessible', not 'perfect'"
        )
    )
    violations: list[DesignViolation] = Field(
        description="each real violation found, severity-tagged; empty on a clean PASS"
    )
    strengths: list[str] = Field(
        default_factory=list,
        description=(
            "what the spec gets RIGHT — on-system choices, complete states, sound a11y — so the "
            "designer converges the loop without regressing what already works"
        ),
    )
    notes: str = Field(
        default="",
        description="optional concise summary, e.g. 'no DESIGN.md found' on a fail-closed miss",
    )


def design_verdict_output_schema() -> dict[str, Any]:
    """The JSON schema handed to the Design-Critic's ``output_schema`` — derived from the model."""
    return DesignVerdict.model_json_schema()


__all__ = ["DesignVerdict", "DesignViolation", "design_verdict_output_schema"]
