"""Test fixtures for the Reports & Analytics module."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _media_root(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    return tmp_path
