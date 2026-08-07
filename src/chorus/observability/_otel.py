"""Optional OTLP export — the gate (spec 08 §4).

Zero-cost when off: this module imports **no** ``opentelemetry``. The heavy impl
(``_otel_impl``) is imported lazily, and only when ``OTEL_EXPORTER_OTLP_ENDPOINT``
is set — so ``import chorus.observability`` pulls no OTel packages and a run with
the endpoint unset pays nothing (no import, no span, no overhead).

The sink keys the beat span tree on ``task_id``: ``run.*`` events carry a stable
task_id across a beat today, whereas ``trace_id``/``run_id`` are not yet threaded
onto the beat stream (08 §6 is still aspirational).
"""

from __future__ import annotations

import logging

from chorus.observability._bus import EventSink
from chorus.observability._otel_config import is_otel_enabled

_logger = logging.getLogger("chorus.observability.otel")


def otel_sink_if_configured() -> EventSink | None:
    """Build the OTel span sink iff ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set, else ``None``.

    Returns ``None`` — importing nothing — when the endpoint is unset. When set but
    the ``opentelemetry`` packages are missing, warns once and returns ``None``
    (graceful degradation, 08 §4) rather than failing the run.
    """
    if not is_otel_enabled():
        return None
    try:
        from chorus.observability._otel_config import load_otel_config
        from chorus.observability._otel_impl import build_otel_sink

        return build_otel_sink(load_otel_config())
    except ImportError:
        _logger.warning(
            "OTEL_EXPORTER_OTLP_ENDPOINT is set but opentelemetry packages are "
            "missing; install chorus[otel]. Running without OTLP export.",
        )
        return None


def with_otel_export(bus: EventSink) -> EventSink:
    """Fan a bus out to the OTel sink when configured, else return it unchanged."""
    sink = otel_sink_if_configured()
    if sink is None:
        return bus
    from chorus.observability._bus import FanoutBus

    return FanoutBus(bus, sink)


__all__ = ["otel_sink_if_configured", "with_otel_export"]
