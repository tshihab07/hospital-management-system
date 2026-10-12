"""Identity models for IHMS.

The custom ``User`` model is defined here from the very start so that
``AUTH_USER_MODEL`` never has to be swapped after the first migration.
"""

from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser, Permission, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import TimeStampedModel

from .managers import UserManager


class Role(TimeStampedModel):
    """A named bundle of permissions (RULES Phase 1).

    Roles map to the ``ROLE`` / ``ROLE_PERMISSION`` tables in ARCHITECTURE;
    permissions reuse Django's ``auth.Permission`` catalogue so codenames
    follow the ``<app_label>.<action>_<model>`` convention (SKILLS-04).
    """

    name = models.CharField(_("name"), max_length=100, unique=True)
    description = models.TextField(_("description"), blank=True)
    is_system = models.BooleanField(
        _("system role"),
        default=False,
        help_text=_("System roles are protected from deletion."),
    )
    permissions = models.ManyToManyField(
        Permission,
        blank=True,
        related_name="roles",
        verbose_name=_("permissions"),
    )

    class Meta:
        verbose_name = _("role")
        verbose_name_plural = _("roles")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def permission_count(self) -> int:
        return self.permissions.count()


class User(AbstractBaseUser, PermissionsMixin):
    """Staff / portal user account.

    ``username`` is the primary login identifier. ``is_superuser`` grants full
    access (used by the seeded Super Admin). Role based access is layered on
    top via :class:`~apps.accounts.models.Role` (added in Phase 1).
    """

    username = models.CharField(
        _("username"), max_length=150, unique=True, db_index=True
    )
    email = models.EmailField(_("email address"), blank=True)
    phone = models.CharField(_("phone"), max_length=20, blank=True)
    full_name_en = models.CharField(
        _("full name (English)"), max_length=150, blank=True
    )
    full_name_bn = models.CharField(
        _("full name (Bengali)"), max_length=150, blank=True
    )
    designation = models.CharField(_("designation"), max_length=100, blank=True)

    profile_photo = models.ImageField(
        _("profile photo"), upload_to="users/photos/", null=True, blank=True
    )

    is_active = models.BooleanField(_("active"), default=True)
    is_staff = models.BooleanField(
        _("staff status"),
        default=False,
        help_text=_("Designates whether the user can log into the admin panel."),
    )
    must_change_password = models.BooleanField(default=False)
    mfa_enabled = models.BooleanField(_("MFA enabled"), default=False)

    roles = models.ManyToManyField(
        Role,
        blank=True,
        related_name="users",
        verbose_name=_("roles"),
    )

    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    date_joined = models.DateTimeField(_("date joined"), default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["email"]

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        ordering = ["username"]

    def __str__(self) -> str:
        return self.get_full_name() or self.username

    def get_full_name(self) -> str:
        """Return the English full name, falling back to the username."""
        return self.full_name_en.strip() or self.username

    def get_short_name(self) -> str:
        """Return the first token of the English full name."""
        return (
            self.full_name_en.strip().split(" ")[0]
            if self.full_name_en
            else self.username
        )

    @property
    def display_name(self) -> str:
        """Preferred display name for UI shells."""
        return self.get_full_name()

    @property
    def initials(self) -> str:
        """Two-letter initials for avatars."""
        parts = (self.get_full_name() or self.username).split()
        if len(parts) >= 2:
            return f"{parts[0][0]}{parts[1][0]}".upper()
        return (parts[0][:2] if parts else "?").upper()

    @property
    def role_names(self) -> list[str]:
        """Return the names of the roles assigned to this user."""
        return list(self.roles.values_list("name", flat=True))

    @property
    def primary_role(self) -> Role | None:
        """Return the first assigned role, if any (used for display)."""
        return self.roles.order_by("name").first()

    def has_role(self, *names: str) -> bool:
        """Return ``True`` when the user holds any of the given role names."""
        if self.is_superuser:
            return True
        return self.roles.filter(name__in=names).exists()
