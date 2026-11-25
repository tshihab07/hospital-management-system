"""Audit trail for IHMS.

Every CREATE / UPDATE / DELETE of a business record must be recorded
(RULES §4.4.1). Domain services call :func:`log_action`; the model is
deliberately append-only (no update/delete helpers).
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models

from .threadlocals import get_client_ip, get_current_request, get_current_user


class AuditAction(models.TextChoices):
    """Recognised audit actions."""

    CREATE = "create", "Create"
    UPDATE = "update", "Update"
    DELETE = "delete", "Delete"
    LOGIN = "login", "Login"
    LOGOUT = "logout", "Logout"
    LOGIN_FAILED = "login_failed", "Login failed"
    ACCESS = "access", "Access"
    DENIED = "denied", "Permission denied"
    EXPORT = "export", "Export"
    APPROVE = "approve", "Approve"
    DISPENSE = "dispense", "Dispense"
    PAYMENT = "payment", "Payment"


class AuditLog(models.Model):
    """Immutable record of a single auditable action."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=32, choices=AuditAction.choices, db_index=True)
    model_name = models.CharField(max_length=100, blank=True, db_index=True)
    object_id = models.CharField(max_length=64, blank=True)
    object_repr = models.CharField(max_length=255, blank=True)
    changes = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    path = models.CharField(max_length=255, blank=True)
    method = models.CharField(max_length=10, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Audit log"
        verbose_name_plural = "Audit logs"
        indexes = [
            models.Index(fields=["model_name", "object_id"]),
            models.Index(fields=["user", "-created_at"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.get_action_display()} {self.model_name}#{self.object_id}"

    @property
    def changes_json(self) -> str:
        """Pretty-printed JSON of the change payload for display."""
        import json

        return json.dumps(self.changes, indent=2, ensure_ascii=False, default=str)


def log_action(
    action: str,
    *,
    instance: models.Model | None = None,
    model_name: str | None = None,
    object_id: str | int | None = None,
    object_repr: str | None = None,
    changes: dict[str, Any] | None = None,
    user: Any | None = None,
    request: Any | None = None,
) -> AuditLog:
    """Create an :class:`AuditLog` entry.

    Args:
        action: One of :class:`AuditAction` values.
        instance: Optional model instance being acted upon.
        model_name: Explicit model name when no instance is provided.
        object_id: Explicit object id when no instance is provided.
        object_repr: Human readable representation of the object.
        changes: Structured diff / payload describing the change.
        user: Acting user; falls back to the thread-local request user.
        request: Optional request for IP/user-agent/path capture.

    Returns:
        The persisted :class:`AuditLog` instance.
    """
    request = request or get_current_request()
    user = user or get_current_user()

    if instance is not None:
        model_name = model_name or instance._meta.label
        object_id = object_id if object_id is not None else instance.pk
        object_repr = object_repr or str(instance)[:255]

    return AuditLog.objects.create(
        user=user if getattr(user, "pk", None) else None,
        action=action,
        model_name=model_name or "",
        object_id=str(object_id) if object_id is not None else "",
        object_repr=object_repr or "",
        changes=changes,
        ip_address=get_client_ip(request),
        user_agent=(getattr(request, "META", {}).get("HTTP_USER_AGENT", "") or "")[
            :512
        ],
        path=(getattr(request, "path", "") or "")[:255],
        method=(getattr(request, "method", "") or "")[:10],
    )


def model_to_dict_safe(instance: models.Model) -> dict[str, Any]:
    """Return a JSON-safe dict of concrete field values for audit diffs."""
    from decimal import Decimal
    from uuid import UUID

    data: dict[str, Any] = {}
    for field in instance._meta.concrete_fields:
        value = getattr(instance, field.attname, None)
        if isinstance(value, Decimal):
            value = str(value)
        elif isinstance(value, UUID):
            value = str(value)
        elif hasattr(value, "isoformat"):
            value = value.isoformat()
        else:
            try:
                import json

                json.dumps(value)
            except TypeError:
                value = str(value)
        data[field.name] = value
    return data
