"""Authentication and profile forms for IHMS accounts."""

from __future__ import annotations

from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    PasswordResetForm,
    SetPasswordForm,
)
from django.contrib.auth.models import Permission
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .models import Role, User

INPUT_CLASSES = (
    "h-10 w-full rounded-[10px] border border-slate-200 bg-page px-3 text-sm "
    "text-slate-700 focus:border-primary-500 focus:ring-2 focus:ring-primary-500/30 "
    "dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
)


class LoginForm(AuthenticationForm):
    """Username/password login with a 'remember me' option."""

    username = forms.CharField(
        label=_("Username"),
        widget=forms.TextInput(
            attrs={
                "autofocus": True,
                "autocomplete": "username",
                "class": INPUT_CLASSES,
            }
        ),
    )
    password = forms.CharField(
        label=_("Password"),
        strip=False,
        widget=forms.PasswordInput(
            attrs={"autocomplete": "current-password", "class": INPUT_CLASSES}
        ),
    )
    remember_me = forms.BooleanField(label=_("Remember me"), required=False)

    error_messages = {
        "invalid_login": _("Invalid username or password."),
        "inactive": _("This account is inactive."),
    }

    def confirm_login_allowed(self, user: User) -> None:
        """Reject inactive accounts with a clear message."""
        if not user.is_active:
            raise ValidationError(self.error_messages["inactive"], code="inactive")


class ProfileForm(forms.ModelForm):
    """Self-service profile edit (non-privileged fields only)."""

    class Meta:
        model = User
        fields = ["full_name_en", "full_name_bn", "email", "phone", "profile_photo"]
        widgets = {
            "full_name_en": forms.TextInput(attrs={"class": INPUT_CLASSES}),
            "full_name_bn": forms.TextInput(attrs={"class": INPUT_CLASSES}),
            "email": forms.EmailInput(attrs={"class": INPUT_CLASSES}),
            "phone": forms.TextInput(attrs={"class": INPUT_CLASSES}),
        }

    def clean_phone(self) -> str:
        """Normalise Bangladeshi phone numbers."""
        phone = (self.cleaned_data.get("phone") or "").strip()
        return phone


class IHMSPasswordResetForm(PasswordResetForm):
    """Password reset request form with IHMS styling."""

    email = forms.EmailField(
        label=_("Email"),
        max_length=254,
        widget=forms.EmailInput(
            attrs={"class": INPUT_CLASSES, "autocomplete": "email"}
        ),
    )


class IHMSSetPasswordForm(SetPasswordForm):
    """Set a new password (used after reset)."""

    new_password1 = forms.CharField(
        label=_("New password"),
        widget=forms.PasswordInput(
            attrs={"class": INPUT_CLASSES, "autocomplete": "new-password"}
        ),
    )
    new_password2 = forms.CharField(
        label=_("Confirm new password"),
        widget=forms.PasswordInput(
            attrs={"class": INPUT_CLASSES, "autocomplete": "new-password"}
        ),
    )


class IHMSPasswordChangeForm(PasswordChangeForm):
    """Change password while logged in."""

    old_password = forms.CharField(
        label=_("Current password"),
        widget=forms.PasswordInput(
            attrs={"class": INPUT_CLASSES, "autocomplete": "current-password"}
        ),
    )
    new_password1 = forms.CharField(
        label=_("New password"),
        widget=forms.PasswordInput(
            attrs={"class": INPUT_CLASSES, "autocomplete": "new-password"}
        ),
    )
    new_password2 = forms.CharField(
        label=_("Confirm new password"),
        widget=forms.PasswordInput(
            attrs={"class": INPUT_CLASSES, "autocomplete": "new-password"}
        ),
    )


# ---------------------------------------------------------------------------
# Administration: users
# ---------------------------------------------------------------------------
class UserCreateForm(forms.ModelForm):
    """Create a staff/portal user (admins only)."""

    password1 = forms.CharField(
        label=_("Password"),
        strip=False,
        widget=forms.PasswordInput(
            attrs={"class": INPUT_CLASSES, "autocomplete": "new-password"}
        ),
        help_text=_("At least 8 characters."),
    )
    password2 = forms.CharField(
        label=_("Confirm password"),
        strip=False,
        widget=forms.PasswordInput(
            attrs={"class": INPUT_CLASSES, "autocomplete": "new-password"}
        ),
    )

    class Meta:
        model = User
        fields = [
            "username",
            "email",
            "full_name_en",
            "full_name_bn",
            "phone",
            "designation",
            "is_staff",
            "is_active",
            "must_change_password",
            "roles",
        ]
        widgets = {
            "username": forms.TextInput(attrs={"class": INPUT_CLASSES}),
            "email": forms.EmailInput(attrs={"class": INPUT_CLASSES}),
            "full_name_en": forms.TextInput(attrs={"class": INPUT_CLASSES}),
            "full_name_bn": forms.TextInput(attrs={"class": INPUT_CLASSES}),
            "phone": forms.TextInput(attrs={"class": INPUT_CLASSES}),
            "designation": forms.TextInput(attrs={"class": INPUT_CLASSES}),
            "roles": forms.SelectMultiple(attrs={"class": INPUT_CLASSES, "size": 8}),
        }

    def clean_password2(self) -> str:
        p1 = self.cleaned_data.get("password1")
        p2 = self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise ValidationError(_("The two password fields did not match."))
        if p2:
            validate_password(p2)
        return p2


class UserUpdateForm(forms.ModelForm):
    """Edit an existing user (admins only); passwords handled separately."""

    class Meta:
        model = User
        fields = [
            "username",
            "email",
            "full_name_en",
            "full_name_bn",
            "phone",
            "designation",
            "is_staff",
            "is_active",
            "must_change_password",
            "roles",
        ]
        widgets = {
            "username": forms.TextInput(attrs={"class": INPUT_CLASSES}),
            "email": forms.EmailInput(attrs={"class": INPUT_CLASSES}),
            "full_name_en": forms.TextInput(attrs={"class": INPUT_CLASSES}),
            "full_name_bn": forms.TextInput(attrs={"class": INPUT_CLASSES}),
            "phone": forms.TextInput(attrs={"class": INPUT_CLASSES}),
            "designation": forms.TextInput(attrs={"class": INPUT_CLASSES}),
            "roles": forms.SelectMultiple(attrs={"class": INPUT_CLASSES, "size": 8}),
        }


class AdminSetPasswordForm(forms.Form):
    """Force-set a user's password from the admin panel."""

    password1 = forms.CharField(
        label=_("New password"),
        strip=False,
        widget=forms.PasswordInput(
            attrs={"class": INPUT_CLASSES, "autocomplete": "new-password"}
        ),
    )
    password2 = forms.CharField(
        label=_("Confirm new password"),
        strip=False,
        widget=forms.PasswordInput(
            attrs={"class": INPUT_CLASSES, "autocomplete": "new-password"}
        ),
    )
    must_change = forms.BooleanField(
        label=_("Require password change at next login"), required=False
    )

    def clean_password2(self) -> str:
        p1 = self.cleaned_data.get("password1")
        p2 = self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise ValidationError(_("The two password fields did not match."))
        if p2:
            validate_password(p2)
        return p2


# ---------------------------------------------------------------------------
# Administration: roles
# ---------------------------------------------------------------------------
class RoleForm(forms.ModelForm):
    """Create/edit a role and grant permissions."""

    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.select_related("content_type").order_by(
            "content_type__app_label", "codename"
        ),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label=_("Permissions"),
    )

    class Meta:
        model = Role
        fields = ["name", "description", "permissions"]
        widgets = {
            "name": forms.TextInput(attrs={"class": INPUT_CLASSES}),
            "description": forms.Textarea(attrs={"class": INPUT_CLASSES, "rows": 3}),
        }


# ---------------------------------------------------------------------------
# Filters (GET forms, no model save)
# ---------------------------------------------------------------------------
class UserFilterForm(forms.Form):
    """Search/filter controls for the user list."""

    q = forms.CharField(required=False, label=_("Search"))
    is_active = forms.ChoiceField(
        required=False,
        label=_("Status"),
        choices=[("", _("All")), ("1", _("Active")), ("0", _("Inactive"))],
    )
    role = forms.ModelChoiceField(
        required=False, queryset=Role.objects.order_by("name"), label=_("Role")
    )


class AuditFilterForm(forms.Form):
    """Search/filter controls for the audit log."""

    q = forms.CharField(required=False, label=_("Search"))
    action = forms.CharField(required=False, label=_("Action"))
    model_name = forms.CharField(required=False, label=_("Model"))
    date_from = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    date_to = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
