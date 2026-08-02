"""Secret lookup adapters used only inside the credential broker."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from dream.contracts.credentials import CredentialName


@dataclass(frozen=True, repr=False)
class SecretValue:
    """A source-local secret value with a redacted representation."""

    value: str

    def __repr__(self) -> str:
        return "SecretValue(<redacted>)"


class SecretSource(Protocol):
    async def get(self, name: CredentialName) -> SecretValue | None: ...


class EnvironmentSecretSource:
    def __init__(self, environment: Mapping[str, str]) -> None:
        self._environment = environment

    async def get(self, name: CredentialName) -> SecretValue | None:
        value = self._environment.get(name.value)
        return SecretValue(value) if value else None


class AwsSecretsManagerClient(Protocol):
    async def get_secret(self, name: str) -> str | None: ...


class AwsSecretsManagerSource:
    def __init__(self, client: AwsSecretsManagerClient, *, prefix: str = "") -> None:
        self._client = client
        self._prefix = prefix

    async def get(self, name: CredentialName) -> SecretValue | None:
        value = await self._client.get_secret(f"{self._prefix}{name.value}")
        return SecretValue(value) if value else None


class LayeredSecretSource:
    def __init__(self, sources: tuple[SecretSource, ...]) -> None:
        self._sources = sources

    async def get(self, name: CredentialName) -> SecretValue | None:
        for source in self._sources:
            value = await source.get(name)
            if value is not None:
                return value
        return None


__all__ = [
    "AwsSecretsManagerClient",
    "AwsSecretsManagerSource",
    "EnvironmentSecretSource",
    "LayeredSecretSource",
    "SecretSource",
    "SecretValue",
]
