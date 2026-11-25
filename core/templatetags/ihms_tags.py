"""Custom template tags and filters for IHMS."""

from __future__ import annotations

from django import template

from core.permissions import user_has_any_perm, user_has_perms
from core.utils.formatting import format_date, format_datetime, format_money

register = template.Library()


@register.filter(name="bdt")
def bdt(value, symbol: bool = True) -> str:
    """Render a value as BDT currency (``৳1,234.00``)."""
    return format_money(value, symbol=bool(symbol))


@register.filter(name="ihms_date")
def ihms_date(value) -> str:
    """Render a date as ``DD/MM/YYYY``."""
    return format_date(value)


@register.filter(name="ihms_datetime")
def ihms_datetime(value) -> str:
    """Render a datetime as ``DD/MM/YYYY HH:MM``."""
    return format_datetime(value)


@register.filter(name="change_perm")
def change_perm(model) -> str:
    """Return the ``change_<model>`` permission codename for a model class."""
    meta = model._meta
    return f"{meta.app_label}.change_{meta.model_name}"


@register.filter(name="delete_perm")
def delete_perm(model) -> str:
    """Return the ``delete_<model>`` permission codename for a model class."""
    meta = model._meta
    return f"{meta.app_label}.delete_{meta.model_name}"


@register.filter(name="add_perm")
def add_perm(model) -> str:
    """Return the ``add_<model>`` permission codename for a model class."""
    meta = model._meta
    return f"{meta.app_label}.add_{meta.model_name}"


@register.simple_tag
def has_perm(user, *codenames: str) -> bool:
    """Return ``True`` when the user holds every given permission."""
    return user_has_perms(user, list(codenames))


@register.simple_tag
def has_any_perm(user, *codenames: str) -> bool:
    """Return ``True`` when the user holds at least one permission."""
    return user_has_any_perm(user, list(codenames))


@register.simple_tag(takes_context=True)
def active(context, url_name: str, css: str = "active") -> str:
    """Return ``css`` when the current request resolves to ``url_name``."""
    request = context.get("request")
    if request is None:
        return ""
    from django.urls import resolve

    try:
        match = resolve(request.path_info)
    except Exception:  # pragma: no cover - defensive
        return ""
    if match.url_name == url_name or match.view_name == url_name:
        return css
    return ""


@register.simple_tag
def nav_url(url_name: str) -> str:
    """Resolve a navigation URL name, degrading to ``#`` when unavailable."""
    if not url_name:
        return "#"
    from django.urls import NoReverseMatch, reverse

    try:
        return reverse(url_name)
    except NoReverseMatch:
        return "#"


@register.simple_tag(takes_context=True)
def is_active_nav(context, url_name: str) -> bool:
    """Return ``True`` when the current view matches ``url_name``'s namespace."""
    request = context.get("request")
    if request is None or not url_name:
        return False
    from django.urls import resolve

    try:
        match = resolve(request.path_info)
    except Exception:  # pragma: no cover - defensive
        return False
    if match.view_name == url_name:
        return True
    namespace = url_name.split(":")[0]
    return bool(match.namespace and match.namespace.startswith(namespace))


@register.inclusion_tag("components/status_badge.html")
def status_badge(label: str, variant: str = "neutral") -> dict:
    """Render a coloured status pill.

    Args:
        label: Display text (translated by the caller).
        variant: One of ``success``, ``warning``, ``danger``, ``info``, ``neutral``.
    """
    variants = {"success", "warning", "danger", "info", "neutral", "critical"}
    if variant not in variants:
        variant = "neutral"
    return {"label": label, "variant": variant}
