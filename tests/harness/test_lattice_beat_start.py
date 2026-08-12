"""Beat-start lattice consolidation push — read lattice-beat-end.json at materialize."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from dream.contracts.hook import HookEvent

from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee
from chorus_employee._lattice import read_lattice_wake
from chorus_harness import _factory as _factory_mod
from chorus_harness._dream_hooks import VolatileBeatPacketHook

pytestmark = pytest.mark.integration


class _HarnessStub:
    def __init__(self) -> None:
        self.hooks: list[object] = []

    def register_hook(self, hook: object) -> None:
        self.hooks.append(hook)


def _factory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Any, dict[str, Any]]:
    captured: dict[str, Any] = {}
    harness = _HarnessStub()
    monkeypatch.setattr(
        _factory_mod.dream,
        "build_harness",
        lambda **kw: captured.update(kw) or captured.update(harness=harness) or harness,
    )
    factory = _factory_mod.EmployeeHarnessFactory(
        api_key="k",
        base_url="https://x/openai/v1",
        deployment="gpt-x",
        company_id="acme",
        roles=RoleRegistry.from_plugins(default_roles()),
        work_root=tmp_path,
    )
    return factory, captured


def test_read_lattice_wake_from_beat_end_file(tmp_path: Path) -> None:
    harness = tmp_path / "wt"
    harness.mkdir()
    payload = {
        "gate_open": True,
        "teaser": "**Lattice gate open** — pattern consolidation is due this beat.",
        "employee_id": "bex",
        "run_id": "run_1",
    }
    path = harness / ".harness" / "lattice-beat-end.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")

    wake = read_lattice_wake(harness)
    assert wake is not None
    assert wake.gate_open is True
    assert "Lattice gate open" in wake.teaser
    assert "lattice-consolidate" not in wake.teaser
    assert "get_run" not in wake.teaser


async def test_materialize_injects_lattice_wake_via_tcp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    factory, captured = _factory(monkeypatch, tmp_path)
    employee = Employee(id="ana", name="Ana", role="analyst")
    mat = factory.materialize(employee)

    teaser_path = mat.working_dir / ".harness" / "lattice-beat-end.json"
    teaser_path.parent.mkdir(parents=True, exist_ok=True)
    teaser_path.write_text(
        json.dumps(
            {
                "gate_open": True,
                "teaser": "**Lattice gate open** — consolidate now.",
                "employee_id": "bex",
            }
        ),
        encoding="utf-8",
    )
    wake = read_lattice_wake(mat.working_dir)
    assert wake is not None
    monkeypatch.setattr(_factory_mod, "read_lattice_wake", lambda _root: wake)

    mat2 = factory.materialize(employee)
    agents = (mat2.working_dir / ".harness" / "AGENTS.md").read_text(encoding="utf-8")
    assert "consolidate now" not in agents
    assert "lattice_packet" not in agents
    hook = [
        item
        for item in captured["harness"].hooks
        if isinstance(item, VolatileBeatPacketHook)
    ][-1]
    packet = (
        await hook(HookEvent.USER_PROMPT_SUBMIT, {"role": "generator", "prompt": "work"})
    ).inject_context or ""
    assert "### Lattice wake" in packet
    assert "consolidate now" in packet
    assert "lattice-consolidate" in packet
    assert "lattice_packet" not in packet
