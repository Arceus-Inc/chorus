"""Shared guards for cohesive runnable-app delegation."""

from __future__ import annotations

from chorus.lifecycle import ChildPlan

_PM_ROLES = {"pm", "product_manager", "product manager"}


def looks_like_cohesive_app(intent: str) -> bool:
    text = intent.lower()
    has_app_shape = (
        "full-stack" in text
        or "fullstack" in text
        or "websocket" in text
        or "runnable application" in text
    )
    has_single_repo_gate = (
        "one repo" in text
        or "one-repo" in text
        or "single repo" in text
        or "single-repo" in text
        or "one repository" in text
        or "one runnable application" in text
        or "one-command" in text
        or "single gate" in text
        or "single-gate" in text
        or "single root" in text
        or "root gate" in text
        or "one command" in text
        or "clean checkout" in text
    )
    return has_app_shape and has_single_repo_gate


def looks_like_sidecar_child(child: ChildPlan, role: str | None) -> bool:
    text = f"{child.label} {child.intent}".lower()
    return role in _PM_ROLES or any(
        word in text
        for word in ("plan", "spec", "gate", "ci", "proof", "test", "tests", "verify", "verification", "qa")
    )


def looks_like_incremental_sidecar(child: ChildPlan, role: str | None) -> bool:
    """Return True for non-product follow-up work that should not split a cohesive app.

    Managers may submit one missing repair/build task during integration. For cohesive runnable apps,
    that follow-up still needs to be product work in an engineer worktree; PM plan/spec/gate-only
    sidecars recreate the same split the decomposition guard prevents.
    """
    if role in _PM_ROLES:
        return True

    label = child.label.lower()
    text = f"{label} {child.intent}".lower()
    if "do not modify source" in text or "implementation plan only" in text:
        return True

    sidecar_terms = ("plan", "spec", "verify", "verification", "gate", "ci", "review", "qa")
    product_terms = (
        "build",
        "implement",
        "deliver",
        "repair",
        "fix",
        "server",
        "client",
        "frontend",
        "backend",
        "schema",
        "websocket",
        "react",
        "test",
    )
    return any(term in label for term in sidecar_terms) and not any(
        term in label for term in product_terms
    )


__all__ = [
    "looks_like_cohesive_app",
    "looks_like_incremental_sidecar",
    "looks_like_sidecar_child",
]