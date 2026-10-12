"""Authentication backend layering role permissions on top of Django's.

Django resolves permissions through authentication backends, so role based
grants (RULES Phase 1 / ARCHITECTURE ``ROLE_PERMISSION``) are added here
rather than by overriding ``User.has_perm``. The backend extends
:class:`~django.contrib.auth.backends.ModelBackend`, so username/password
authentication and direct/group permissions keep working unchanged.
"""

from __future__ import annotations

from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import Permission

from .models import User


class RolePermissionBackend(ModelBackend):
    """Grant permissions held by any of the user's :class:`Role` objects."""

    def _role_permissions(self, user_obj: User) -> set[str]:
        if not user_obj.is_active or user_obj.is_anonymous:
            return set()
        if not user_obj.pk:
            return set()
        pairs = Permission.objects.filter(roles__in=user_obj.roles.all()).values_list(
            "content_type__app_label", "codename"
        )
        return {f"{app_label}.{codename}" for app_label, codename in pairs}

    def get_all_permissions(self, user_obj, obj=None) -> set[str]:
        perms = super().get_all_permissions(user_obj, obj)
        return perms | self._role_permissions(user_obj)

    def has_perm(self, user_obj, perm: str, obj=None) -> bool:
        if super().has_perm(user_obj, perm, obj):
            return True
        return perm in self._role_permissions(user_obj)
