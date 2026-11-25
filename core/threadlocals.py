"""Thread-local request storage used by audit helpers.

A single request is associated with a worker thread for the duration of a
request/response cycle. Domain services use :func:`get_current_user` so audit
entries can be written without threading the request through every call.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from django.http import HttpRequest

_state = threading.local()


def set_current_request(request: "HttpRequest | None") -> None:
    """Store the active request for the current thread."""
    _state.request = request


def get_current_request() -> "HttpRequest | None":
    """Return the active request for the current thread, if any."""
    return getattr(_state, "request", None)


def get_current_user():
    """Return the authenticated user for the current thread, if any."""
    request = get_current_request()
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return user
    return None


def get_client_ip(request: "HttpRequest | None" = None) -> str | None:
    """Best-effort client IP extraction honouring proxy headers."""
    request = request or get_current_request()
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
