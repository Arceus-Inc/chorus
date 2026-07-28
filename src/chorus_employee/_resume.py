"""Cross-beat resume directive — re-export from Dream's Base Prompt.

Canonical text lives in ``dream.prompts.employee_base`` and is injected by
Dream when ``employee_mode=True``. This module remains for imports/tests.
"""

from __future__ import annotations

from dream.prompts.employee_base import RESUME_DIRECTIVE

__all__ = ["RESUME_DIRECTIVE"]
