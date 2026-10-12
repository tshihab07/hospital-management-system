"""Accounts signal handlers."""

from __future__ import annotations

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from core.threadlocals import get_client_ip


@receiver(user_logged_in, dispatch_uid="accounts_store_login_ip")
def store_login_ip(sender, request, user, **kwargs) -> None:
    """Persist the client IP of the most recent successful login."""
    ip = get_client_ip(request)
    if ip:
        type(user).objects.filter(pk=user.pk).update(last_login_ip=ip)
