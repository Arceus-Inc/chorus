"""Web research integration — read-only `web_search` / `web_fetch` backed by Tavily.

The Analyst's window onto the world, as a first-class integration (spec: ``WebPlugin =
(name, kind, capability, auth secret-ref, trust scope, caps)``). Both tools are **read-only** (HTTP
GET-equivalent), network-scoped to a single allowlisted host (``api.tavily.com``), and read their key
from the ``TAVILY_API_KEY`` env var — a secret-ref, never hardcoded. When the key is absent the tools
fail cleanly ("unavailable") rather than erroring the beat, so a harness without the integration
degrades gracefully.

The single HTTP entrypoint :func:`_tavily_post` is module-level so tests can monkeypatch it and run
fully hermetically (no network, no key).
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration, ToolEffects
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel, Field

__all__ = [
    "WebFetchInput",
    "WebFetchTool",
    "WebSearchInput",
    "WebSearchTool",
    "web_tool",
]

_TAVILY_HOST = "api.tavily.com"
_TAVILY_BASE = f"https://{_TAVILY_HOST}"
_API_KEY_ENV = "TAVILY_API_KEY"
_OUTPUT_CAP = 12_000


def _cap(text: str, limit: int = _OUTPUT_CAP) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n... [truncated {len(text) - limit} chars]"


def _api_key() -> str | None:
    key = os.environ.get(_API_KEY_ENV, "").strip()
    return key or None


async def _tavily_post(endpoint: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    """POST to a Tavily endpoint and return the parsed JSON. The one network seam (mockable in tests)."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{_TAVILY_BASE}/{endpoint}", json=payload)
        resp.raise_for_status()
        return resp.json()


def _unavailable() -> ToolResult:
    return ToolResult(
        content=(
            f"web integration unavailable: no {_API_KEY_ENV} configured. Proceed with the data you "
            "have, or ask an operator to enable web access."
        ),
        is_error=True,
        metadata={"root_cause": "no-web-credential", "stop_condition": "do not retry until a key is set"},
    )


# --------------------------------------------------------------------------- web_search


class WebSearchInput(BaseModel):
    """Arguments for ``web_search``."""

    query: str = Field(description="The search query.")
    max_results: int = Field(default=5, ge=1, le=10, description="How many results to return.")


class WebSearchTool(BaseTool):
    """Search the web (read-only) and return a short answer plus ranked result titles/URLs/snippets."""

    name = "web_search"
    description = (
        "Search the public web for current information. Returns a concise answer plus the top results "
        "(title, URL, snippet). Read-only. Use it to find sources, then `web_fetch` a URL to read a "
        "page in full. Always cite the URLs you used in your findings."
    )
    declaration = ToolDeclaration(risk="safe", tier_required=0, timeout_seconds=30.0)
    input_model = WebSearchInput

    def is_read_only_for(self, input: dict[str, Any]) -> bool:
        return True

    def effects_for(self, input: dict[str, Any]) -> ToolEffects:
        return ToolEffects(network_host=_TAVILY_HOST)

    async def execute(self, input: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        args = WebSearchInput.model_validate(input)
        if _api_key() is None:
            return _unavailable()
        payload = {
            "api_key": _api_key(),
            "query": args.query,
            "max_results": args.max_results,
            "search_depth": "basic",
            "include_answer": True,
        }
        try:
            data = await _tavily_post("search", payload, timeout=self.declaration.timeout_seconds)
        except httpx.HTTPError as exc:
            return ToolResult(content=f"web_search failed: {exc}", is_error=True, metadata={"root_cause": "http-error"})
        results = data.get("results", []) or []
        lines: list[str] = []
        answer = (data.get("answer") or "").strip()
        if answer:
            lines.append(f"answer: {answer}\n")
        for i, r in enumerate(results, start=1):
            title = str(r.get("title", "")).strip()
            url = str(r.get("url", "")).strip()
            snippet = str(r.get("content", "")).strip().replace("\n", " ")
            lines.append(f"{i}. {title}\n   {url}\n   {snippet[:280]}")
        body = "\n".join(lines) if lines else "(no results)"
        return ToolResult(content=_cap(body), metadata={"results": len(results), "host": _TAVILY_HOST})


# --------------------------------------------------------------------------- web_fetch


class WebFetchInput(BaseModel):
    """Arguments for ``web_fetch``."""

    url: str = Field(description="The URL to fetch and extract readable text from.")


class WebFetchTool(BaseTool):
    """Fetch a URL (read-only) and return its extracted readable text."""

    name = "web_fetch"
    description = (
        "Fetch a single web page (read-only) and return its readable text, so you can read a source "
        "you found with `web_search` in full. Cite the URL in your findings."
    )
    declaration = ToolDeclaration(risk="safe", tier_required=0, timeout_seconds=30.0)
    input_model = WebFetchInput

    def is_read_only_for(self, input: dict[str, Any]) -> bool:
        return True

    def effects_for(self, input: dict[str, Any]) -> ToolEffects:
        return ToolEffects(network_host=_TAVILY_HOST)

    async def execute(self, input: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        args = WebFetchInput.model_validate(input)
        if not args.url.lower().startswith(("http://", "https://")):
            return ToolResult(content=f"refused: url must be http(s), got {args.url!r}", is_error=True)
        if _api_key() is None:
            return _unavailable()
        payload = {"api_key": _api_key(), "urls": [args.url]}
        try:
            data = await _tavily_post("extract", payload, timeout=self.declaration.timeout_seconds)
        except httpx.HTTPError as exc:
            return ToolResult(content=f"web_fetch failed: {exc}", is_error=True, metadata={"root_cause": "http-error"})
        results = data.get("results", []) or []
        if not results:
            failed = data.get("failed_results", []) or []
            reason = failed[0].get("error") if failed else "no content extracted"
            return ToolResult(content=f"web_fetch: could not extract {args.url} ({reason})", is_error=True)
        content = str(results[0].get("raw_content", "")).strip()
        return ToolResult(content=_cap(content) or "(empty page)", metadata={"url": args.url})


# --------------------------------------------------------------------------- resolver


def web_tool(name: str) -> BaseTool | None:
    """Build the web integration tool for ``name`` (read-only, network-scoped), or ``None``."""
    if name == "web_search":
        return WebSearchTool()
    if name == "web_fetch":
        return WebFetchTool()
    return None
