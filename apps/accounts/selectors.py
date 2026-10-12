"""Read-only query helpers for identity & access management.

Views must not build querysets inline (RULES §2.2); they call these selectors
so the query logic stays in one testable place.
"""

from __future__ import annotations

from django.contrib.auth.models import Permission
from django.db.models import Count, Q

from .models import Role, User


def user_list(
    *,
    search: str | None = None,
    is_active: bool | None = None,
    role_id: int | None = None,
):
    """Return users matching the given filters, newest first.

    Args:
        search: Matches username, email, English/Bengali name or phone.
        is_active: Filter by active flag when not ``None``.
        role_id: Restrict to users holding the given role id.
    """
    qs = User.objects.prefetch_related("roles").order_by("username")
    if search:
        qs = qs.filter(
            Q(username__icontains=search)
            | Q(email__icontains=search)
            | Q(full_name_en__icontains=search)
            | Q(full_name_bn__icontains=search)
            | Q(phone__icontains=search)
        )
    if is_active is not None:
        qs = qs.filter(is_active=is_active)
    if role_id:
        qs = qs.filter(roles__id=role_id)
    return qs.distinct()


def role_list(*, search: str | None = None):
    """Return roles with an annotated permission count."""
    qs = Role.objects.annotate(perm_count=Count("permissions")).order_by("name")
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(description__icontains=search))
    return qs


def audit_log_list(
    *,
    user_id: int | None = None,
    action: str | None = None,
    model_name: str | None = None,
    date_from=None,
    date_to=None,
    search: str | None = None,
):
    """Return filtered audit rows (imported lazily to avoid app coupling)."""
    from core.audit import AuditLog

    qs = AuditLog.objects.select_related("user").order_by("-created_at")
    if user_id:
        qs = qs.filter(user_id=user_id)
    if action:
        qs = qs.filter(action=action)
    if model_name:
        qs = qs.filter(model_name__icontains=model_name)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    if search:
        qs = qs.filter(
            Q(object_repr__icontains=search)
            | Q(path__icontains=search)
            | Q(user__username__icontains=search)
        )
    return qs


def permission_catalog() -> dict[str, list[Permission]]:
    """Return all permissions grouped by app label, ordered for the UI."""
    perms = Permission.objects.select_related("content_type").order_by(
        "content_type__app_label", "codename"
    )
    grouped: dict[str, list[Permission]] = {}
    for perm in perms:
        grouped.setdefault(perm.content_type.app_label, []).append(perm)
    return grouped
