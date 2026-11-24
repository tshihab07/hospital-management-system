"""Presentation helpers for the Reports & Analytics module."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django import template

from core.utils.formatting import format_date, format_datetime, format_money

register = template.Library()


@register.filter(name="rpt_cell")
def rpt_cell(value, kind: str = "text") -> str:
    """Format a single report cell according to its column ``kind``.

    ``kind`` is one of the values emitted by :mod:`apps.reports.selectors`
    (``money``, ``number``, ``percent``, ``date``, ``datetime``, ``text``).
    """
    if value in (None, ""):
        return ""
    if kind == "money":
        return format_money(value) if _is_number(value) else str(value)
    if kind == "percent":
        return f"{_trim(value)}%" if _is_number(value) else str(value)
    if kind == "number":
        return _trim(value) if _is_number(value) else str(value)
    if kind == "date":
        return format_date(value) if hasattr(value, "strftime") else str(value)
    if kind == "datetime":
        return format_datetime(value) if hasattr(value, "strftime") else str(value)
    return str(value)


@register.filter(name="rpt_at")
def rpt_at(sequence, index):
    """Return ``sequence[index]`` or ``""`` when out of range."""
    try:
        return sequence[int(index)]
    except (IndexError, TypeError, ValueError):
        return ""


@register.simple_tag(name="rpt_cell_at")
def rpt_cell_at(value, formats, index) -> str:
    """Format ``value`` using the column kind at ``index`` in ``formats``."""
    try:
        kind = formats[int(index)]
    except (IndexError, TypeError, ValueError):
        kind = "text"
    return rpt_cell(value, kind)


def _trim(value) -> str:
    if isinstance(value, Decimal):
        value = value.normalize()
    if isinstance(value, float):
        text = f"{value:,.2f}".rstrip("0").rstrip(".")
        return text
    try:
        return f"{int(value):,}"
    except (TypeError, InvalidOperation, ValueError):
        return str(value)


def _is_number(value) -> bool:
    if isinstance(value, bool):
        return False
    try:
        Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return False
    return True
