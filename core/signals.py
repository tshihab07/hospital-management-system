"""Signal handlers for audit logging (RULES §2.2: signals for audit only)."""

from __future__ import annotations

from django.contrib.auth.signals import (user_logged_in, user_logged_out,
                                         user_login_failed)
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .audit import AuditAction, log_action


@receiver(user_logged_in, dispatch_uid="ihms_audit_login")
def on_user_logged_in(sender, request, user, **kwargs) -> None:
    """Record successful logins."""
    log_action(AuditAction.LOGIN, instance=user, user=user, request=request)


@receiver(user_logged_out, dispatch_uid="ihms_audit_logout")
def on_user_logged_out(sender, request, user, **kwargs) -> None:
    """Record logouts."""
    if user is not None:
        log_action(AuditAction.LOGOUT, instance=user, user=user, request=request)


@receiver(user_login_failed, dispatch_uid="ihms_audit_login_failed")
def on_user_login_failed(sender, credentials, request=None, **kwargs) -> None:
    """Record failed authentication attempts."""
    username = (credentials or {}).get("username", "")
    log_action(
        AuditAction.LOGIN_FAILED,
        model_name="accounts.User",
        object_repr=str(username)[:255],
        request=request,
    )


def register_audit_signals(model, *, fields: list[str] | None = None) -> None:
    """Attach generic create/update/delete audit signals to ``model``.

    Used for models whose mutations are not routed through a dedicated service.
    Models with rich business flows should log explicitly from their services.

    Args:
        model: The concrete model class to audit.
        fields: Optional whitelist of fields to include in the audit diff.
    """

    def _on_save(sender, instance, created, **kwargs):
        changes = None
        if fields:
            changes = {f: str(getattr(instance, f, "")) for f in fields}
        log_action(
            AuditAction.CREATE if created else AuditAction.UPDATE,
            instance=instance,
            changes=changes,
        )

    def _on_delete(sender, instance, **kwargs):
        log_action(AuditAction.DELETE, instance=instance)

    post_save.connect(
        _on_save,
        sender=model,
        dispatch_uid=f"ihms_audit_save_{model._meta.label_lower}",
    )
    post_delete.connect(
        _on_delete,
        sender=model,
        dispatch_uid=f"ihms_audit_del_{model._meta.label_lower}",
    )
