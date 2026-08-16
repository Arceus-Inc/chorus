"""Deliverable-kind resolution of a task's Definition of Done (fixes the role↔task DoD coupling).

A role's ``dod_generator(intent)`` only knows how to judge *its own craft's* deliverables — an
analyst classifies its intent among analyst outputs (findings / prediction / recommendation), a
frontend engineer always emits a code floor. That is correct when an employee does its canonical
job. It is **wrong the moment a lead cross-assigns**: give an ``analyst`` a "write Playwright e2e
tests" task and ``analyst_dod`` falls through to its default ``findings.md`` rubric, so correct
test work is rejected for not being a findings report.

First principle: *the deliverable a task owes is a property of the work order, not the worker.*
So the DoD is selected by the **deliverable kind** classified from the intent, and the role's own
generator is used only when the task is within the role's craft (or the kind is ambiguous). A
cross-craft assignment is judged by that deliverable's own standard, independent of who holds it.

The role's *native* kind is derived from the artifact class its own default DoD emits — no role
plugin needs to declare anything. Classification is conservative: it returns :data:`ROLE_DEFAULT`
for anything but a strong, unambiguous cross-craft signal, so canonical work is never re-routed.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import TYPE_CHECKING

from chorus.outcomes._verifier import Verifier

if TYPE_CHECKING:
    from chorus.roles import RoleRegistry
    from chorus.roles._plugin import RolePlugin


class DeliverableKind(StrEnum):
    """What a task asks to be produced — the axis a Definition of Done is chosen on."""

    ROLE_DEFAULT = "role_default"  # ambiguous or in-craft → defer to the assignee's role generator
    CODE = "code"  # a runnable implementation (app / service / module)
    TESTS = "tests"  # a test suite + captured evidence
    DESIGN = "design"  # a design system / visual spec / UX artifact
    WRITEUP = "writeup"  # a written guide / doc / copy / plan (no code)
    ANALYSIS = "analysis"  # an evidence-backed findings / data answer
    DECISION = "decision"  # a recommendation a human signs off on


# --- classification -------------------------------------------------------------------------------

# Cue phrases per kind, most-gated first. A DECISION (human sign-off) dominates; then TESTS — the
# most specific and the case that motivated this module; then the remaining craft signals. Cues are
# deliberately STRONG and specific: a bare "test" or "design" would false-fire on ordinary prose, so
# only tool names and unmistakable phrases are listed. Everything else falls through to ROLE_DEFAULT.
_CUES: tuple[tuple[DeliverableKind, tuple[str, ...]], ...] = (
    (
        DeliverableKind.DECISION,
        ("recommend", "recommendation", "go/no-go", "go no-go", "should we", "make the call"),
    ),
    (
        DeliverableKind.TESTS,
        (
            "playwright", "cypress", "vitest", "jest", "pytest", "mocha",
            "e2e test", "e2e tests", "end-to-end test", "unit test", "unit tests",
            "integration test", "integration tests", "test suite", "test coverage",
            "write tests", "add tests", "author tests", "regression test", "test harness",
        ),
    ),
    (
        DeliverableKind.DESIGN,
        (
            "design system", "visual theme", "visual design", "wireframe", "mockup",
            "style guide", "design spec", "ux flow", "user experience", "color token",
            "color tokens", "typography scale", "component library",
        ),
    ),
    (
        DeliverableKind.WRITEUP,
        (
            "brand guide", "voice guide", "tone of voice", "content plan", "blog post",
            "blog outline", "marketing copy", "copywriting", "landing-page copy", "documentation",
            "user guide", "readme", "runbook", "playbook", "seo plan", "launch calendar",
            "go-to-market", "gtm plan", "write a guide", "written guide",
        ),
    ),
    (
        DeliverableKind.CODE,
        (
            "implement", "build the app", "build a web", "web app", "npm run", "npm script",
            "rest api", "api endpoint", "endpoint", "the component", "refactor", "the module",
            "ship runnable",
        ),
    ),
    (
        DeliverableKind.ANALYSIS,
        (
            "analyze", "analysis", "investigate", "root cause", "data analysis",
            "findings.md", "benchmark", "quantify",
        ),
    ),
)


def _matcher(cues: tuple[str, ...]) -> re.Pattern[str]:
    """Whole-word/phrase matcher (optional trailing ``s``), so substrings don't false-match."""
    alternation = "|".join(re.escape(cue) for cue in cues)
    return re.compile(rf"(?<!\w)(?:{alternation})s?(?!\w)")


_COMPILED: tuple[tuple[DeliverableKind, re.Pattern[str]], ...] = tuple(
    (kind, _matcher(cues)) for kind, cues in _CUES
)


def classify_deliverable(intent: str) -> DeliverableKind:
    """Infer the deliverable kind from a task intent; ROLE_DEFAULT unless a strong cue matches."""
    text = intent.lower()
    for kind, pattern in _COMPILED:
        if pattern.search(text):
            return kind
    return DeliverableKind.ROLE_DEFAULT


# --- deliverable-kind verifiers (role-independent) ------------------------------------------------

_CONVERGENCE = (
    "Hold a CONVERGENCE bar: PASS as soon as the task's deliverable is materially present and "
    "correct; approve work that satisfies what the task asked even if it could be marginally "
    "improved, and never withhold approval for stylistic polish or belt-and-suspenders evidence the "
    "task did not require. You are read-only: use `read_file` to inspect the committed artifacts and "
    "assess their content; never claim you cannot verify. FAIL only for a CONCRETE defect, and when "
    "you fail, name the specific fix so the next attempt can converge."
)

_TESTS_RUBRIC = (
    "You are judging a FINISHED deliverable: an automated test suite plus its captured evidence. "
    "Use `read_file` to inspect the committed test files (e.g. under `e2e/`, `tests/`, or "
    "`*.spec.*`/`*.test.*`), the runner config, and any evidence the task asked for "
    "(a `test_evidence/` summary, results, screenshots, or traces). PASS when the tests exist, "
    "target the specific behaviours the task named, are runnable as written (a real runner config "
    "and script are present), and the committed evidence shows them exercised. Judge the COMMITTED "
    "test + evidence files as the proof — do NOT require re-running the suite yourself or demand a "
    "process artifact the task did not ask for. " + _CONVERGENCE
)

_CODE_RUBRIC = (
    "You are judging a FINISHED deliverable: a runnable implementation. Use `read_file` to inspect "
    "the committed source, its entry points, and its build/run manifest (e.g. `package.json`), plus "
    "any tests or evidence the task named. PASS when the implementation covers the behaviours the "
    "task asked for, is internally coherent, and is runnable as written (a real build/run script "
    "and its dependencies are declared). Judge the committed files as the proof. " + _CONVERGENCE
)

_DESIGN_RUBRIC = (
    "You are judging a FINISHED deliverable: a design artifact (a design system, visual spec, or UX "
    "definition). Use `read_file` to inspect the committed design document(s). PASS when it defines "
    "the specific surfaces the task asked for (e.g. tokens, type scale, spacing, component states) "
    "concretely enough to build against, with accessible defaults where relevant. " + _CONVERGENCE
)

_WRITEUP_RUBRIC = (
    "You are judging a FINISHED deliverable: a written document (guide, plan, copy, or "
    "documentation — no code). Use `read_file` to read the committed document(s). PASS when the "
    "document answers every part of what the task asked with specific, concrete, internally "
    "consistent content and the structure the task named. " + _CONVERGENCE
)

_ANALYSIS_RUBRIC = (
    "You are judging a FINISHED deliverable: an evidence-backed written answer (typically "
    "`findings.md`). Use `read_file` to read it. PASS when it answers every part of the task's "
    "question with specific, sourced, internally consistent conclusions. Judge citations by "
    "substance, not format; a source you cannot personally re-fetch is not grounds to fail. "
    + _CONVERGENCE
)


def _cross_verifier(kind: DeliverableKind) -> Verifier | None:
    """A role-independent verifier for a cross-craft deliverable; None for kinds with no override."""
    if kind is DeliverableKind.TESTS:
        return Verifier.agent_review(rubric=_TESTS_RUBRIC, artifact_class="tests")
    if kind is DeliverableKind.CODE:
        return Verifier.agent_review(rubric=_CODE_RUBRIC, artifact_class="pr")
    if kind is DeliverableKind.DESIGN:
        return Verifier.agent_review(rubric=_DESIGN_RUBRIC, artifact_class="design")
    if kind is DeliverableKind.WRITEUP:
        return Verifier.agent_review(rubric=_WRITEUP_RUBRIC, artifact_class="doc")
    if kind is DeliverableKind.ANALYSIS:
        return Verifier.agent_review(rubric=_ANALYSIS_RUBRIC, artifact_class="finding")
    if kind is DeliverableKind.DECISION:
        return Verifier.human_approval(artifact_class="recommendation")
    return None


# --- role native kind + resolution ---------------------------------------------------------------

# A neutral, craft-agnostic probe: it names no deliverable, so a role generator returns its DEFAULT
# verifier, whose artifact class reveals the role's native deliverable kind.
_NEUTRAL_PROBE = "complete the assigned work to its definition of done"

_ARTIFACT_CLASS_TO_KIND: dict[str, DeliverableKind] = {
    "pr": DeliverableKind.CODE,
    "tests": DeliverableKind.TESTS,
    "design": DeliverableKind.DESIGN,
    "content": DeliverableKind.WRITEUP,
    "doc": DeliverableKind.WRITEUP,
    "spec": DeliverableKind.WRITEUP,
    "directive": DeliverableKind.WRITEUP,
    "finding": DeliverableKind.ANALYSIS,
    "prediction": DeliverableKind.ANALYSIS,
    "recommendation": DeliverableKind.DECISION,
    "commitment": DeliverableKind.DECISION,
}

_NATIVE_KIND_CACHE: dict[int, DeliverableKind] = {}


def _role_native_kind(plugin: RolePlugin) -> DeliverableKind:
    """The deliverable kind the role produces by default — inferred from its own DoD, cached."""
    key = id(plugin.dod_generator)
    cached = _NATIVE_KIND_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        native = _ARTIFACT_CLASS_TO_KIND.get(
            plugin.dod_generator(_NEUTRAL_PROBE).artifact_class, DeliverableKind.ROLE_DEFAULT
        )
    except Exception:
        native = DeliverableKind.ROLE_DEFAULT
    _NATIVE_KIND_CACHE[key] = native
    return native


def native_kind_for_role(role: str, roles: RoleRegistry) -> DeliverableKind:
    """The deliverable kind a role produces by default — its own DoD's artifact class, no lookup table.

    ``ROLE_DEFAULT`` for an unknown role or one whose default DoD maps to no craft kind, so a caller
    treats it as a generalist (never a mismatch). This is the read side of capability matching: it lets
    a router compare *what a task asks for* (:func:`classify_deliverable`) against *what a worker makes*
    without any hardcoded role→kind mapping — both are derived from the same role registry.
    """
    if role not in roles:
        return DeliverableKind.ROLE_DEFAULT
    return _role_native_kind(roles.get(role))


def resolve_delivery_verifier(intent: str, plugin: RolePlugin) -> Verifier:
    """Select a delivery task's DoD by the deliverable it owes, not the assignee's role.

    In-craft work (or an ambiguous intent) uses the role's own generator — it knows its craft best.
    A task whose deliverable kind differs from the role's native kind is judged by that
    deliverable's own standard, so a lead can cross-assign without the acceptance test rejecting
    correct work.
    """
    kind = classify_deliverable(intent)
    if kind is DeliverableKind.ROLE_DEFAULT or kind is _role_native_kind(plugin):
        return plugin.dod_generator(intent)
    cross = _cross_verifier(kind)
    return cross if cross is not None else plugin.dod_generator(intent)


__all__ = [
    "DeliverableKind",
    "classify_deliverable",
    "native_kind_for_role",
    "resolve_delivery_verifier",
]
