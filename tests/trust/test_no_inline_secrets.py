"""The shared no-inline-secrets predicate (spec 13 §3 / M4 S3 guard).

``env`` binds secret *refs*, never raw values. The kernel already enforces this for a low-trust beat
at materialize (``assert_contained``); ``assert_no_inline_secrets`` is the same rule extracted so the
routine-write paths (add / revise / reconcile / plugin registration) reject an inline secret *before*
it can ever land in a row. Key-heuristic: only a secret-looking key with a non-``ref:`` value is
rejected; plain non-secret config passes.
"""

from __future__ import annotations

import pytest

from chorus.errors import InvalidIntake
from chorus.trust import assert_no_inline_secrets

pytestmark = pytest.mark.unit


def test_ref_handle_for_a_secret_key_is_allowed() -> None:
    assert_no_inline_secrets({"GITHUB_TOKEN": "ref:github_token"})  # no raise


def test_plain_non_secret_config_is_allowed() -> None:
    assert_no_inline_secrets({"REGION": "us-east-1", "LOG_LEVEL": "info"})  # no raise


def test_none_and_empty_are_allowed() -> None:
    assert_no_inline_secrets(None)
    assert_no_inline_secrets({})


@pytest.mark.parametrize(
    "key",
    ["GITHUB_TOKEN", "api_key", "DB_PASSWORD", "client_secret", "SOME_CREDENTIAL", "OPENAI_API_KEY"],
)
def test_inline_value_under_a_secret_key_is_rejected(key: str) -> None:
    with pytest.raises(InvalidIntake, match="inline secret"):
        assert_no_inline_secrets({key: "sk-raw-value-1234"})


def test_the_rejected_key_is_named() -> None:
    with pytest.raises(InvalidIntake, match="GITHUB_TOKEN"):
        assert_no_inline_secrets({"REGION": "us-east", "GITHUB_TOKEN": "ghp_raw"})
