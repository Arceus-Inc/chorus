"""Shared HTTP helpers for the hosted tool backends (Strapi, Resend).

Two invariants every hosted backend needs and used to hand-roll (and drift on):

* **Never leak the provider body to the model.** A 4xx/5xx body can echo tenant ids, recipient
  addresses, or field-level validation detail. :func:`ensure_ok` logs the raw body server-side and
  raises a domain error carrying only the HTTP status class.
* **A bad body is a domain error, not an escaping ``JSONDecodeError``.** :func:`json_body` wraps
  ``response.json()`` so a non-JSON 2xx surfaces as the caller's ``error`` type (chained with
  ``from``) — which the tool's ``except CmsError``/``except DeliveryError`` recovery contract
  actually catches, instead of an opaque crash.

``error`` is the domain exception *type* the caller wants (``CmsError`` / ``DeliveryError``), so one
helper serves both packages without coupling them.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

# One place for the hosted-backend client timeout (was duplicated across cms/delivery configs).
HTTP_TIMEOUT_S = 20.0

_logger = logging.getLogger("chorus_tools.http")


def ensure_ok(response: httpx.Response, *, prefix: str, error: type[Exception]) -> None:
    """Raise ``error`` on a non-2xx response; log the provider body server-side only.

    The raised message carries the status class (e.g. ``"strapi publish: HTTP 422"``) — never the
    response body, which stays in the server log.
    """
    if response.status_code // 100 == 2:
        return
    _logger.warning("%s: HTTP %s body=%s", prefix, response.status_code, response.text[:500])
    raise error(f"{prefix}: HTTP {response.status_code}")


def json_body(response: httpx.Response, *, prefix: str, error: type[Exception]) -> Any:
    """Return ``response.json()``, or raise ``error(...) from exc`` if the body is not JSON."""
    try:
        return response.json()
    except ValueError as exc:  # json.JSONDecodeError is a ValueError
        raise error(f"{prefix}: response body was not JSON") from exc


def strapi_document_id(response: httpx.Response, *, prefix: str, error: type[Exception]) -> str:
    """Pull ``data.documentId`` from a Strapi content-API response, or raise ``error``.

    Shared by the cms create/update path and the delivery publish path (same v5 response shape).
    """
    payload = json_body(response, prefix=prefix, error=error)
    data = payload.get("data") if isinstance(payload, dict) else None
    document_id = data.get("documentId") if isinstance(data, dict) else None
    if not isinstance(document_id, str) or not document_id:
        raise error(f"{prefix}: response missing data.documentId")
    return document_id


__all__ = ["HTTP_TIMEOUT_S", "ensure_ok", "json_body", "strapi_document_id"]
