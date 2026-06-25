"""Stack-aware product Definition-of-Done gate.

The gate runs from the repository under test and detects ordinary project markers: Node/TypeScript,
Rust, Go, and Python. It fails scaffold-only repositories, chooses the package manager declared by the
repo, and runs the strongest conventional build/test command it can infer.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
_DEFAULT_STEP_TIMEOUT_SECONDS = 300

_IGNORE_PARTS = frozenset({
    ".git",
    ".harness",
    ".dream",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "docs",
})
_SCAFFOLD_ROOT_NAMES = frozenset({"README.md", "test_smoke.py", ".npmrc"})
_CONFIG_NAMES = frozenset({
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    "yarn.lock",
    "tsconfig.json",
    "vite.config.ts",
    "vite.config.js",
    "Cargo.toml",
    "Cargo.lock",
    "go.mod",
    "go.sum",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
})


def _run(cmd: list[str]) -> int:
    print(f"[gate] $ {' '.join(cmd)}", flush=True)
    exe = shutil.which(cmd[0])
    if exe is None:
        print(f"[gate] tool not found on PATH: {cmd[0]}", flush=True)
        return 127
    timeout = _step_timeout_seconds()
    try:
        return subprocess.run([exe, *cmd[1:]], cwd=str(ROOT), timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        print(f"[gate] FAILED: command timed out after {timeout}s: {' '.join(cmd)}", flush=True)
        return 124


def _step_timeout_seconds() -> int:
    raw = os.environ.get("CHORUS_GATE_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return _DEFAULT_STEP_TIMEOUT_SECONDS
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_STEP_TIMEOUT_SECONDS
    return max(1, value)


def _ignored(rel: Path) -> bool:
    return bool(set(rel.parts) & _IGNORE_PARTS)


def _is_root_plan(rel: Path) -> bool:
    return rel.parent == Path(".") and rel.suffix.lower() == ".md" and rel.name.lower().startswith(
        "plan"
    )


def _is_scaffold_or_config(rel: Path) -> bool:
    if rel.parent == Path(".") and rel.name in _SCAFFOLD_ROOT_NAMES:
        return True
    if _is_root_plan(rel):
        return True
    if rel.name in _CONFIG_NAMES:
        return True
    return rel.name.startswith(".")


def _has_deliverable() -> bool:
    """True once a real product file exists, not only scaffolding, plans, and config."""
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if _ignored(rel) or _is_scaffold_or_config(rel):
            continue
        return True
    return False


def _has_py_sources() -> bool:
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if _ignored(rel) or _is_scaffold_or_config(rel):
            continue
        return True
    return False


def _node_scripts() -> dict[str, str]:
    try:
        data = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    scripts = data.get("scripts", {})
    return scripts if isinstance(scripts, dict) else {}


def _is_npm_workspaces() -> bool:
    try:
        data = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    workspaces = data.get("workspaces")
    if isinstance(workspaces, list):
        return bool(workspaces)
    if isinstance(workspaces, dict):
        return bool(workspaces.get("packages"))
    return False


def _node_pm() -> str:
    try:
        data = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    package_manager = str(data.get("packageManager", ""))
    if package_manager.startswith("pnpm") or (ROOT / "pnpm-lock.yaml").is_file() or (
        ROOT / "pnpm-workspace.yaml"
    ).is_file():
        return "pnpm"
    if package_manager.startswith("yarn") or (ROOT / "yarn.lock").is_file():
        return "yarn"
    return "npm"


def _node_steps() -> list[list[str]] | None:
    scripts = _node_scripts()
    is_workspaces = _is_npm_workspaces()
    package_manager = _node_pm()
    if package_manager == "pnpm":
        install = ["pnpm", "install"]
        workspace_build = ["pnpm", "-r", "--if-present", "run", "build"]
        workspace_test = ["pnpm", "-r", "--if-present", "run", "test"]
    elif package_manager == "yarn":
        install = ["yarn", "install"]
        workspace_build = ["yarn", "workspaces", "run", "build"]
        workspace_test = ["yarn", "workspaces", "run", "test"]
    else:
        install = ["npm", "install", "--no-audit", "--no-fund"]
        workspace_build = ["npm", "--workspaces", "run", "build", "--if-present"]
        workspace_test = ["npm", "--workspaces", "run", "test", "--if-present"]

    steps: list[list[str]] = []
    if not (ROOT / "node_modules").is_dir():
        steps.append(install)
    aggregate = next((script for script in ("gate", "ci", "verify", "check") if script in scripts), None)
    if aggregate is not None:
        steps.append([package_manager, "run", aggregate])
        return steps
    if "build" in scripts:
        steps.append([package_manager, "run", "build"])
    elif is_workspaces:
        steps.append(workspace_build)
    if "test" in scripts:
        steps.append([package_manager, "run", "test"])
    elif is_workspaces:
        steps.append(workspace_test)
    elif (ROOT / "tsconfig.json").is_file():
        steps.append(["npx", "tsc", "--noEmit"])
    if len(steps) == (0 if (ROOT / "node_modules").is_dir() else 1):
        print("[gate] FAILED: Node project has no build/test/check script to prove it", flush=True)
        return None
    return steps


def _run_pytest_strict() -> int:
    exe = shutil.which("pytest")
    if exe is None:
        print("[gate] tool not found on PATH: pytest", flush=True)
        return 127
    print("[gate] $ pytest -q -rs", flush=True)
    proc = subprocess.run([exe, "-q", "-rs"], cwd=str(ROOT), capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    sys.stdout.write(proc.stderr)
    sys.stdout.flush()
    if proc.returncode != 0:
        return proc.returncode
    output = proc.stdout + proc.stderr
    if re.search(r"no tests ran", output) or re.search(r"\b0 passed\b", output):
        print("[gate] FAILED: no tests actually executed", flush=True)
        return 1
    if re.search(r"\b\d+ skipped\b", output):
        print("[gate] FAILED: tests were skipped", flush=True)
        return 1
    return 0


def main() -> int:
    if not _has_deliverable():
        print(
            "[gate] FAILED: no deliverable was built; plans, scaffolding, and config are not the product",
            flush=True,
        )
        return 1

    steps: list[list[str]] = []
    if (ROOT / "package.json").is_file():
        node_steps = _node_steps()
        if node_steps is None:
            return 1
        steps.extend(node_steps)
    if (ROOT / "Cargo.toml").is_file():
        steps.append(["cargo", "test"])
    if (ROOT / "go.mod").is_file():
        steps.append(["go", "test", "./..."])

    run_py = _has_py_sources() or not steps
    if run_py:
        steps.append(["ruff", "check", "."])

    for cmd in steps:
        return_code = _run(cmd)
        if return_code != 0:
            print(f"[gate] FAILED (rc={return_code}): {' '.join(cmd)}", flush=True)
            return return_code

    if run_py:
        return_code = _run_pytest_strict()
        if return_code != 0:
            print(f"[gate] FAILED (rc={return_code}): pytest (strict)", flush=True)
            return return_code

    print("[gate] all gates passed", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())