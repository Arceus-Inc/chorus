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

from chorus.coherence import authored_contract, contract_sha
from chorus.ledger import ActivityVerb, SqliteLedger
from chorus.lifecycle import record_activity
from chorus.workspace import CompanyWorkspace

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
    sha = CompanyWorkspace(root).publish_to_main(
        "AGENTS.md", content, message="chorus: publish AGENTS.md contract (pre-fan-out)"
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
