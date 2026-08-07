"""OTLP export — on by default (spec 08 §4, default-on revision).

The EventBus always fans out to an OTel span sink unless ``OTEL_SDK_DISABLED``
is set. Endpoint defaults to ``http://localhost:4318``. The config module still
imports no ``opentelemetry``; the SDK loads when the sink is constructed.

The sink keys the beat span tree on ``task_id``.
"""

from __future__ import annotations

import logging

from chorus.observability._bus import EventSink, FanoutBus
from chorus.observability._otel_config import is_otel_enabled, load_otel_config

_logger = logging.getLogger("chorus.observability.otel")


def otel_sink_if_configured() -> EventSink | None:
    """Build the OTel span sink unless the SDK is disabled.

    Returns ``None`` when ``OTEL_SDK_DISABLED`` is set. On ImportError (broken
    install), warns once and returns ``None`` rather than failing the run.
    """
    if not is_otel_enabled():
        return None
    try:
        from chorus.observability._otel_impl import build_otel_sink

        return build_otel_sink(load_otel_config())
    except ImportError:
        _logger.warning(
            "OpenTelemetry packages failed to import; running without OTLP export. "
            "Ensure opentelemetry-api/sdk/exporter are installed.",
        )
        return None


def with_otel_export(bus: EventSink) -> EventSink:
    """Fan a bus out to the OTel sink (default), or return it unchanged if disabled."""
    sink = otel_sink_if_configured()
    if sink is None:
        return bus
    return FanoutBus(bus, sink)


__all__ = ["otel_sink_if_configured", "with_otel_export"]
