"""Permission helpers for IHMS.

Permissions follow the Django convention ``<app_label>.<action>_<model>``
(e.g. ``patients.view_patient``), matching RULES §4.1 (module/page/action
level access). Custom actions are declared via ``Meta.permissions``.
"""

from __future__ import annotations


def codename(app_label: str, action: str, model: str) -> str:
    """Build a Django permission codename.

    Args:
        app_label: The Django app label (e.g. ``patients``).
        action: One of ``add``, ``view``, ``change``, ``delete`` or a custom action.
        model: The lowercase model name (e.g. ``patient``).

    Returns:
        The ``"<app_label>.<action>_<model>"`` codename.
    """
    return f"{app_label}.{action}_{model}"


def user_has_perms(user, codenames: list[str]) -> bool:
    """Return ``True`` when the user holds every codename in ``codenames``."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    return all(user.has_perm(name) for name in codenames)


def user_has_any_perm(user, codenames: list[str]) -> bool:
    """Return ``True`` when the user holds at least one of ``codenames``."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    return any(user.has_perm(name) for name in codenames)
