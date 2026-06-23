"""Contract-derived decomposition — fan the goal out into one task per declared module (spec 15, B).

The manager authors ``AGENTS.md`` (module map · public API · ownership · dependencies); the kernel then
derives the work breakdown FROM that contract rather than from a hand-written children list: one ledger
task per declared SOURCE module, assigned to its declared owner, wired with ``depends_on`` from the
dependency DAG (so an importer branches off a main that already carries what it imports). This makes
"one small task per module, ordered by imports" structural — the manager cannot bundle the hard module
in with three others, because it does not write the children at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from chorus.coherence import AgentsMd
from chorus.lifecycle._capability import ChildPlan


@dataclass(frozen=True)
class DerivedPlan:
    """The outcome of deriving children from a contract: the per-module plans + any unowned modules."""

    plans: tuple[ChildPlan, ...]
    unowned: tuple[str, ...]  # declared source modules with no owner — the manager must fix the contract


def _label(module: str) -> str:
    """A stable, unique child label from a module path (``prefrank/model.py`` -> ``prefrank-model-py``)."""
    return module.replace("/", "-").replace(".", "-")


def _is_test(module: str) -> bool:
    name = module.replace("\\", "/").rsplit("/", 1)[-1]
    return (
        "/tests/" in f"/{module}" or name.startswith("test_") or name.endswith("_test.py")
    )


def _intent(module: str, deps: tuple[str, ...]) -> str:
    builds_on = ", ".join(f"`{d}`" for d in deps) if deps else "none"
    return (
        f"Implement `{module}` exactly as declared in AGENTS.md (which is on company main). Build this "
        f"ONE file and its OWN tests, providing the part of the public API it owns. Work test-first. "
        f"Make the `acceptance/` suite pass and NEVER edit it. Modules it builds on (already merged to "
        f"main, import them directly): {builds_on}."
    )


def child_plans_from_contract(doc: AgentsMd) -> DerivedPlan:
    """Derive one :class:`ChildPlan` per declared source module — owner + ``depends_on`` from the contract.

    ``__init__`` re-exports the whole public API, so it depends on every other source module (it lands
    last). A module with no declared owner is returned in ``unowned`` so the caller can refuse and have
    the manager complete the contract rather than silently drop the work.
    """
    source = [m for m in doc.modules if m.endswith(".py") and not _is_test(m)]
    label_of = {m: _label(m) for m in source}
    others = [m for m in source if not m.endswith("__init__.py")]

    plans: list[ChildPlan] = []
    unowned: list[str] = []
    for module in source:
        owner = doc.ownership.get(module)
        if owner is None:
            unowned.append(module)
            continue
        deps = set(doc.dependencies.get(module, ()))
        if module.endswith("__init__.py"):
            deps |= set(others)  # the package entry re-exports every module → build it last
        ordered_deps = tuple(d for d in source if d in deps)  # stable, declaration order
        dep_labels = tuple(label_of[d] for d in ordered_deps if d in label_of)
        plans.append(
            ChildPlan(
                label=label_of[module],
                intent=_intent(module, ordered_deps),
                assignee=owner,
                depends_on=dep_labels,
            )
        )
    return DerivedPlan(plans=tuple(plans), unowned=tuple(unowned))


__all__ = ["DerivedPlan", "child_plans_from_contract"]
