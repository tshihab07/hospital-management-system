"""URLs for identity and access management."""

from django.urls import path

from .views import (
    AuditLogDetailView,
    AuditLogListView,
    IHMSLoginView,
    IHMSLogoutView,
    IHMSPasswordChangeView,
    IHMSPasswordResetCompleteView,
    IHMSPasswordResetConfirmView,
    IHMSPasswordResetDoneView,
    IHMSPasswordResetView,
    ProfileView,
    RoleCreateView,
    RoleDeleteView,
    RoleDetailView,
    RoleListView,
    RoleUpdateView,
    UserCreateView,
    UserDetailView,
    UserListView,
    UserSetActiveView,
    UserSetPasswordView,
    UserUpdateView,
)

app_name = "accounts"

urlpatterns = [
    # Authentication
    path("login/", IHMSLoginView.as_view(), name="login"),
    path("logout/", IHMSLogoutView.as_view(), name="logout"),
    path("profile/", ProfileView.as_view(), name="profile"),
    path("password-change/", IHMSPasswordChangeView.as_view(), name="password_change"),
    path("password-reset/", IHMSPasswordResetView.as_view(), name="password_reset"),
    path(
        "password-reset/done/",
        IHMSPasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "password-reset/<uidb64>/<token>/",
        IHMSPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "password-reset/complete/",
        IHMSPasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
    # User administration
    path("users/", UserListView.as_view(), name="user_list"),
    path("users/add/", UserCreateView.as_view(), name="user_create"),
    path("users/<int:pk>/", UserDetailView.as_view(), name="user_detail"),
    path("users/<int:pk>/edit/", UserUpdateView.as_view(), name="user_update"),
    path(
        "users/<int:pk>/toggle/",
        UserSetActiveView.as_view(),
        name="user_toggle_active",
    ),
    path(
        "users/<int:pk>/set-password/",
        UserSetPasswordView.as_view(),
        name="user_set_password",
    ),
    # Role & permission administration
    path("roles/", RoleListView.as_view(), name="role_list"),
    path("roles/add/", RoleCreateView.as_view(), name="role_create"),
    path("roles/<int:pk>/", RoleDetailView.as_view(), name="role_detail"),
    path("roles/<int:pk>/edit/", RoleUpdateView.as_view(), name="role_update"),
    path("roles/<int:pk>/delete/", RoleDeleteView.as_view(), name="role_delete"),
    # Audit trail
    path("audit/", AuditLogListView.as_view(), name="audit_log"),
    path("audit/<int:pk>/", AuditLogDetailView.as_view(), name="audit_detail"),
]
