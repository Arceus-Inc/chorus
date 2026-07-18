"""Org hooks — deterministic reactions to durable org state (the third autonomy leg).

Routines drive time ("every Monday, plan"), wakes drive dispatch ("someone has work"), and
hooks drive REACTION: each scheduler pulse, every registered hook reads the ledger and takes a
bounded, idempotent action in plain code — no model call, no veto power over beats. Paperclip's
lesson applied: an org feels alive when events are answered without anyone prompting it.

A hook is just ``Callable[[Ledger], int]`` returning how many actions it took. Hooks must be
idempotent (fingerprint what you create) and cheap (they run every pulse). A crashing hook is
isolated and logged; the pulse never dies for it.
"""

from chorus.hooks._delegatory import instruction_messages_become_tasks
from chorus.hooks._run import OrgHook, run_org_hooks


def default_org_hooks() -> tuple[OrgHook, ...]:
    """The built-in reactions every company starts with."""
    return (instruction_messages_become_tasks,)


__all__ = ["OrgHook", "default_org_hooks", "run_org_hooks"]
