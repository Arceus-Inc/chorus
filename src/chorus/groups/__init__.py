"""Low-level grouped facades (spec 14 §2.2).

The niche operator surfaces, namespaced off ``Chorus`` so they never clutter the flat high-level
front door. Each group is a thin, typed delegation over the same backends the composition root holds
— two views of one object, never two objects to keep in sync.
"""

from __future__ import annotations

from chorus.groups._governance import GovernanceFacade, HireRequest
from chorus.groups._inspect import InspectFacade

__all__ = ["GovernanceFacade", "HireRequest", "InspectFacade"]
