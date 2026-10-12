"""Accounts views."""

from .audit import AuditLogDetailView, AuditLogListView
from .auth import IHMSLoginView, IHMSLogoutView
from .password import (
    IHMSPasswordChangeView,
    IHMSPasswordResetCompleteView,
    IHMSPasswordResetConfirmView,
    IHMSPasswordResetDoneView,
    IHMSPasswordResetView,
)
from .profile import ProfileView
from .roles import (
    RoleCreateView,
    RoleDeleteView,
    RoleDetailView,
    RoleListView,
    RoleUpdateView,
)
from .users import (
    UserCreateView,
    UserDetailView,
    UserListView,
    UserSetActiveView,
    UserSetPasswordView,
    UserUpdateView,
)

__all__ = [
    # auth
    "IHMSLoginView",
    "IHMSLogoutView",
    "ProfileView",
    "IHMSPasswordChangeView",
    "IHMSPasswordResetView",
    "IHMSPasswordResetDoneView",
    "IHMSPasswordResetConfirmView",
    "IHMSPasswordResetCompleteView",
    # users
    "UserListView",
    "UserCreateView",
    "UserUpdateView",
    "UserDetailView",
    "UserSetActiveView",
    "UserSetPasswordView",
    # roles
    "RoleListView",
    "RoleCreateView",
    "RoleUpdateView",
    "RoleDetailView",
    "RoleDeleteView",
    # audit
    "AuditLogListView",
    "AuditLogDetailView",
]
