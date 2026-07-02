"""Delivery — executors that turn an APPROVED go-live gate into actual reach (§05 dark node).

Public surface: the value objects (:class:`PublishedRef`, :class:`DeliveryRecord`,
:class:`DeliveryError`), the :class:`PublishBackend` seam with its Strapi + Markdown
implementations, and :class:`ExecuteGoLiveTool` — the fail-closed ``execute_go_live`` verb.
"""

from __future__ import annotations

from chorus_tools.delivery._backend import PublishBackend
from chorus_tools.delivery._config import (
    email_backend_from_env,
    email_delivery_from_env,
    publish_backend_from_env,
)
from chorus_tools.delivery._email_backend import EmailBackend
from chorus_tools.delivery._email_types import (
    EmailMessage,
    EmailRouting,
    email_routing_from_env,
)
from chorus_tools.delivery._markdown_publish import MarkdownPublishBackend
from chorus_tools.delivery._outbox_email import OutboxEmailBackend
from chorus_tools.delivery._resend_email import ResendEmailBackend
from chorus_tools.delivery._send import EmailDelivery
from chorus_tools.delivery._strapi_publish import StrapiPublishBackend
from chorus_tools.delivery._tool import ExecuteGoLiveInput, ExecuteGoLiveTool
from chorus_tools.delivery._types import DeliveryError, DeliveryRecord, PublishedRef

__all__ = [
    "DeliveryError",
    "DeliveryRecord",
    "EmailBackend",
    "EmailDelivery",
    "EmailMessage",
    "EmailRouting",
    "ExecuteGoLiveInput",
    "ExecuteGoLiveTool",
    "MarkdownPublishBackend",
    "OutboxEmailBackend",
    "PublishBackend",
    "PublishedRef",
    "ResendEmailBackend",
    "StrapiPublishBackend",
    "email_backend_from_env",
    "email_delivery_from_env",
    "email_routing_from_env",
    "publish_backend_from_env",
]
