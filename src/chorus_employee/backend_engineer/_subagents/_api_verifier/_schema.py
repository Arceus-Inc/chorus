"""The API-Verifier subagent's typed return contract (spec §16 Slice 3 — real-system verification).

The API-Verifier boots the just-built service and probes it over real HTTP, then returns an
:class:`ApiTestVerdict` — a decisive ``passed`` flag plus one :class:`ApiCheck` per live request it
issued (each naming what it probed, whether the response held, and the observed detail). ``evidence``
records *how* it booted and reached the service, so the verdict is auditable, not a bare boolean.

The contract is **self-consistent**: ``passed`` cannot be ``True`` while any check failed — a
green grade with a red probe is a contradiction the model cannot express.

Pydantic is the single source of truth: :func:`api_test_verdict_output_schema` derives the JSON
schema the subagent's ``output_schema`` enforces at runtime, and a caller parses the raw return with
:meth:`ApiTestVerdict.model_validate` — no hand-written schema to drift.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ApiCheck(BaseModel):
    """One probe against the running service — what was checked and whether it held."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, description="what was probed, e.g. 'GET /health -> 200'")
    ok: bool = Field(description="True iff the live response matched the expectation")
    detail: str = Field(min_length=1, description="the observed response or failure, quoted")


class ApiTestVerdict(BaseModel):
    """API-Verifier's return: did the *running* service behave, proven by real requests."""

    model_config = ConfigDict(str_strip_whitespace=True)

    passed: bool = Field(
        description="True iff every check passed — the service booted and behaved over real HTTP"
    )
    checks: list[ApiCheck] = Field(
        min_length=1, description="one entry per real request issued; at least one is required"
    )
    evidence: str = Field(
        min_length=1,
        description=(
            "how the service was booted + reached (command, port, responses); for a stateful check "
            "against a client-server datastore (Postgres/Mongo/Redis/…), the exact container boot "
            "command/image used (e.g. `docker run -d postgres:16 ...`) — not just 'connected to db'"
        ),
    )

    @model_validator(mode="after")
    def _passed_implies_every_check_ok(self) -> ApiTestVerdict:
        """A ``passed`` verdict may not carry a failing probe — the grade must match the evidence."""
        if self.passed and not all(check.ok for check in self.checks):
            raise ValueError("passed=True is invalid while a check failed")
        return self


def api_test_verdict_output_schema() -> dict[str, Any]:
    """The JSON schema handed to the API-Verifier's ``output_schema`` — derived from the model."""
    return ApiTestVerdict.model_json_schema()


__all__ = ["ApiCheck", "ApiTestVerdict", "api_test_verdict_output_schema"]
