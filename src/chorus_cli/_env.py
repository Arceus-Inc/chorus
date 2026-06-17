"""A tiny ``.env`` loader — ``KEY=VALUE`` lines into the process environment.

Just enough to pick up local credentials (the Azure keys that enable ``tick``) without a dependency.
By default an already-set variable wins (12-factor: an explicit export beats the file). The CLI opts
into ``override=True`` so the gitignored ``.env`` is *authoritative* for its credentials — a stale
``AZURE_OPENAI_*`` left in a shell profile must not silently shadow the file — and passes
``on_conflict`` to warn when it replaces a differing ambient value. Blank lines and ``#`` comments are
ignored; an optional ``export`` prefix and surrounding quotes are stripped; values may contain ``=``.
"""

from __future__ import annotations

import os
from collections.abc import Callable, MutableMapping
from pathlib import Path

_EXPORT = "export "


def _unquote(value: str) -> str:
    """Drop one layer of matching single or double quotes around ``value``."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def load_env_file(
    path: Path,
    *,
    environ: MutableMapping[str, str] = os.environ,
    override: bool = False,
    on_conflict: Callable[[str], None] | None = None,
) -> int:
    """Load ``path`` into ``environ`` (defaults to the real process env); return how many keys it set.

    A missing file is a no-op (returns 0). With ``override`` false (the default) an already-set key is
    left untouched — the ambient environment wins. With ``override`` true the file value replaces a
    differing ambient one (the file is authoritative) and ``on_conflict(key)`` is called for each such
    replacement, so the caller can warn. A key whose ambient value already equals the file value is a
    no-op either way (not counted, not a conflict).
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
        if not key:
            continue
        new_value = _unquote(value.strip())
        existing = environ.get(key)
        if existing == new_value:
            continue  # already correct — nothing to set, no conflict
        if existing is not None and not override:
            continue  # ambient value wins (the default)
        if existing is not None and on_conflict is not None:
            on_conflict(key)  # we are replacing a differing ambient value
        environ[key] = new_value
        loaded += 1
    return loaded


__all__ = ["load_env_file"]
