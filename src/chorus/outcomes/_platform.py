"""Cross-platform Definition-of-Done command building + a runtime brief block.

dream runs a DoD :class:`~chorus.outcomes.Command` (and the ``run_command`` tool) through
``asyncio.create_subprocess_shell``, which is ``/bin/sh -c`` on POSIX but ``%COMSPEC%`` (``cmd.exe``
by default) on Windows. A floor authored in POSIX syntax — ``test -s`` / ``grep`` / ``wc`` — therefore
*cannot* execute on Windows, which is exactly the failure the first design beats hit ("DoD fails due to
the Windows env"). The one command string that verifies **identically on every OS** is a single
``python -c`` invocation, because Python is guaranteed present (dream itself runs on it) and its syntax
is shell-independent.

To stay robust across both shells' quoting rules this module never embeds the check logic as raw shell
text. It base64-encodes a small self-contained checker script and emits::

    <python> -c "import base64;exec(base64.b64decode('<BASE64>').decode())"

The only thing on the command line is a single-quoted base64 blob — no ``%``, ``&``, ``|``, ``<``, ``>``,
``^`` or embedded quotes — so ``cmd.exe`` and ``sh`` hand Python byte-identical source. Composed via the
small check constructors below (:func:`file_exists`, :func:`min_words`, :func:`file_matches`,
:func:`file_matches_any`, :func:`glob_at_least`), each of which fails the whole gate — with a readable
reason on stderr — the moment its assertion does not hold.

:func:`detect_platform` + :func:`runtime_brief_block` render a short, factual *Operating environment*
block an employee brief can carry so the model writes ``run_command`` calls in the right shell and knows
which runtimes are on ``PATH`` (dream advertises OS/shell/Python; this adds the role-relevant Node/npm/
Playwright facts an engineer needs).
"""

from __future__ import annotations

import base64
import platform
import shutil
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# --- cross-platform DoD command building --------------------------------------------------------

Check = dict[str, object]
"""A single JSON-serialisable assertion the checker script evaluates (see the constructors below)."""


def file_exists(path: str) -> Check:
    """Assert ``path`` exists and is a non-empty regular file (relative to the verification CWD)."""
    return {"kind": "exists", "path": path}


def min_words(path: str, count: int) -> Check:
    """Assert ``path`` is readable and holds at least ``count`` whitespace-separated words."""
    return {"kind": "min_words", "path": path, "count": int(count)}


def file_matches(path: str, pattern: str, *, label: str) -> Check:
    """Assert ``path`` contains ``pattern`` (regex, case-insensitive + multiline); ``label`` names it."""
    return {"kind": "regex", "path": path, "pattern": pattern, "label": label}


def file_matches_any(path: str, patterns: Sequence[str], *, label: str) -> Check:
    """Assert ``path`` matches at least one of ``patterns`` (regex, case-insensitive + multiline)."""
    return {"kind": "any_regex", "path": path, "patterns": list(patterns), "label": label}


def glob_at_least(pattern: str, count: int) -> Check:
    """Assert at least ``count`` files match the recursive glob ``pattern`` (relative to the CWD)."""
    return {"kind": "glob_min", "pattern": pattern, "count": int(count)}


# The checker script. Kept free of ``{`` / ``}`` so a literal ``__CHECKS__`` substitution is enough;
# the whole script is base64-encoded before it reaches a shell, so quotes/regexes/newlines are all safe.
_CHECKER_SCRIPT = """\
import os, re, sys

CHECKS = __CHECKS__


def _fail(msg):
    sys.stderr.write("DoD FAIL: " + msg + "\\n")
    raise SystemExit(1)


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        _fail("cannot read: " + path)
        raise


for _c in CHECKS:
    _kind = _c["kind"]
    _path = _c.get("path", "")
    if _kind == "exists":
        if not os.path.isfile(_path):
            _fail("missing file: " + _path)
        if os.path.getsize(_path) <= 0:
            _fail("empty file: " + _path)
    elif _kind == "min_words":
        _n = len(_read(_path).split())
        if _n < _c["count"]:
            _fail(_path + " has " + str(_n) + " words; need >= " + str(_c["count"]))
    elif _kind == "regex":
        if not re.search(_c["pattern"], _read(_path), re.I | re.M):
            _fail(_path + ": missing required content (" + _c["label"] + ")")
    elif _kind == "any_regex":
        _text = _read(_path)
        if not any(re.search(_p, _text, re.I | re.M) for _p in _c["patterns"]):
            _fail(_path + ": missing required content (" + _c["label"] + ")")
    elif _kind == "glob_min":
        import glob
        _hits = [p for p in glob.glob(_c["pattern"], recursive=True) if os.path.isfile(p)]
        if len(_hits) < _c["count"]:
            _fail("need >= " + str(_c["count"]) + " file(s) matching "
                  + _c["pattern"] + "; found " + str(len(_hits)))
    else:
        _fail("unknown check kind: " + str(_kind))

raise SystemExit(0)
"""


def python_check(checks: Iterable[Check], *, python: str | None = None) -> str:
    """Compose ``checks`` into one cross-platform ``python -c`` command that exits 0 iff all pass.

    ``python`` defaults to :data:`sys.executable` — the same interpreter chorus is running under, which
    is guaranteed present for dream's oracle on this host. The command is quoting-safe on both
    ``cmd.exe`` and ``/bin/sh``: everything but a single-quoted base64 blob is plain ASCII.
    """
    interpreter = python or sys.executable or "python"
    script = _CHECKER_SCRIPT.replace("__CHECKS__", repr(list(checks)))
    blob = base64.b64encode(script.encode("utf-8")).decode("ascii")
    exe = f'"{interpreter}"' if " " in interpreter else interpreter
    return f"{exe} -c \"import base64;exec(base64.b64decode('{blob}').decode())\""


# --- runtime detection + brief block -------------------------------------------------------------


@dataclass(frozen=True)
class PlatformInfo:
    """A factual snapshot of the host runtime the employee's ``run_command`` calls land on."""

    os_name: str
    os_release: str
    shell: str
    python_version: str
    node_version: str | None
    npm_version: str | None
    playwright_browsers_cached: bool


def _shell_for(env: Mapping[str, str]) -> str:
    """The shell ``create_subprocess_shell`` hands a ``command`` to — matches dream's own rule."""
    if sys.platform == "win32":
        return env.get("COMSPEC") or "cmd.exe"
    return "/bin/sh"


def _probe_version(executable: str, *args: str) -> str | None:
    """Best-effort ``<executable> --version`` (short timeout); ``None`` if absent or it misbehaves."""
    resolved = shutil.which(executable)
    if resolved is None:
        return None
    try:
        completed = subprocess.run(
            [resolved, *args],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = (completed.stdout or completed.stderr or "").strip()
    return out.splitlines()[0].strip() if out else None


def _playwright_cache_dir(env: Mapping[str, str]) -> Path:
    """Where Playwright caches browsers on this OS (honouring ``PLAYWRIGHT_BROWSERS_PATH``)."""
    override = env.get("PLAYWRIGHT_BROWSERS_PATH")
    if override and override != "0":
        return Path(override)
    if sys.platform == "win32":
        base = env.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "ms-playwright"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def _has_cached_browsers(env: Mapping[str, str]) -> bool:
    cache = _playwright_cache_dir(env)
    try:
        return cache.is_dir() and any(cache.iterdir())
    except OSError:
        return False


@lru_cache(maxsize=1)
def detect_platform() -> PlatformInfo:
    """Detect the host runtime once per process (cached — the host does not change mid-run)."""
    import os

    env = os.environ
    return PlatformInfo(
        os_name=platform.system() or sys.platform,
        os_release=platform.release(),
        shell=_shell_for(env),
        python_version=platform.python_version(),
        node_version=_probe_version("node", "--version"),
        npm_version=_probe_version("npm", "--version"),
        playwright_browsers_cached=_has_cached_browsers(env),
    )


def runtime_brief_block(info: PlatformInfo | None = None) -> str:
    """Render an *Operating environment* brief block from ``info`` (detected if not supplied).

    Complements dream's own OS/shell/Python line with the Node/npm/Playwright facts an engineer needs,
    and states plainly that the DoD is verified with a platform-agnostic Python check (so the model does
    not waste turns second-guessing shell portability).
    """
    info = info or detect_platform()
    runtimes = [f"Python {info.python_version}"]
    runtimes.append(f"Node.js {info.node_version}" if info.node_version else "Node.js: not on PATH")
    runtimes.append(f"npm {info.npm_version}" if info.npm_version else "npm: not on PATH")
    runtimes.append(
        "Playwright browsers: cached (offline e2e OK)"
        if info.playwright_browsers_cached
        else "Playwright browsers: not cached (npx playwright install may be needed)"
    )
    runtime_lines = "\n".join(f"- {line}" for line in runtimes)
    return (
        "## Operating environment\n"
        f"You are running on {info.os_name} ({info.os_release}). Commands you pass to `run_command` "
        f"execute through `{info.shell}` — write them in that shell's syntax (POSIX `sh` on Linux/macOS, "
        "`cmd.exe` on Windows), or invoke a cross-platform runtime (prefer `node`/`npx`/`python`) so the "
        "same command works everywhere. Runtimes on PATH:\n"
        f"{runtime_lines}\n"
        "Your Definition of Done is verified with a platform-agnostic Python check, so it evaluates "
        "identically on every OS — you do not need to author OS-specific verification yourself."
    )


__all__ = [
    "Check",
    "PlatformInfo",
    "detect_platform",
    "file_exists",
    "file_matches",
    "file_matches_any",
    "glob_at_least",
    "min_words",
    "python_check",
    "runtime_brief_block",
]
