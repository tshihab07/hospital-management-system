"""Profile views for the logged-in user."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import UpdateView

from core.audit import AuditAction, log_action

from ..forms import ProfileForm
from ..models import User


class ProfileView(LoginRequiredMixin, UpdateView):
    """Allow a user to review and update their own profile."""

    model = User
    form_class = ProfileForm
    template_name = "accounts/profile.html"
    success_url = reverse_lazy("accounts:profile")

    def get_object(self, queryset=None) -> User:
        return self.request.user

    def form_valid(self, form):
        response = super().form_valid(form)
        log_action(
            AuditAction.UPDATE, instance=self.object, changes={"self_profile": True}
        )
        messages.success(self.request, "Your profile has been updated.")
        return response
