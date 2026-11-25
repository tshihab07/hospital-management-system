"""Create (or update) the IHMS Super Admin from environment variables.

Usage::

    python manage.py seed_superadmin
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Seed the Super Admin account used to access the /admin control panel."""

    help = "Create or update the super admin account from .env (ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_EMAIL)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--username",
            default=None,
            help="Override ADMIN_USERNAME from settings.",
        )
        parser.add_argument(
            "--password",
            default=None,
            help="Override ADMIN_PASSWORD from settings.",
        )
        parser.add_argument(
            "--email",
            default=None,
            help="Override ADMIN_EMAIL from settings.",
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        User = get_user_model()

        username = options["username"] or settings.SUPER_ADMIN_USERNAME
        password = options["password"] or settings.SUPER_ADMIN_PASSWORD
        email = options["email"] or settings.SUPER_ADMIN_EMAIL

        if not username or not password:
            self.stderr.write(self.style.ERROR("Username and password are required."))
            return

        user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": email or ""},
        )

        user.email = email or user.email
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.set_password(password)
        user.save()

        self._assign_super_admin_role(user)

        verb = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} super admin '{username}' ({email or 'no email'})."
            )
        )
        logger.info("%s super admin '%s'.", verb, username)

    @staticmethod
    def _assign_super_admin_role(user) -> None:
        """Attach the Super Admin role when it has been seeded."""
        from apps.accounts.models import Role

        role = Role.objects.filter(name="Super Admin").first()
        if role is not None:
            user.roles.add(role)
