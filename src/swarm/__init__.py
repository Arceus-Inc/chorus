"""swarm — reusable, shared subagents that any chorus employee can spawn mid-beat.

Where ``chorus_employee`` defines whole *roles* (a role manifest + DoD + lander), ``swarm`` is
the home for *shared subagents*: bounded, capability-minimized specialists that are not owned by
one role but spliced into any role that opts in. The first is the Web-Research Orchestrator (a
research-over-the-web subagent, ported in spirit from eu-swarm's smart-scraper).

This package depends on :mod:`chorus.roles` (``SubagentSpec`` / ``RoleManifest``) and stays
dream-free — the composition root (``chorus_harness``) projects these specs onto dream at
materialize time, exactly as it does for role-owned subagents.
"""

from __future__ import annotations
