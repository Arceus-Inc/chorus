"""The contract-first gate + publish, shared by every fan-out tool (spec 15 §4.1).

A manager may fan a goal out with either ``decompose`` (the planned multi-child split) or ``submit_task``
(a single child). BOTH must enforce the same rule: the cross-child contract (``AGENTS.md``) has to be
authored and landed on company ``main`` BEFORE the children are created, so every engineer worktree —
cut at dispatch, after this beat — branches off the real module map / public API / ownership rather than
the seeded placeholder. Centralising the gate here is what makes "can't be skipped" true regardless of
which tool the manager reaches for.
"""

from __future__ import annotations

from pathlib import Path

from dream.contracts.tool import ToolResult

from chorus.coherence import AgentsMd, authored_contract, contract_sha
from chorus.ledger import ActivityVerb, SqliteLedger
from chorus.lifecycle import record_activity
from chorus.scaffold import scaffold_if_missing
from chorus.workspace import ACCEPTANCE_DIR, CompanyWorkspace

# Stack-neutral packaging manifests — published with the contract so the gate installs the deliverable's
# declared third-party dependencies in every worktree (the acceptance test may use them).
_MANIFESTS = ("pyproject.toml", "requirements.txt", "package.json", "Cargo.toml", "go.mod")

_REFUSAL = (
    "refused: AGENTS.md is missing or still the placeholder. Author it YOURSELF, now, in this beat: "
    "call write_file on AGENTS.md at the repo root, replacing every <package>/<Symbol>/<file>/"
    "<employee_id> marker with the REAL module map, public API, and per-file ownership — THEN fan out. "
    "Do NOT create a subtask to author the contract and do NOT delegate it: a child cannot author the "
    "contract its own siblings must build to. write_file AGENTS.md, then call decompose/submit_task again."
)


def contract_gate(working_dir: Path) -> ToolResult | None:
    """Fail closed when the beat's ``AGENTS.md`` is missing or still the placeholder; else ``None``.

    Returns the refusal :class:`ToolResult` a fan-out tool should hand straight back to the model, so the
    manager authors the real contract before any child (and any engineer branch) can exist.
    """
    if authored_contract(working_dir) is None:
        return ToolResult(content=_REFUSAL, is_error=True, structured={"contract_unauthored": True})
    return None


def publish_contract(
    ledger: SqliteLedger, *, working_dir: Path, parent_id: str, actor: str | None
) -> str | None:
    """Land the authored contract on company ``main`` and audit it; return main's sha (spec 15 §4.1).

    Best-effort: when ``working_dir`` is not an isolated company worktree (``<root>/worktrees/<id>`` with
    a sibling ``repo/`` — e.g. a unit test driving a tool directly), there is no main to land on, so the
    git side-effect is skipped and ``None`` returned. Call only after :func:`contract_gate` has passed.
    """
    content = authored_contract(working_dir)
    if content is None:
        return None
    root = working_dir.parent.parent
    if not (root / "repo" / ".git").exists():
        return None
    # Scaffold the project manifest BEFORE fan-out (the manifest-as-module fix): a manager that lists
    # `pyproject.toml`/`Cargo.toml` in the module map would otherwise deadlock — nobody builds it (the
    # derive skips non-source files) yet the gate needs it to install declared deps. Lay it down once
    # from the declared stack (or the goal text) so it exists on main for every engineer branch.
    parent = ledger.tasks.get(parent_id)
    scaffold_if_missing(
        working_dir,
        goal=parent.intent if parent is not None else "",
        declared_modules=AgentsMd.parse(content).modules,
    )
    workspace = CompanyWorkspace(root)
    sha = workspace.publish_to_main(
        "AGENTS.md", content, message="chorus: publish AGENTS.md contract (pre-fan-out)"
    )
    # The manager-authored acceptance suite is part of the contract — land it on main too so engineers
    # branch off the goal's RED bar (spec 15 §4.2; test-first-as-org-structure). It is the goal's rollup
    # gate, not a per-engineer one (it exercises the WHOLE package), and is locked from the engineers.
    # Stack-neutral: publish whatever file(s) the manager wrote under ``acceptance/`` (any language),
    # plus any packaging MANIFEST it authored — so the gate can install the deliverable's declared
    # third-party dependencies (the acceptance test is free to use them) in every worktree from the start.
    contract_files = sorted(
        p for p in (working_dir / ACCEPTANCE_DIR).rglob("*") if p.is_file()
    ) + [working_dir / m for m in _MANIFESTS if (working_dir / m).is_file()]
    for path in contract_files:
        workspace.publish_to_main(
            str(path.relative_to(working_dir).as_posix()),
            path.read_text(encoding="utf-8"),
            message="chorus: publish acceptance suite + manifest (pre-fan-out)",
        )
    record_activity(
        ledger,
        verb=ActivityVerb.CONTRACT_PUBLISHED,
        subject_id=parent_id,
        actor_employee_id=actor,
        payload={"main_sha": sha, "contract_sha": contract_sha(content), "bytes": len(content)},
    )
    return sha


__all__ = ["contract_gate", "publish_contract"]
