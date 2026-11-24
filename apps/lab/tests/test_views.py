"""View / access-control tests for the Laboratory & Radiology module."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from apps.lab import services
from apps.lab.models import LabReport, RadiologyRecord, SampleStatus

from .factories import (make_lab_order, make_lab_test, make_radiology_order,
                        make_user)

pytestmark = pytest.mark.django_db

_ALL = [
    "emr.view_laborder",
    "emr.view_radiologyorder",
    "lab.view_labsample",
    "lab.add_labsample",
    "lab.change_labsample",
    "lab.view_labresult",
    "lab.add_labresult",
    "lab.verify_labresult",
    "lab.add_labresultaddendum",
    "lab.view_labreport",
    "lab.verify_labreport",
    "lab.release_labreport",
    "lab.view_radiologyrecord",
    "lab.change_radiologyrecord",
    "lab.verify_radiologyrecord",
]


def _client(*specs, username="lab-view-user") -> Client:
    client = Client()
    client.force_login(make_user(*specs, username=username))
    return client


def test_anonymous_redirects_to_login():
    response = Client().get(reverse("lab:order_list"))
    assert response.status_code == 302
    assert "login" in response.url


def test_missing_permission_is_denied():
    response = _client("lab.view_labsample", username="none").get(
        reverse("lab:order_list")
    )
    assert response.status_code == 403


def test_order_list_and_sublists_render():
    make_lab_order()
    client = _client(*_ALL, username="lists")
    assert client.get(reverse("lab:order_list")).status_code == 200
    assert client.get(reverse("lab:sample_list")).status_code == 200
    assert client.get(reverse("lab:result_list")).status_code == 200
    assert client.get(reverse("lab:radiology_list")).status_code == 200


def test_order_detail_renders():
    order = make_lab_order()
    response = _client(*_ALL, username="detail").get(
        reverse("lab:order_detail", args=[order.pk])
    )
    assert response.status_code == 200


def test_sample_create_and_collect_via_view():
    order = make_lab_order()
    client = _client(*_ALL, username="samp")
    response = client.post(reverse("lab:sample_create", args=[order.pk]))
    assert response.status_code == 302
    sample = order.sample
    client.post(reverse("lab:sample_action", args=[sample.pk, "collect"]))
    sample.refresh_from_db()
    assert sample.status == SampleStatus.COLLECTED


def test_result_entry_and_verify_via_view():
    order = make_lab_order(tests=[make_lab_test(reference_range="4.0 - 10.0")])
    item = order.items.first()
    client = _client(*_ALL, username="res")
    client.post(
        reverse("lab:result_entry", args=[order.pk]),
        {"item_id": item.pk, "value": "15", "flag": "", "remarks": ""},
    )
    result = order.results.get()
    assert result.flag != "normal"
    client.post(reverse("lab:result_verify", args=[result.pk]))
    result.refresh_from_db()
    assert result.is_verified
    assert LabReport.objects.filter(order=order).exists()


def test_report_detail_and_pdf():
    order = make_lab_order()
    services.ensure_sample(order=order)
    services.collect_sample(sample=order.sample)
    services.enter_result(order_item=order.items.first(), value="7")
    services.verify_result(result=order.results.first())
    client = _client(*_ALL, username="rep")
    assert client.get(reverse("lab:report_detail", args=[order.pk])).status_code == 200
    pdf = client.get(reverse("lab:report_pdf", args=[order.pk]))
    assert pdf.status_code == 200
    assert pdf["Content-Type"] == "application/pdf"


def test_report_release_via_view():
    order = make_lab_order()
    services.enter_result(order_item=order.items.first(), value="7")
    services.verify_result(result=order.results.first())
    _client(*_ALL, username="rel").post(
        reverse("lab:report_action", args=[order.pk, "release"])
    )
    report = LabReport.objects.get(order=order)
    assert report.is_released


def test_radiology_report_and_verify_via_view():
    order = make_radiology_order()
    client = _client(*_ALL, username="rad")
    client.post(
        reverse("lab:radiology_action", args=[order.pk, "report"]),
        {"findings": "Normal", "impression": "Clear", "radiologist": ""},
    )
    record = RadiologyRecord.objects.get(order=order)
    assert record.status == "reported"
    client.post(reverse("lab:radiology_action", args=[order.pk, "verify"]))
    record.refresh_from_db()
    assert record.verified_at is not None
