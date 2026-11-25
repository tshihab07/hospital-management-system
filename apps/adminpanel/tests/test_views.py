"""Tests for the control-tower dashboard (RULES Phase 1 shell, Phase 16 KPIs)."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.urls import reverse

import pytest

pytestmark = pytest.mark.django_db

User = get_user_model()


def test_dashboard_requires_login(client):
    resp = client.get(reverse("panel:home"))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.url


def test_dashboard_renders_real_kpis(client):
    user = User.objects.create_user(username="dash", password="x", is_staff=True)
    client.force_login(user)
    resp = client.get(reverse("panel:home"))
    assert resp.status_code == 200
    assert b"Bed Occupancy" in resp.content
    assert b"Today&#x27;s Collection" in resp.content or b"Today's Collection" in resp.content


def test_dashboard_denies_non_staff(client):
    user = User.objects.create_user(username="patient", password="x")
    client.force_login(user)
    resp = client.get(reverse("panel:home"))
    assert resp.status_code == 403
