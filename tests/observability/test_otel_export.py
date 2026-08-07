"""OTel OTLP export — default-on beat span tree."""

from __future__ import annotations

import importlib
import sys
from datetime import UTC, datetime

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from chorus.events import Event, EventKind
from chorus.observability._otel_config import OtelConfig, is_otel_enabled, load_otel_config

pytestmark = pytest.mark.unit


def _task_id() -> str:
    return "task_otel_1"


def _beat_events(task_id: str) -> list[Event]:
    at = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    return [
        Event(kind=EventKind.RUN_STARTED, at=at, task_id=task_id, payload={}),
        Event(
            kind=EventKind.RUN_TOOL_USE,
            at=at,
            task_id=task_id,
            payload={"tool": "bash", "input": {"command": "echo hi"}},
        ),
        Event(
            kind=EventKind.RUN_TOOL_RESULT,
            at=at,
            task_id=task_id,
            payload={"tool": "bash", "is_error": False, "content": "hi"},
        ),
        Event(
            kind=EventKind.LLM_CALL,
            at=at,
            task_id=task_id,
            payload={
                "source": "dream",
                "role": "generator",
                "model": "gpt-test",
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_tokens": 10,
                "cost_usd": 0.01,
            },
        ),
        Event(
            kind=EventKind.SUBAGENT_SPAWNED,
            at=at,
            task_id=task_id,
            payload={"subagent_name": "researcher", "prompt": "look up X"},
        ),
        Event(
            kind=EventKind.SUBAGENT_COMPLETED,
            at=at,
            task_id=task_id,
            payload={"subagent_name": "researcher", "content": "found X", "is_error": False},
        ),
        Event(
            kind=EventKind.RUN_EVALUATED,
            at=at,
            task_id=task_id,
            payload={"outcome": "completed", "score": 0.95},
        ),
        Event(kind=EventKind.RUN_DONE, at=at, task_id=task_id, payload={}),
    ]


def _config() -> OtelConfig:
    return OtelConfig(
        enabled=True,
        endpoint="http://127.0.0.1:4318",
        service_name="chorus-test",
        service_version="0.0.0",
        insecure=True,
    )


@pytest.fixture(autouse=True)
def _reset_otel_provider() -> None:
    from chorus.observability._otel_impl import reset_otel_provider_for_tests

    reset_otel_provider_for_tests()
    yield
    reset_otel_provider_for_tests()


def test_enabled_by_default() -> None:
    assert is_otel_enabled(environ={})
    cfg = load_otel_config(environ={})
    assert cfg.enabled is True
    assert cfg.endpoint == "http://localhost:4318"
    assert cfg.service_name == "chorus"


def test_disabled_via_sdk_flag() -> None:
    env = {"OTEL_SDK_DISABLED": "1"}
    assert not is_otel_enabled(environ=env)
    assert load_otel_config(environ=env).endpoint is None


def test_config_module_does_not_import_opentelemetry() -> None:
    for key in list(sys.modules):
        if key.startswith("opentelemetry"):
            del sys.modules[key]
    mod = importlib.import_module("chorus.observability._otel_config")
    importlib.reload(mod)
    assert not any(k.startswith("opentelemetry") for k in sys.modules)


def test_otel_sink_none_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    from chorus.observability._otel import otel_sink_if_configured

    assert otel_sink_if_configured() is None


def test_with_otel_export_unchanged_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    from chorus.observability import EventBus
    from chorus.observability._otel import with_otel_export

    bus = EventBus()
    assert with_otel_export(bus) is bus


def test_nested_span_tree_for_beat() -> None:
    from chorus.observability._otel_impl import build_otel_sink

    memory = InMemorySpanExporter()
    task_id = _task_id()
    sink = build_otel_sink(_config(), span_exporter=memory)

    for event in _beat_events(task_id):
        sink.emit(event)

    spans = memory.get_finished_spans()
    names = [span.name for span in spans]
    assert f"beat.{task_id}" in names
    assert "tool.bash" in names
    assert "llm.call" in names
    assert "subagent.researcher" in names

    root = next(span for span in spans if span.name == f"beat.{task_id}")
    assert root.attributes is not None
    assert root.attributes.get("service.name") == "chorus-test"
    assert root.attributes.get("service.version") == "0.0.0"
    assert root.attributes.get("chorus.task_id") == task_id
    assert root.attributes.get("chorus.eval.outcome") == "completed"
    assert root.attributes.get("chorus.eval.score") == 0.95

    llm = next(span for span in spans if span.name == "llm.call")
    assert llm.attributes is not None
    assert llm.attributes.get("gen_ai.request.model") == "gpt-test"
    assert llm.attributes.get("gen_ai.usage.input_tokens") == 100
    assert llm.attributes.get("gen_ai.usage.output_tokens") == 50


def test_tool_error_marks_span_status() -> None:
    from chorus.observability._otel_impl import build_otel_sink

    memory = InMemorySpanExporter()
    task_id = _task_id()
    sink = build_otel_sink(_config(), span_exporter=memory)
    at = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)

    sink.emit(Event(kind=EventKind.RUN_STARTED, at=at, task_id=task_id, payload={}))
    sink.emit(
        Event(
            kind=EventKind.RUN_TOOL_USE,
            at=at,
            task_id=task_id,
            payload={"tool": "bash"},
        )
    )
    sink.emit(
        Event(
            kind=EventKind.RUN_TOOL_RESULT,
            at=at,
            task_id=task_id,
            payload={"tool": "bash", "is_error": True},
        )
    )
    sink.emit(Event(kind=EventKind.RUN_DONE, at=at, task_id=task_id, payload={}))

    tool = next(span for span in memory.get_finished_spans() if span.name == "tool.bash")
    assert tool.status.status_code.name == "ERROR"
