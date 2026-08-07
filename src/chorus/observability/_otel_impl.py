"""Optional OTLP export — the impl (spec 08 §4).

Imports ``opentelemetry`` at module top, so it is imported ONLY via ``_otel``'s
lazy, env-gated path — never at ``import chorus.observability`` time.

Maps a beat's ``run.*`` event stream onto an OTel span tree keyed by ``task_id``.
One root span per beat (``RUN_STARTED`` → ``RUN_DONE``); tool calls, LLM sessions,
and subagents are child spans. The evaluator verdict (``RUN_EVALUATED``) is recorded
on the root as ``chorus.eval.outcome`` / ``chorus.eval.score`` attributes.
"""

from __future__ import annotations

import atexit
import logging
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import cast

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import Span as SdkSpan
from opentelemetry.trace import Status, StatusCode
from opentelemetry.trace import Tracer as SdkTracer
from opentelemetry.util.types import Attributes

from chorus.events import Event, EventKind
from chorus.observability._otel_config import OtelConfig

_logger = logging.getLogger("chorus.observability.otel")

AttributeValue = str | bool | int | float | Sequence[str]

_provider: TracerProvider | None = None
_handle: OtelProviderHandle | None = None


@dataclass(frozen=True)
class OtelProviderHandle:
    """Live provider + tracer for one process."""

    enabled: bool
    tracer: SdkTracer
    provider: TracerProvider
    service_name: str
    service_version: str

    def force_flush(self, timeout_millis: int = 5_000) -> bool:
        return bool(self.provider.force_flush(timeout_millis))

    def shutdown(self) -> None:
        self.provider.shutdown()


class OtelSpanSink:
    """Map a beat's ``run.*`` event stream onto an OTel span tree, keyed by task_id."""

    def __init__(self, handle: OtelProviderHandle) -> None:
        self._handle = handle
        self._roots: dict[str, SdkSpan] = {}
        self._tools: dict[str, list[SdkSpan]] = {}
        self._subagents: dict[str, list[SdkSpan]] = {}

    def emit(self, event: Event) -> None:
        task_id = event.task_id
        if task_id is None:
            return
        kind = event.kind
        if kind is EventKind.RUN_STARTED:
            self._start_beat(task_id)
        elif kind is EventKind.RUN_TOOL_USE:
            self._start_tool(task_id, event)
        elif kind is EventKind.RUN_TOOL_RESULT:
            self._end_tool(task_id, event)
        elif kind is EventKind.LLM_CALL:
            self._record_llm_call(task_id, event)
        elif kind is EventKind.RUN_EVALUATED:
            self._record_verdict(task_id, event)
        elif kind is EventKind.SUBAGENT_SPAWNED:
            self._start_subagent(task_id, event)
        elif kind is EventKind.SUBAGENT_COMPLETED:
            self._end_subagent(task_id, event)
        elif kind is EventKind.RUN_DONE:
            self._end_beat(task_id)

    def _base_attributes(self, task_id: str) -> dict[str, AttributeValue]:
        return {
            "service.name": self._handle.service_name,
            "service.version": self._handle.service_version,
            "chorus.task_id": task_id,
        }

    def _start_beat(self, task_id: str) -> None:
        span = self._handle.tracer.start_span(
            f"beat.{task_id}",
            attributes=_as_otel_attributes(self._base_attributes(task_id)),
        )
        self._roots[task_id] = span

    def _start_tool(self, task_id: str, event: Event) -> None:
        root = self._roots.get(task_id)
        if root is None:
            return
        tool = payload_str(event.payload, "tool") or "tool"
        attrs = self._base_attributes(task_id)
        attrs["tool.name"] = tool
        span = self._start_child(root, f"tool.{tool}", attrs)
        self._tools.setdefault(task_id, []).append(span)

    def _end_tool(self, task_id: str, event: Event) -> None:
        stack = self._tools.get(task_id)
        if not stack:
            return
        span = stack.pop()
        is_error = payload_bool(event.payload, "is_error")
        if is_error is True:
            span.set_status(Status(StatusCode.ERROR))
        span.end()

    def _record_llm_call(self, task_id: str, event: Event) -> None:
        root = self._roots.get(task_id)
        if root is None:
            return
        attrs = self._base_attributes(task_id)
        attrs.update(_gen_ai_attributes(event.payload))
        span = self._start_child(root, "llm.call", attrs)
        span.end()

    def _record_verdict(self, task_id: str, event: Event) -> None:
        root = self._roots.get(task_id)
        if root is None:
            return
        outcome = payload_str(event.payload, "outcome")
        if outcome is not None:
            root.set_attribute("chorus.eval.outcome", outcome)
        score = payload_float(event.payload, "score")
        if score is not None:
            root.set_attribute("chorus.eval.score", score)

    def _start_subagent(self, task_id: str, event: Event) -> None:
        root = self._roots.get(task_id)
        if root is None:
            return
        name = payload_str(event.payload, "subagent_name") or "subagent"
        attrs = self._base_attributes(task_id)
        attrs["subagent.name"] = name
        span = self._start_child(root, f"subagent.{name}", attrs)
        self._subagents.setdefault(task_id, []).append(span)

    def _end_subagent(self, task_id: str, event: Event) -> None:
        stack = self._subagents.get(task_id)
        if not stack:
            return
        span = stack.pop()
        is_error = payload_bool(event.payload, "is_error")
        if is_error is True:
            span.set_status(Status(StatusCode.ERROR))
        span.end()

    def _end_beat(self, task_id: str) -> None:
        for span in self._tools.pop(task_id, []):
            span.end()
        for span in self._subagents.pop(task_id, []):
            span.end()
        root = self._roots.pop(task_id, None)
        if root is not None:
            root.end()
        self._handle.force_flush()

    def _start_child(
        self,
        parent: SdkSpan,
        name: str,
        attributes: Mapping[str, AttributeValue],
    ) -> SdkSpan:
        ctx = trace.set_span_in_context(parent)
        return self._handle.tracer.start_span(
            name,
            context=ctx,
            attributes=_as_otel_attributes(attributes),
        )


def build_otel_sink(
    config: OtelConfig,
    *,
    span_exporter: SpanExporter | None = None,
) -> OtelSpanSink:
    """Wire a real OTel tracer and return the span sink."""
    handle = build_tracer_provider(config, span_exporter=span_exporter)
    return OtelSpanSink(handle)


def build_tracer_provider(
    config: OtelConfig,
    *,
    span_exporter: SpanExporter | None = None,
) -> OtelProviderHandle:
    """Build (or return cached) TracerProvider."""
    global _provider, _handle
    if _handle is not None and span_exporter is None:
        return _handle

    resource = Resource.create(
        {
            "service.name": config.service_name,
            "service.version": config.service_version,
        }
    )
    provider = TracerProvider(resource=resource)
    exporter = span_exporter
    if exporter is None and config.enabled and config.endpoint is not None:
        exporter = _build_otlp_exporter(config.endpoint)
    if exporter is not None:
        provider.add_span_processor(BatchSpanProcessor(exporter))
    if span_exporter is None:
        trace.set_tracer_provider(provider)
        _provider = provider
        atexit.register(_shutdown_provider)
    tracer = provider.get_tracer("chorus.observability", config.service_version)
    handle = OtelProviderHandle(
        enabled=True,
        tracer=tracer,
        provider=provider,
        service_name=config.service_name,
        service_version=config.service_version,
    )
    if span_exporter is None:
        _handle = handle
    return handle


def reset_otel_provider_for_tests() -> None:
    """Drop the process-global provider (tests only)."""
    global _provider, _handle
    if _handle is not None:
        with suppress(Exception):
            _handle.shutdown()
    _provider = None
    _handle = None


def _as_otel_attributes(attributes: Mapping[str, AttributeValue]) -> Attributes:
    return cast(Attributes, dict(attributes))


def payload_str(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def payload_bool(payload: Mapping[str, object], key: str) -> bool | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return None


def payload_int(payload: Mapping[str, object], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def payload_float(payload: Mapping[str, object], key: str) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _gen_ai_attributes(payload: Mapping[str, object]) -> dict[str, AttributeValue]:
    attrs: dict[str, AttributeValue] = {}
    model = payload_str(payload, "model")
    if model is not None:
        attrs["gen_ai.request.model"] = model
    role = payload_str(payload, "role")
    if role is not None:
        attrs["gen_ai.request.role"] = role
    input_tokens = payload_int(payload, "input_tokens")
    if input_tokens is not None:
        attrs["gen_ai.usage.input_tokens"] = input_tokens
    output_tokens = payload_int(payload, "output_tokens")
    if output_tokens is not None:
        attrs["gen_ai.usage.output_tokens"] = output_tokens
    cache_read = payload_int(payload, "cache_read_tokens")
    if cache_read is not None:
        attrs["gen_ai.usage.cache_read_tokens"] = cache_read
    cost = payload_float(payload, "cost_usd")
    if cost is not None:
        attrs["gen_ai.usage.cost_usd"] = cost
    return attrs


def _build_otlp_exporter(endpoint: str) -> SpanExporter:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    return OTLPSpanExporter(endpoint=_traces_url(endpoint))


def _traces_url(endpoint: str) -> str:
    base = endpoint.rstrip("/")
    if base.endswith("/v1/traces"):
        return base
    return f"{base}/v1/traces"


def _shutdown_provider() -> None:
    global _provider, _handle
    if _handle is not None:
        try:
            _handle.shutdown()
        except Exception:
            _logger.debug("otel provider shutdown failed", exc_info=True)
    _provider = None
    _handle = None


__all__ = [
    "AttributeValue",
    "OtelProviderHandle",
    "OtelSpanSink",
    "build_otel_sink",
    "build_tracer_provider",
    "payload_bool",
    "payload_float",
    "payload_int",
    "payload_str",
    "reset_otel_provider_for_tests",
]
