"""Template context processors for IHMS."""

from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from .navigation import NAV_SECTIONS


def ihms_context(request) -> dict:
    """Expose global IHMS configuration and navigation state to templates."""
    ihms = getattr(settings, "IHMS", {})
    return {
        "IHMS": ihms,
        "CURRENCY_SYMBOL": ihms.get("CURRENCY_SYMBOL", "৳"),
        "HOSPITAL_NAME": ihms.get("HOSPITAL_NAME", "Integrated Hospital"),
        "today": timezone.localdate(),
        "now": timezone.localtime(),
        "current_language": getattr(request, "LANGUAGE_CODE", settings.LANGUAGE_CODE),
        "is_dark": request.COOKIES.get("theme") == "dark" if request else False,
        "nav_sections": NAV_SECTIONS,
    }
