"""WebPluginRegistry — fail-closed + idempotent registration of trust-scoped reach (spec GM §5)."""

from __future__ import annotations

import pytest

from chorus.errors import WebPluginConflict, WebPluginInvalid
from chorus.webplugins import (
    Capability,
    PluginKind,
    SpendCap,
    WebPlugin,
    WebPluginRegistry,
)

pytestmark = pytest.mark.unit


def _read_plugin(name: str = "warehouse") -> WebPlugin:
    return WebPlugin(
        name=name,
        kind=PluginKind.WAREHOUSE,
        capability=Capability.READ,
        auth_ref="ref:warehouse_ro",
        scope="read-only, row/role-scoped views",
    )


def _ads_plugin() -> WebPlugin:
    return WebPlugin(
        name="ads",
        kind=PluginKind.ADS,
        capability=Capability.SPEND,
        auth_ref="ref:ads",
        spend_cap=SpendCap(per_action_cents=500_00, daily_cents=2_000_00),
    )


def test_registers_and_resolves_a_plugin() -> None:
    reg = WebPluginRegistry.from_plugins([_read_plugin(), _ads_plugin()])
    assert set(reg.names()) == {"warehouse", "ads"}
    assert "warehouse" in reg and len(reg) == 2
    assert reg.get("ads").gated is True
    assert reg.get("warehouse").gated is False


def test_re_registering_an_identical_definition_is_idempotent() -> None:
    reg = WebPluginRegistry()
    reg.register(_read_plugin())
    reg.register(_read_plugin())  # no raise — identical definition is a no-op
    assert len(reg) == 1


def test_conflicting_definition_raises_without_replace() -> None:
    reg = WebPluginRegistry()
    reg.register(_read_plugin())
    other = WebPlugin(
        name="warehouse",
        kind=PluginKind.WAREHOUSE,
        capability=Capability.READ,
        auth_ref="ref:warehouse_rw",  # a different auth ref → different definition
    )
    with pytest.raises(WebPluginConflict):
        reg.register(other)
    reg.register(other, replace=True)  # explicit override is allowed
    assert reg.get("warehouse").auth_ref == "ref:warehouse_rw"


def test_inline_secret_is_rejected() -> None:
    bad = WebPlugin(
        name="warehouse",
        kind=PluginKind.WAREHOUSE,
        capability=Capability.READ,
        auth_ref="super-secret-token",  # raw value, not a ref: handle
    )
    with pytest.raises(WebPluginInvalid):
        WebPluginRegistry().register(bad)


def test_gated_plugin_without_a_spend_cap_is_rejected() -> None:
    uncapped = WebPlugin(
        name="ads",
        kind=PluginKind.ADS,
        capability=Capability.SPEND,
        auth_ref="ref:ads",  # gated but no SpendCap
    )
    with pytest.raises(WebPluginInvalid):
        WebPluginRegistry().register(uncapped)


def test_empty_name_is_rejected() -> None:
    with pytest.raises(WebPluginInvalid):
        WebPluginRegistry().register(
            WebPlugin(name="  ", kind=PluginKind.WAREHOUSE, capability=Capability.READ, auth_ref="ref:x")
        )
