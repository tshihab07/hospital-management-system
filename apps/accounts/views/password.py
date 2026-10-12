"""Password reset and change views for IHMS."""

from __future__ import annotations

from django.contrib.auth.views import (
    PasswordChangeView,
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.urls import reverse_lazy

from ..forms import IHMSPasswordChangeForm, IHMSPasswordResetForm, IHMSSetPasswordForm


class IHMSPasswordResetView(PasswordResetView):
    template_name = "registration/password_reset_form.html"
    form_class = IHMSPasswordResetForm
    email_template_name = "registration/password_reset_email.html"
    subject_template_name = "registration/password_reset_subject.txt"
    success_url = "/accounts/password-reset/done/"


class IHMSPasswordResetDoneView(PasswordResetDoneView):
    template_name = "registration/password_reset_done.html"


class IHMSPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = "registration/password_reset_confirm.html"
    form_class = IHMSSetPasswordForm
    success_url = "/accounts/password-reset/complete/"


class IHMSPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = "registration/password_reset_complete.html"


class IHMSPasswordChangeView(PasswordChangeView):
    """Change password for the logged-in user."""

    template_name = "registration/password_change_form.html"
    form_class = IHMSPasswordChangeForm
    success_url = reverse_lazy("accounts:profile")
