"""Unit tests for the dependency-free tax engine (RULES Phase 14)."""

from __future__ import annotations

from decimal import Decimal

from apps.payroll import tax

GENERAL = [(band, rate) for band, rate, _label in tax.BD_SLABS["general"]]


def test_income_below_threshold_is_tax_free():
    assert tax.compute_tax(
        Decimal("300000"), GENERAL, tax_free_threshold=Decimal("350000")
    ) == Decimal("0.00")


def test_income_exactly_at_threshold_has_no_minimum_tax():
    result = tax.compute_tax(
        Decimal("350000"),
        GENERAL,
        tax_free_threshold=Decimal("350000"),
        minimum_tax=Decimal("5000"),
    )
    assert result == Decimal("0.00")


def test_minimum_tax_applies_just_above_threshold():
    result = tax.compute_tax(
        Decimal("351000"),
        GENERAL,
        tax_free_threshold=Decimal("350000"),
        minimum_tax=Decimal("5000"),
    )
    assert result == Decimal("5000.00")


def test_general_slab_progressive_calculation():
    # 350k free, next 100k @5% = 5,000, next 400k @10% = 40,000.
    # taxable 850,000 -> 45,000.
    result = tax.compute_tax(
        Decimal("850000"), GENERAL, tax_free_threshold=Decimal("350000")
    )
    assert result == Decimal("45000.00")


def test_top_band_is_open_ended():
    # 350k free +100k@5 +400k@10 +500k@15 +500k@20 +2,000,000@25 = 720,000;
    # remaining 150,000 @30% = 45,000 -> total 765,000.
    taxable = Decimal("4000000")
    result = tax.compute_tax(taxable, GENERAL, tax_free_threshold=Decimal("350000"))
    assert result == Decimal("765000.00")


def test_zero_or_negative_income_is_zero():
    assert tax.compute_tax(Decimal("0"), GENERAL) == Decimal("0.00")
    assert tax.compute_tax(Decimal("-5000"), GENERAL) == Decimal("0.00")


def test_standard_deduction_is_capped():
    assert tax.standard_deduction(Decimal("1000000")) == Decimal("300000.00")
    assert tax.standard_deduction(Decimal("480000")) == Decimal("159984.00")


def test_taxable_income_subtracts_pf_and_standard_deduction():
    result = tax.taxable_income(
        Decimal("900000"),
        annual_pf=Decimal("36000"),
        standard_deduction=Decimal("300000"),
    )
    assert result == Decimal("564000.00")


def test_taxable_income_never_negative():
    result = tax.taxable_income(
        Decimal("100000"),
        annual_pf=Decimal("200000"),
        standard_deduction=Decimal("300000"),
    )
    assert result == Decimal("0.00")


def test_monthly_tax_divides_annual_tax():
    assert tax.monthly_tax(Decimal("60000"), 12) == Decimal("5000.00")
    assert tax.monthly_tax(Decimal("60000"), 0) == Decimal("60000.00")
