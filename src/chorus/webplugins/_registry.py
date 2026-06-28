"""The WebPlugin registry — trust-scoped external reach, fail-closed + idempotent (spec GM §5).

A :class:`WebPlugin` is the role-agnostic integration surface: ``(name, kind, capability, auth ref,
trust scope, spend cap)``. Once registered, *any* employee's manifest can be granted it — the Growth
Marketer is the forcing function, not a special case (the Engineer and Analyst inherit the same
layer). Registration mirrors :class:`~chorus.roles.RoleRegistry`:

- **fail-closed** — a plugin with an empty name, an inline (non-``ref:``) auth secret, or a gated
  capability without a :class:`~chorus.webplugins._trust.SpendCap` is rejected *whole* before it can
  own reach (:class:`~chorus.errors.WebPluginInvalid`);
- **idempotent** — re-registering an identical definition is a no-op; a *different* definition under
  the same name raises :class:`~chorus.errors.WebPluginConflict` unless ``replace=True``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from chorus.errors import WebPluginConflict, WebPluginInvalid
from chorus.webplugins._trust import Capability, PluginKind, SpendCap, is_secret_ref


@dataclass(frozen=True)
class WebPlugin:
    """One trust-scoped integration — the hands an employee reaches an external system with.

    ``auth_ref`` is a secret *handle* (``ref:warehouse_ro``), never an inline value. ``scope`` is the
    human-readable trust note (e.g. "read-only, row/role-scoped views"). A gated capability
    (``SEND``/``SPEND``) must carry ``spend_cap``; a read/design plugin leaves it ``None``.
    """

    name: str
    kind: PluginKind
    capability: Capability
    auth_ref: str
    scope: str = ""
    spend_cap: SpendCap | None = None

    @property
    def gated(self) -> bool:
        """Whether exercising this plugin crosses the human-approval gate (spec GM §9)."""
        return self.capability.gated


class WebPluginRegistry:
    """An in-memory ``name -> WebPlugin`` map, validated fail-closed at registration (spec GM §5)."""

    def __init__(self) -> None:
        self._plugins: dict[str, WebPlugin] = {}

    @classmethod
    def from_plugins(cls, plugins: Iterable[WebPlugin]) -> WebPluginRegistry:
        """Build a registry and register every plugin through the validated path."""
        registry = cls()
        for plugin in plugins:
            registry.register(plugin)
        return registry

    # -- reads ----------------------------------------------------------------

    def get(self, name: str) -> WebPlugin:
        return self._plugins[name]

    def names(self) -> tuple[str, ...]:
        return tuple(self._plugins)

    def __contains__(self, name: object) -> bool:
        return name in self._plugins

    def __len__(self) -> int:
        return len(self._plugins)

    # -- writes ---------------------------------------------------------------

    def register(self, plugin: WebPlugin, *, replace: bool = False) -> None:
        """Validate, then register the plugin — fail-closed + idempotent (spec GM §5)."""
        self._validate(plugin)
        existing = self._plugins.get(plugin.name)
        if existing is not None and not replace:
            if existing == plugin:
                return  # idempotent — an identical definition is a harmless no-op
            raise WebPluginConflict(
                f"web plugin {plugin.name!r} already registered with a different definition; "
                "pass replace=True to override"
            )
        self._plugins[plugin.name] = plugin

    # -- validation -----------------------------------------------------------

    @staticmethod
    def _validate(plugin: WebPlugin) -> None:
        if not plugin.name or not plugin.name.strip():
            raise WebPluginInvalid("web plugin name must be a non-empty slug")
        if not isinstance(plugin.kind, PluginKind):
            raise WebPluginInvalid(f"web plugin {plugin.name!r} has illegal kind {plugin.kind!r}")
        if not isinstance(plugin.capability, Capability):
            raise WebPluginInvalid(
                f"web plugin {plugin.name!r} has illegal capability {plugin.capability!r}"
            )
        if not is_secret_ref(plugin.auth_ref):
            raise WebPluginInvalid(
                f"web plugin {plugin.name!r} auth must bind a ref: handle, not an inline value "
                f"(got {plugin.auth_ref!r})"
            )
        if plugin.gated and plugin.spend_cap is None:
            raise WebPluginInvalid(
                f"gated web plugin {plugin.name!r} ({plugin.capability}) must carry a SpendCap — "
                "a spend/send can never be unbounded"
            )


__all__ = ["WebPlugin", "WebPluginRegistry"]
