"""Write operations for identity & access management.

Every mutation lives here, runs inside a transaction and writes an audit row
(RULES §2.2, §4.4.1). Views/forms never touch the ORM for writes directly.
"""

from __future__ import annotations

from typing import Iterable

from django.contrib.auth.models import Permission
from django.db import transaction

from core.audit import AuditAction, log_action, model_to_dict_safe

from .models import Role, User

_VOLATILE = {"updated_at", "last_login", "last_login_ip", "password"}


def _diff(before: dict, after: dict) -> dict:
    """Return the changed keys between two audit snapshots."""
    changed = {}
    for key, value in after.items():
        if key in _VOLATILE:
            continue
        if before.get(key) != value:
            changed[key] = {"from": before.get(key), "to": value}
    return changed


@transaction.atomic
def create_user(
    *,
    data: dict,
    roles: Iterable[Role] | None = None,
    actor: User | None = None,
    request=None,
) -> User:
    """Create a user from validated ``data`` and assign roles."""
    data = dict(data)
    password = data.pop("password1", None) or data.pop("password", None)
    data.pop("password2", None)
    roles = roles if roles is not None else data.pop("roles", None)
    user = User(**data)
    if password:
        user.set_password(password)
    user.save()

    if roles:
        user.roles.set(roles)

    log_action(
        AuditAction.CREATE,
        instance=user,
        changes={"username": user.username, "roles": user.role_names},
        user=actor,
        request=request,
    )
    return user


@transaction.atomic
def update_user(
    *,
    user: User,
    data: dict,
    roles: Iterable[Role] | None = None,
    actor: User | None = None,
    request=None,
) -> User:
    """Update a user's profile fields and role assignments."""
    before = model_to_dict_safe(user)
    data = dict(data)
    data.pop("password1", None)
    data.pop("password2", None)
    roles = roles if roles is not None else data.pop("roles", None)
    for field, value in data.items():
        setattr(user, field, value)
    user.save()

    if roles is not None:
        user.roles.set(roles)

    changes = _diff(before, model_to_dict_safe(user))
    if roles is not None:
        changes["roles"] = {"to": user.role_names}
    log_action(
        AuditAction.UPDATE, instance=user, changes=changes, user=actor, request=request
    )
    return user


@transaction.atomic
def set_user_password(
    *,
    user: User,
    raw_password: str,
    actor: User | None = None,
    request=None,
    must_change: bool = False,
) -> User:
    """Set a user's password (used by the admin set-password screen)."""
    user.set_password(raw_password)
    user.must_change_password = must_change
    user.save(update_fields=["password", "must_change_password", "updated_at"])
    log_action(
        AuditAction.UPDATE,
        instance=user,
        changes={"password": "changed"},
        user=actor,
        request=request,
    )
    return user


@transaction.atomic
def set_user_active(
    *,
    user: User,
    is_active: bool,
    actor: User | None = None,
    request=None,
) -> User:
    """Activate or deactivate a user account."""
    user.is_active = is_active
    user.save(update_fields=["is_active", "updated_at"])
    log_action(
        AuditAction.UPDATE,
        instance=user,
        changes={"is_active": {"to": is_active}},
        user=actor,
        request=request,
    )
    return user


@transaction.atomic
def create_role(
    *,
    data: dict,
    permissions: Iterable[Permission] | None = None,
    actor: User | None = None,
    request=None,
) -> Role:
    """Create a role and grant it the given permissions."""
    role = Role.objects.create(**data)
    if permissions:
        role.permissions.set(permissions)
    log_action(
        AuditAction.CREATE,
        instance=role,
        changes={"name": role.name, "permissions": role.permission_count},
        user=actor,
        request=request,
    )
    return role


@transaction.atomic
def update_role(
    *,
    role: Role,
    data: dict,
    permissions: Iterable[Permission] | None = None,
    actor: User | None = None,
    request=None,
) -> Role:
    """Update a role and its permission grants."""
    before = model_to_dict_safe(role)
    before_count = role.permission_count
    for field, value in data.items():
        setattr(role, field, value)
    role.save()
    if permissions is not None:
        role.permissions.set(permissions)
    changes = _diff(before, model_to_dict_safe(role))
    if permissions is not None:
        changes["permissions"] = {
            "from": before_count,
            "to": role.permission_count,
        }
    log_action(
        AuditAction.UPDATE, instance=role, changes=changes, user=actor, request=request
    )
    return role


@transaction.atomic
def delete_role(*, role: Role, actor: User | None = None, request=None) -> None:
    """Delete a non-system role. System roles are protected."""
    if role.is_system:
        raise ValueError("System roles cannot be deleted.")
    log_action(
        AuditAction.DELETE,
        instance=role,
        changes={"name": role.name},
        user=actor,
        request=request,
    )
    role.delete()
