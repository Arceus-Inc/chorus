"""The PM's Decision OS layer — the confidence policy and (later) the packet render (§10).

Role-owned domain knowledge that the kernel deliberately does not depend on: the tool and the DoD
floor import the policy from here, keeping the dependency arrow pointing inward (checklist J2).
"""

from __future__ import annotations

from chorus_employee.pm._decision._confidence import CONFIDENCE_FLOOR, clears_floor
from chorus_employee.pm._decision._packet import render_packet

__all__ = ["CONFIDENCE_FLOOR", "clears_floor", "render_packet"]
