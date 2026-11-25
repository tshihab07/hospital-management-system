"""Reusable view mixins enforcing authentication, RBAC and audit.

Every view in IHMS MUST be protected by authentication and a permission check
(RULES §4.2.1). These mixins centralise that behaviour and record permission
denials and PII access to the audit trail.
"""

from __future__ import annotations

from django.contrib.auth.mixins import (LoginRequiredMixin,
                                        PermissionRequiredMixin)
from django.core.exceptions import PermissionDenied

from .audit import AuditAction, log_action


class IHMSLoginRequiredMixin(LoginRequiredMixin):
    """Require an authenticated user; audit anonymous denials."""

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            log_action(
                AuditAction.DENIED, model_name="View", object_repr=self.request.path
            )
        return super().handle_no_permission()


class IHMSPermissionRequiredMixin(PermissionRequiredMixin):
    """Require specific permissions; audit every denial."""

    permission_denied_message = "You do not have permission to perform this action."

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            log_action(
                AuditAction.DENIED,
                model_name=self.__class__.__name__,
                object_repr=self.request.path,
                changes={"required": list(self.get_permission_required())},
            )
            raise PermissionDenied(self.get_permission_denied_message())
        return super().handle_no_permission()


class StaffRequiredMixin(LoginRequiredMixin):
    """Require an authenticated *staff* user (never a portal patient account)."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not (
            request.user.is_staff or request.user.is_superuser
        ):
            log_action(
                AuditAction.DENIED,
                model_name=self.__class__.__name__,
                object_repr=request.path,
                changes={"reason": "not_staff"},
            )
            raise PermissionDenied("Staff access required.")
        return super().dispatch(request, *args, **kwargs)


class PIIAccessMixin:
    """Log access to a page that displays patient-identifiable information.

    Add to detail/report views; call :meth:`log_pii_access` from
    ``get_object`` or ``get`` once the target object is known.
    """

    pii_model_name: str = ""

    def log_pii_access(self, instance=None, *, object_repr: str = "") -> None:
        """Write an ``ACCESS`` audit row for this page view."""
        log_action(
            AuditAction.ACCESS,
            instance=instance,
            model_name=self.pii_model_name or None,
            object_repr=object_repr,
        )
