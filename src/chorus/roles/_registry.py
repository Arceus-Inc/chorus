"""The role registry — fail-closed, idempotent role registration (spec 06 §2, spec 09 §1).

The registry is the in-memory map of role slug → :class:`RolePlugin`, rebuilt from code each
boot (never ledger state, so nothing to migrate). Registration is **fail-closed**: a malformed
plugin is rejected *whole* with :class:`RolePluginInvalid` before it can own work — never
half-applied. It is **idempotent**: re-registering the same slug with an identical definition is a
no-op; a *different* definition raises :class:`RolePluginConflict` unless ``replace=True``.

Validation (spec 09 §1):
- the name is a non-empty slug;
- ``permission_mode`` / ``memory_scope`` / ``isolation`` are legal enum members;
- every tool resolves to a *registered* tool — but only when the caller supplies the
  ``known_tools`` set (chorus has no global tool registry yet, so the check is opt-in);
- the ``dod_generator`` returns a typed :class:`Verifier` for a probe intent;
- the ``outcome_kind`` is non-empty and, when ``known_outcome_kinds`` is supplied, has a
  registered lander.
"""

from __future__ import annotations

from collections.abc import Iterable

from chorus.errors import RolePluginConflict, RolePluginInvalid
from chorus.outcomes import Verifier
from chorus.roles._manifest import Isolation, MemoryScope, PermissionMode
from chorus.roles._plugin import RolePlugin
from chorus.roles._routine_declaration import RoutineDeclaration

_PROBE_INTENT = "probe: does this role generate a typed DoD?"


class RoleRegistry:
    """An in-memory role-plugin registry keyed by slug (spec 06 §2, spec 09 §1).

    ``known_tools`` / ``known_outcome_kinds`` are the optional validation universes: when
    ``None`` (the default) the corresponding check is skipped, because chorus has no global
    tool/lander registry yet — supplying them turns the check on without a kernel change.
    """

    def __init__(
        self,
        *,
        known_tools: frozenset[str] | None = None,
        known_outcome_kinds: frozenset[str] | None = None,
    ) -> None:
        self._known_tools = known_tools
        self._known_outcome_kinds = known_outcome_kinds
        self._plugins: dict[str, RolePlugin] = {}
        self._frozen: set[str] = set()

    @classmethod
    def from_plugins(
        cls,
        plugins: Iterable[RolePlugin],
        *,
        known_tools: frozenset[str] | None = None,
        known_outcome_kinds: frozenset[str] | None = None,
    ) -> RoleRegistry:
        """Build a registry and register every plugin through the validated path."""
        registry = cls(known_tools=known_tools, known_outcome_kinds=known_outcome_kinds)
        for plugin in plugins:
            registry.register(plugin)
        return registry

    # -- reads ----------------------------------------------------------------

    def get(self, name: str) -> RolePlugin:
        return self._plugins[name]

    def names(self) -> tuple[str, ...]:
        return tuple(self._plugins)

    def __contains__(self, name: object) -> bool:
        return name in self._plugins

    def is_frozen(self, name: str) -> bool:
        return name in self._frozen

    # -- writes ---------------------------------------------------------------

    def register(self, plugin: RolePlugin, *, replace: bool = False) -> None:
        """Validate, then register the plugin — fail-closed + idempotent (spec 09 §1)."""
        self._validate(plugin)
        existing = self._plugins.get(plugin.name)
        if existing is not None and not replace:
            if _same_definition(existing, plugin):
                return  # idempotent boot — identical definition is a harmless no-op
            raise RolePluginConflict(
                f"role {plugin.name!r} already registered with a different definition; "
                "pass replace=True to override"
            )
        self._plugins[plugin.name] = plugin

    def mark_used(self, name: str) -> None:
        """Freeze a role at first use — later ``replace=True`` registers a new version (spec 09 §1)."""
        if name in self._plugins:
            self._frozen.add(name)

    # -- validation -----------------------------------------------------------

    def _validate(self, plugin: RolePlugin) -> None:
        if not plugin.name or not plugin.name.strip():
            raise RolePluginInvalid("role name must be a non-empty slug")
        manifest = plugin.manifest
        if not isinstance(manifest.permission_mode, PermissionMode):
            raise RolePluginInvalid(f"illegal permission_mode {manifest.permission_mode!r}")
        if not isinstance(manifest.memory_scope, MemoryScope):
            raise RolePluginInvalid(f"illegal memory_scope {manifest.memory_scope!r}")
        if not isinstance(manifest.isolation, Isolation):
            raise RolePluginInvalid(f"illegal isolation {manifest.isolation!r}")
        if self._known_tools is not None:
            unknown = tuple(t for t in manifest.tools if t not in self._known_tools)
            if unknown:
                raise RolePluginInvalid(f"role {plugin.name!r} names unregistered tools {unknown}")
        if not plugin.outcome_kind:
            raise RolePluginInvalid(f"role {plugin.name!r} has an empty outcome_kind")
        if (
            self._known_outcome_kinds is not None
            and plugin.outcome_kind not in self._known_outcome_kinds
        ):
            raise RolePluginInvalid(
                f"role {plugin.name!r} outcome_kind {plugin.outcome_kind!r} has no registered lander"
            )
        try:
            probe = plugin.dod_generator(_PROBE_INTENT)
        except Exception as exc:  # any failure is a malformed generator
            raise RolePluginInvalid(
                f"role {plugin.name!r} dod_generator raised on a probe intent: {exc}"
            ) from exc
        if not isinstance(probe, Verifier):
            raise RolePluginInvalid(
                f"role {plugin.name!r} dod_generator must return a typed Verifier, got {type(probe)}"
            )
        for decl in plugin.declared_routines:
            _validate_declaration(plugin.name, decl)


def _validate_declaration(role: str, decl: RoutineDeclaration) -> None:
    """Fail-closed at registration: a declared routine's cron must parse and its env must hold no
    inline secret. Imported locally because ``chorus.cron``/``chorus.trust`` import ``chorus.roles``
    (the validators would otherwise form a cycle at module load)."""
    from datetime import UTC, datetime

    from chorus.cron import parse_cron
    from chorus.errors import InvalidIntake
    from chorus.ledger import RoutineStatus
    from chorus.trust import assert_no_inline_secrets

    if not isinstance(decl.initial_status, RoutineStatus):
        raise RolePluginInvalid(
            f"role {role!r} routine {decl.routine_key!r} has an invalid initial_status"
        )
    try:
        parse_cron(decl.schedule, base=datetime.now(UTC))
    except Exception as exc:
        raise RolePluginInvalid(
            f"role {role!r} routine {decl.routine_key!r} has an invalid schedule "
            f"{decl.schedule!r}: {exc}"
        ) from exc
    try:
        assert_no_inline_secrets(decl.env)
    except InvalidIntake as exc:
        raise RolePluginInvalid(f"role {role!r} routine {decl.routine_key!r} env: {exc}") from exc


def _same_definition(a: RolePlugin, b: RolePlugin) -> bool:
    """Two plugins are the *same definition* iff their manifest, outcome, and generator match.

    The ``dod_generator`` is compared by identity (``is``) because a lambda is never value-equal
    to a structurally-identical sibling — so only a genuinely re-imported plugin (the same function
    object) counts as idempotent; a freshly-built generator is a new definition.
    """
    return (
        a.manifest == b.manifest
        and a.outcome_kind == b.outcome_kind
        and a.dod_generator is b.dod_generator
    )


__all__ = ["RoleRegistry"]
