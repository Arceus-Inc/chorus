"""The per-beat context a capability tool needs but dream's ``ToolExecutionContext`` does not carry.

A capability tool (e.g. ``decompose``) runs *inside* a dream beat and must know which task and run it
is acting for. The harness is materialized per-employee (``runner_for(employee)``) — it does not see
the beat's ``task_id`` / ``run_id`` — so the kernel writes those to a small file in the employee's
working dir just before the beat, and the tool reads it back from ``ctx.working_dir``.

Dream-free (chorus core): both the writer (the kernel) and the reader (a ``chorus_tools`` tool) share
this one model so the on-disk shape can't drift between them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_RELATIVE_PATH = Path(".harness") / "beat-context.json"


@dataclass(frozen=True)
class BeatContext:
    """Which task/run an employee's beat is acting for, handed to its in-beat capability tools."""

    task_id: str
    run_id: str
    employee_id: str

    @staticmethod
    def path_in(working_dir: Path) -> Path:
        """The on-disk location of the beat context under an employee's working dir."""
        return working_dir / _RELATIVE_PATH

    def write(self, working_dir: Path) -> None:
        """Persist this context under ``working_dir`` for the beat's capability tools to read."""
        path = self.path_in(working_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"task_id": self.task_id, "run_id": self.run_id, "employee_id": self.employee_id}
        path.write_text(json.dumps(payload), encoding="utf-8")

    @classmethod
    def read(cls, working_dir: Path) -> BeatContext:
        """Load the beat context a tool is acting under; raises if it is missing or malformed."""
        data = json.loads(cls.path_in(working_dir).read_text(encoding="utf-8"))
        return cls(
            task_id=data["task_id"],
            run_id=data["run_id"],
            employee_id=data["employee_id"],
        )


__all__ = ["BeatContext"]
