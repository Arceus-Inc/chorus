"""Delivery — executors that turn an APPROVED go-live gate into actual reach (§05 dark node).

Public surface: the value objects (:class:`PublishedRef`, :class:`DeliveryRecord`,
:class:`DeliveryError`), the :class:`PublishBackend` seam with its Strapi + Markdown
implementations, and :class:`ExecuteGoLiveTool` — the fail-closed ``execute_go_live`` verb.
"""

from __future__ import annotations

from chorus_tools.delivery._backend import PublishBackend
from chorus_tools.delivery._config import publish_backend_from_env
from chorus_tools.delivery._markdown_publish import MarkdownPublishBackend
from chorus_tools.delivery._strapi_publish import StrapiPublishBackend
from chorus_tools.delivery._tool import ExecuteGoLiveInput, ExecuteGoLiveTool
from chorus_tools.delivery._types import DeliveryError, DeliveryRecord, PublishedRef

__all__ = [
    "DeliveryError",
    "DeliveryRecord",
    "ExecuteGoLiveInput",
    "ExecuteGoLiveTool",
    "MarkdownPublishBackend",
    "PublishBackend",
    "PublishedRef",
    "StrapiPublishBackend",
    "publish_backend_from_env",
]
