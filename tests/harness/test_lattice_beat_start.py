"""Beat-start lattice consolidation push — read lattice-beat-end.json at materialize."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from chorus.ledger import Ledger
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee
from chorus_employee._lattice import LATTICE_BEAT_START_HEADER, read_lattice_consolidation_push
from chorus_harness import _factory as _factory_mod

pytestmark = pytest.mark.integration


def _factory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger: Ledger
) -> tuple[Any, dict[str, Any]]:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        _factory_mod.dream, "build_harness", lambda **kw: captured.update(kw) or object()
    )
    factory = _factory_mod.EmployeeHarnessFactory(
        api_key="k",
        base_url="https://x/openai/v1",
        deployment="gpt-x",
        company_id="acme",
        roles=RoleRegistry.from_plugins(default_roles()),
        work_root=tmp_path,
        ledger=ledger,
    )
    return factory, captured


def test_read_lattice_consolidation_push_from_beat_end_file(tmp_path: Path) -> None:
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

    push = read_lattice_consolidation_push(harness)
    assert "Lattice gate open" in push
    assert "lattice-consolidate" in push
    assert "get_run" in push


def test_materialize_injects_lattice_push_when_gate_file_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger: Ledger
) -> None:
    factory, _ = _factory(monkeypatch, tmp_path, ledger)
    mat = factory.materialize(Employee(id="bex", name="Bex", role="backend_engineer"))

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

    mat2 = factory.materialize(Employee(id="bex", name="Bex", role="backend_engineer"))
    overlay = (mat2.working_dir / ".harness" / "roles" / "generator.toml").read_text(
        encoding="utf-8"
    )
    assert LATTICE_BEAT_START_HEADER.strip() in overlay or "Lattice consolidation (auto" in overlay
    assert "consolidate now" in overlay
    assert "lattice_packet" in overlay
