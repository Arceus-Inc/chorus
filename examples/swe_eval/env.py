"""Environment + credentials — one place to load the pinned ``.env`` and the model creds.

Mirrors ``frontend_engineer_hard_tasks.py::_load_env``: the repo-root ``chorus/.env`` is
AUTHORITATIVE and OVERRIDES stale shell values (the footgun where a leftover
``AZURE_OPENAI_DEPLOYMENT`` silently defeats the pinned config). Secrets stay in the
gitignored ``.env`` — never in source.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_env() -> None:
    """Fold ``chorus/.env`` (or ``$CHORUS_ENV_FILE``) into ``os.environ``, overriding stale values."""
    # examples/swe_eval/env.py -> parents[2] == the chorus repo root that holds .env
    default = Path(__file__).resolve().parents[2] / ".env"
    path = Path(os.environ.get("CHORUS_ENV_FILE", str(default)))
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ[key.strip()] = value.strip().strip("'\"")


@dataclass(frozen=True)
class ModelCreds:
    """The OpenAI-compatible chat endpoint the employees + the LLM judge share."""

    api_key: str
    base_url: str
    deployment: str


def model_creds() -> ModelCreds | None:
    """Read the Azure/OpenAI-compatible creds from the environment, or ``None`` if unset."""
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        return None
    return ModelCreds(api_key=api_key, base_url=base_url, deployment=deployment)
