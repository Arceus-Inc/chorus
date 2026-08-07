"""Step-1 eval: chorus OTLP EventSink contracts (spec 08 §4).

Run: ``uv run --extra otel python evals/otel/eval_step1_chorus_otlp.py``
Exit 0 iff all checks pass.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def _check(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"[{status}] {name}{suffix}")
    if not ok:
        raise SystemExit(1)


def main() -> None:
    for key in list(sys.modules):
        if key.startswith("opentelemetry"):
            del sys.modules[key]
    os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)

    from chorus.observability._otel_config import is_otel_enabled

    _check("disabled without endpoint", not is_otel_enabled())
    from chorus.observability._otel import otel_sink_if_configured

    _check("sink none when unset", otel_sink_if_configured() is None)
    _check(
        "no otel import when disabled",
        not any(k.startswith("opentelemetry") for k in sys.modules),
    )

    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://127.0.0.1:4318"
    try:
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        from chorus.events import Event, EventKind
        from chorus.observability._otel_config import OtelConfig
        from chorus.observability._otel_impl import build_otel_sink, reset_otel_provider_for_tests

        reset_otel_provider_for_tests()
        memory = InMemorySpanExporter()
        sink = build_otel_sink(
            OtelConfig(
                enabled=True,
                endpoint="http://127.0.0.1:4318",
                service_name="chorus-eval",
                service_version="0.0.0-eval",
                insecure=True,
            ),
            span_exporter=memory,
        )
        at = datetime(2026, 8, 7, tzinfo=UTC)
        task_id = "eval-task"
        for event in (
            Event(kind=EventKind.RUN_STARTED, at=at, task_id=task_id, payload={}),
            Event(
                kind=EventKind.RUN_TOOL_USE,
                at=at,
                task_id=task_id,
                payload={"tool": "bash"},
            ),
            Event(
                kind=EventKind.RUN_TOOL_RESULT,
                at=at,
                task_id=task_id,
                payload={"tool": "bash", "is_error": False},
            ),
            Event(
                kind=EventKind.RUN_EVALUATED,
                at=at,
                task_id=task_id,
                payload={"outcome": "completed", "score": 1.0},
            ),
            Event(kind=EventKind.RUN_DONE, at=at, task_id=task_id, payload={}),
        ):
            sink.emit(event)

        names = {span.name for span in memory.get_finished_spans()}
        _check("beat root present", f"beat.{task_id}" in names, str(names))
        _check("tool child present", "tool.bash" in names, str(names))
        root = next(s for s in memory.get_finished_spans() if s.name == f"beat.{task_id}")
        assert root.attributes is not None
        _check(
            "eval outcome on root",
            root.attributes.get("chorus.eval.outcome") == "completed",
        )
    except ImportError as exc:
        _check("otel extra installed", False, str(exc))
    finally:
        os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
        try:
            from chorus.observability._otel_impl import reset_otel_provider_for_tests

            reset_otel_provider_for_tests()
        except ImportError:
            pass

    print("eval_step1_chorus_otlp: all checks passed")


if __name__ == "__main__":
    main()
