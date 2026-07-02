"""Hermetic unit tests for the web integration (web_search / web_fetch).

No network, no key: the single HTTP seam ``chorus_tools._web._tavily_post`` is monkeypatched, and the
missing-key path is exercised directly. Confirms read-only classification, network-host effect, result
formatting, and graceful degradation when the credential is absent.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import chorus_tools._web as web
from chorus_tools import WebFetchTool, WebSearchTool, web_tool
from dream.tools._context import ToolExecutionContext

pytestmark = pytest.mark.unit


def _ctx(tmp_path: Path) -> ToolExecutionContext:
    return ToolExecutionContext(working_dir=tmp_path, session_id="s-test")


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def _with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")


@pytest.fixture
def _no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)


# --------------------------------------------------------------------------- web_search


def test_web_search_formats_answer_and_results(monkeypatch, tmp_path, _with_key) -> None:
    async def fake_post(endpoint, payload, *, timeout):
        assert endpoint == "search" and payload["query"] == "python asyncio"
        assert payload["api_key"] == "test-key"  # key read from env, forwarded
        return {
            "answer": "asyncio is Python's async framework.",
            "results": [
                {"title": "asyncio docs", "url": "https://docs.python.org/3/library/asyncio.html", "content": "The asyncio library..."},
                {"title": "Real Python", "url": "https://realpython.com/async-io-python/", "content": "A tutorial..."},
            ],
        }

    monkeypatch.setattr(web, "_tavily_post", fake_post)
    res = _run(WebSearchTool().execute({"query": "python asyncio"}, _ctx(tmp_path)))
    assert not res.is_error
    assert "asyncio is Python's async framework." in res.content
    assert "https://docs.python.org/3/library/asyncio.html" in res.content
    assert res.metadata["results"] == 2


def test_web_search_read_only_and_network_scoped() -> None:
    tool = WebSearchTool()
    assert tool.is_read_only_for({"query": "x"}) is True
    assert tool.effects_for({"query": "x"}).network_host == "api.tavily.com"


def test_web_search_no_key_degrades_cleanly(monkeypatch, tmp_path, _no_key) -> None:
    called = False

    async def fake_post(*a, **k):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(web, "_tavily_post", fake_post)
    res = _run(WebSearchTool().execute({"query": "x"}, _ctx(tmp_path)))
    assert res.is_error and "unavailable" in res.content
    assert called is False  # never hits the network without a key


def test_web_search_http_error_is_a_clean_tool_error(monkeypatch, tmp_path, _with_key) -> None:
    import httpx

    async def fake_post(*a, **k):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(web, "_tavily_post", fake_post)
    res = _run(WebSearchTool().execute({"query": "x"}, _ctx(tmp_path)))
    assert res.is_error and "web_search failed" in res.content


# --------------------------------------------------------------------------- web_fetch


def test_web_fetch_returns_extracted_text(monkeypatch, tmp_path, _with_key) -> None:
    async def fake_post(endpoint, payload, *, timeout):
        assert endpoint == "extract" and payload["urls"] == ["https://example.com"]
        return {"results": [{"url": "https://example.com", "raw_content": "Hello from the page."}]}

    monkeypatch.setattr(web, "_tavily_post", fake_post)
    res = _run(WebFetchTool().execute({"url": "https://example.com"}, _ctx(tmp_path)))
    assert not res.is_error and "Hello from the page." in res.content


def test_web_fetch_rejects_non_http(tmp_path, _with_key) -> None:
    res = _run(WebFetchTool().execute({"url": "file:///etc/passwd"}, _ctx(tmp_path)))
    assert res.is_error and "must be http" in res.content


def test_web_fetch_reports_extraction_failure(monkeypatch, tmp_path, _with_key) -> None:
    async def fake_post(endpoint, payload, *, timeout):
        return {"results": [], "failed_results": [{"url": "https://x", "error": "403 Forbidden"}]}

    monkeypatch.setattr(web, "_tavily_post", fake_post)
    res = _run(WebFetchTool().execute({"url": "https://x"}, _ctx(tmp_path)))
    assert res.is_error and "could not extract" in res.content


def test_web_fetch_no_key_degrades_cleanly(tmp_path, _no_key) -> None:
    res = _run(WebFetchTool().execute({"url": "https://x"}, _ctx(tmp_path)))
    assert res.is_error and "unavailable" in res.content


# --------------------------------------------------------------------------- resolver


def test_web_tool_resolves_known_names() -> None:
    assert isinstance(web_tool("web_search"), WebSearchTool)
    assert isinstance(web_tool("web_fetch"), WebFetchTool)
    assert web_tool("not_a_tool") is None
