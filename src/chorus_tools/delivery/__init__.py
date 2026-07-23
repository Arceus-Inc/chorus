"""Delivery — executors that turn an APPROVED go-live gate into actual reach (§05 dark node).

Two channels, one per sub-package: :mod:`.publish` (flip a staged CMS draft LIVE — blog/social)
and :mod:`.email` (send an approved draft over an ESP). The shared spine stays at this level: the
value objects (:mod:`._types`), the per-approval idempotency :class:`~._index.DeliveryIndex`, the
backend selection (:mod:`._config`), and :class:`ExecuteGoLiveTool` — the fail-closed
``execute_go_live`` verb that drives both channels.
"""

from __future__ import annotations

from chorus_tools.delivery._config import (
    email_backend_from_env,
    email_delivery_from_env,
    publish_backend_from_env,
)
from chorus_tools.delivery._tool import ExecuteGoLiveInput, ExecuteGoLiveTool
from chorus_tools.delivery._types import DeliveryError, DeliveryRecord, PublishedRef
from chorus_tools.delivery.email import (
    EmailBackend,
    EmailDelivery,
    EmailMessage,
    EmailRouting,
    OutboxEmailBackend,
    ResendEmailBackend,
    email_routing_from_env,
)
from chorus_tools.delivery.publish import (
    MarkdownPublishBackend,
    PublishBackend,
    StrapiPublishBackend,
)

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
