"""Top-level views: health check, root redirect and error handlers."""

from __future__ import annotations

from django.http import JsonResponse
from django.shortcuts import redirect, render


def health(request):
    """Liveness probe used by uptime monitors and CI smoke tests."""
    return JsonResponse({"status": "ok", "service": "ihms"})


def root_redirect(request):
    """Send users to the control tower, portal or login from the site root."""
    if request.user.is_authenticated:
        if getattr(request.user, "is_staff", False) or request.user.is_superuser:
            return redirect("panel:home")
        if getattr(request.user, "patient_profile", None) is not None:
            return redirect("portal:dashboard")
        return redirect("panel:home")
    return redirect("accounts:login")


def handler403(request, exception=None):
    """Render the 403 page with a friendly message."""
    return render(request, "errors/403.html", status=403)


def handler404(request, exception=None):
    """Render the 404 page."""
    return render(request, "errors/404.html", status=404)


def handler500(request):
    """Render the 500 page without leaking stack traces."""
    return render(request, "errors/500.html", status=500)
