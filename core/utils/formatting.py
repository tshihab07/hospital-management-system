"""Localised formatting helpers (BDT, BST, DD/MM/YYYY).

Localization is a CORE skill (CORE-10): currency is BDT (৳), dates are
``DD/MM/YYYY`` and all timestamps are Asia/Dhaka (BST).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.utils import timezone
from django.utils.formats import date_format

CURRENCY_SYMBOL = "৳"
DATE_FORMAT = "d/m/Y"
DATETIME_FORMAT = "d/m/Y H:i"


def format_money(amount, *, symbol: bool = True, places: int = 2) -> str:
    """Format a numeric amount as BDT with thousands separators.

    Args:
        amount: Value convertible to :class:`~decimal.Decimal`.
        symbol: Prefix the result with the ``৳`` symbol.
        places: Number of decimal places.

    Returns:
        A display string such as ``"৳1,250.00"``.
    """
    try:
        value = Decimal(str(amount if amount is not None else 0))
    except (InvalidOperation, ValueError):
        value = Decimal("0")
    quantised = value.quantize(Decimal("1." + "0" * places))
    formatted = f"{quantised:,.{places}f}"
    return f"{CURRENCY_SYMBOL}{formatted}" if symbol else formatted


def localdate(value):
    """Return ``value`` converted to the current (Asia/Dhaka) local date."""
    if value is None:
        return None
    return timezone.localtime(value).date() if hasattr(value, "tzinfo") else value


def format_date(value, fmt: str = DATE_FORMAT) -> str:
    """Format a date/datetime using the IHMS date format."""
    if not value:
        return ""
    return date_format(value, fmt)


def format_datetime(value, fmt: str = DATETIME_FORMAT) -> str:
    """Format a datetime using the IHMS datetime format."""
    if not value:
        return ""
    return date_format(timezone.localtime(value), fmt)
