"""Request middleware for IHMS."""

from __future__ import annotations

from .threadlocals import set_current_request


class AuditRequestMiddleware:
    """Bind the current request to the thread so audit helpers can use it.

    The request is cleared after the response so worker threads do not leak
    state between requests.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        set_current_request(request)
        try:
            response = self.get_response(request)
        finally:
            set_current_request(None)
        return response
