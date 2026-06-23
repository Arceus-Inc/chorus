"""Contract-derived decomposition — one task per declared module, owner + depends_on from AGENTS.md."""

from __future__ import annotations

import pytest

from chorus.coherence import AgentsMd
from chorus.lifecycle import child_plans_from_contract

pytestmark = pytest.mark.unit


def _doc() -> AgentsMd:
    return AgentsMd(
        modules=("pkg/__init__.py", "pkg/ingest.py", "pkg/model.py", "pkg/cli.py"),
        public_api=("pkg.fit",),
        ownership={
            "pkg/__init__.py": "ada",
            "pkg/ingest.py": "ada",
            "pkg/model.py": "bo",
            "pkg/cli.py": "ada",
        },
        dependencies={"pkg/model.py": ("pkg/ingest.py",), "pkg/cli.py": ("pkg/model.py",)},
    )


def test_one_plan_per_source_module_assigned_to_its_owner() -> None:
    derived = child_plans_from_contract(_doc())
    assert derived.unowned == ()
    by_label = {p.label: p for p in derived.plans}
    assert set(by_label) == {"pkg-__init__-py", "pkg-ingest-py", "pkg-model-py", "pkg-cli-py"}
    assert by_label["pkg-model-py"].assignee == "bo"
    assert by_label["pkg-ingest-py"].assignee == "ada"


def test_depends_on_comes_from_the_contract_dependency_dag() -> None:
    by_label = {p.label: p for p in child_plans_from_contract(_doc()).plans}
    # model depends on ingest; cli depends on model — the declared import edges
    assert by_label["pkg-model-py"].depends_on == ("pkg-ingest-py",)
    assert by_label["pkg-cli-py"].depends_on == ("pkg-model-py",)
    # a foundation module with no declared deps is unordered (parallel)
    assert by_label["pkg-ingest-py"].depends_on == ()


def test_init_depends_on_every_other_module_so_it_lands_last() -> None:
    init = next(p for p in child_plans_from_contract(_doc()).plans if p.label == "pkg-__init__-py")
    assert set(init.depends_on) == {"pkg-ingest-py", "pkg-model-py", "pkg-cli-py"}


def test_a_module_with_no_owner_is_reported_unowned() -> None:
    doc = AgentsMd(
        modules=("pkg/__init__.py", "pkg/model.py"),
        public_api=("pkg.fit",),
        ownership={"pkg/__init__.py": "ada"},  # model.py has no owner
    )
    derived = child_plans_from_contract(doc)
    assert derived.unowned == ("pkg/model.py",)


def test_test_files_and_non_py_files_are_not_their_own_tasks() -> None:
    doc = AgentsMd(
        modules=("pkg/core.py", "tests/test_core.py", "pyproject.toml"),
        public_api=("pkg.Thing",),
        ownership={"pkg/core.py": "ada", "tests/test_core.py": "ada", "pyproject.toml": "ada"},
    )
    labels = {p.label for p in child_plans_from_contract(doc).plans}
    assert labels == {"pkg-core-py"}  # only the source module becomes a task


def test_derives_plans_for_a_rust_crate() -> None:
    # Stack-agnostic: a Rust crate (`src/*.rs`) must derive one task per source module just like Python.
    # The manifest is excluded; `lib.rs` is the crate entry (re-exports the API) → depends on all others.
    doc = AgentsMd(
        modules=("Cargo.toml", "src/lib.rs", "src/metric.rs", "src/store.rs"),
        public_api=("tinyvec::TinyVec",),
        ownership={"src/lib.rs": "ada", "src/metric.rs": "bo", "src/store.rs": "ada"},
        dependencies={"src/store.rs": ("src/metric.rs",)},
    )
    derived = child_plans_from_contract(doc)
    assert derived.unowned == ()
    by = {p.label: p for p in derived.plans}
    assert set(by) == {"src-lib-rs", "src-metric-rs", "src-store-rs"}  # Cargo.toml excluded (manifest)
    assert by["src-store-rs"].depends_on == ("src-metric-rs",)  # declared import edge
    assert set(by["src-lib-rs"].depends_on) == {"src-metric-rs", "src-store-rs"}  # entry builds last


def test_derives_plans_for_a_go_module() -> None:
    doc = AgentsMd(
        modules=("go.mod", "store.go", "store_test.go", "index.go"),
        public_api=("Store",),
        ownership={"store.go": "ada", "index.go": "ada"},
    )
    labels = {p.label for p in child_plans_from_contract(doc).plans}
    assert labels == {"store-go", "index-go"}  # go.mod (manifest) + store_test.go (test) excluded
