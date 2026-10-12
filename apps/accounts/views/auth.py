"""Authentication views for IHMS."""

from __future__ import annotations

from django.contrib.auth.views import LoginView, LogoutView

from ..forms import LoginForm


class IHMSLoginView(LoginView):
    """Styled login view supporting 'remember me' session control."""

    template_name = "registration/login.html"
    form_class = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        if not form.cleaned_data.get("remember_me"):
            self.request.session.set_expiry(0)
        return response


class IHMSLogoutView(LogoutView):
    """POST-only logout (Django 5 requirement)."""

    next_page = "accounts:login"
