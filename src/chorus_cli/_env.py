"""A tiny ``.env`` loader — ``KEY=VALUE`` lines into the process environment.

Just enough to pick up local credentials (the Azure keys that enable ``tick``) without a dependency.
An already-set variable always wins, so a real exported value is never clobbered by the file. Blank
lines and ``#`` comments are ignored; an optional ``export`` prefix and surrounding quotes are
stripped; values may themselves contain ``=``.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from pathlib import Path

_EXPORT = "export "


def _unquote(value: str) -> str:
    """Drop one layer of matching single or double quotes around ``value``."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def load_env_file(
    path: Path, *, environ: MutableMapping[str, str] = os.environ
) -> int:
    """Load ``path`` into ``environ`` (defaults to the real process env); return how many keys were set.

    A missing file is a no-op (returns 0). Existing keys are left untouched, so the ambient
    environment takes precedence over the file.
    """
    if not path.is_file():
        return 0
    loaded = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(_EXPORT):
            line = line[len(_EXPORT) :].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue  # not a KEY=VALUE line
        key = key.strip()
        if not key or key in environ:
            continue
        environ[key] = _unquote(value.strip())
        loaded += 1
    return loaded


__all__ = ["load_env_file"]
