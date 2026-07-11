"""Unit tests for the common FOCUS-aligned schema."""

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from ingestion.focus_schema import (
    FOCUS_COLUMNS,
    AllocationStatus,
    ChargeCategory,
    FocusRow,
    PricingCategory,
    ProviderName,
    ServiceCategory,
)


def make_valid_focus_row(**overrides) -> FocusRow:
    values = {
        "record_id": "aws-000001",
        "provider_name": ProviderName.AWS,
        "billing_account_id": "999999999999",
        "sub_account_id": "111111111111",
        "sub_account_name": "production-account",
        "charge_period_start": datetime(
            2026, 4, 1, 0, 0, tzinfo=timezone.utc
        ),
        "charge_period_end": datetime(
            2026, 4, 2, 0, 0, tzinfo=timezone.utc
        ),
        "billing_period_start": datetime(
            2026, 4, 1, 0, 0, tzinfo=timezone.utc
        ),
        "billing_period_end": datetime(
            2026, 5, 1, 0, 0, tzinfo=timezone.utc
        ),
        "service_name": "Amazon Elastic Compute Cloud",
        "service_category": ServiceCategory.COMPUTE,
        "sku_description": "Linux instance usage",
        "resource_id": "i-0123456789abcdef0",
        "region": "us-east-1",
        "availability_zone": "us-east-1a",
        "consumed_quantity": Decimal("24"),
        "consumed_unit": "Hours",
        "list_unit_price": Decimal("0.10"),
        "pricing_category": PricingCategory.STANDARD,
        "billing_currency": "usd",
        "list_cost": Decimal("2.40"),
        "billed_cost": Decimal("2.10"),
        "effective_cost": Decimal("2.10"),
        "charge_category": ChargeCategory.USAGE,
        "charge_class": None,
        "charge_description": "EC2 instance usage",
        "tags": {
            "Environment": "prod",
            "CostCenter": "CC100",
            "Owner": "Data",
        },
        "application": "storefront",
        "environment": "prod",
        "cost_center": "CC100",
        "owner": "Data",
        "allocation_status": AllocationStatus.ALLOCATED,
        "source_file": "aws_billing_sample.csv",
        "source_row_number": 2,
    }
    values.update(overrides)
    return FocusRow(**values)


def test_valid_focus_row_can_be_created_and_exported():
    row = make_valid_focus_row()
    exported = row.to_dict()

    assert exported["provider_name"] == "AWS"
    assert exported["service_category"] == "Compute"
    assert exported["charge_category"] == "Usage"
    assert exported["pricing_category"] == "Standard"
    assert exported["application"] == "storefront"
    assert exported["billing_currency"] == "USD"
    assert exported["billed_cost"] == "2.10"
    assert exported["source_row_number"] == 2

    parsed_tags = json.loads(exported["tags"])
    assert parsed_tags["Environment"] == "prod"
    assert parsed_tags["CostCenter"] == "CC100"
    assert parsed_tags["Owner"] == "Data"


def test_exported_columns_match_schema_definition():
    exported = make_valid_focus_row().to_dict()
    assert tuple(exported.keys()) == FOCUS_COLUMNS
    assert len(FOCUS_COLUMNS) == 34


def test_charge_period_end_must_be_after_start():
    with pytest.raises(ValueError, match="charge_period_end must be later"):
        make_valid_focus_row(
            charge_period_start=datetime(2026, 4, 2, tzinfo=timezone.utc),
            charge_period_end=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )


def test_billing_period_end_must_be_after_start():
    with pytest.raises(ValueError, match="billing_period_end must be later"):
        make_valid_focus_row(
            billing_period_start=datetime(2026, 5, 1, tzinfo=timezone.utc),
            billing_period_end=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )


@pytest.mark.parametrize("currency", ["US", "US1"])
def test_currency_must_be_three_letters(currency):
    with pytest.raises(ValueError, match="three-letter currency code"):
        make_valid_focus_row(billing_currency=currency)


def test_currency_must_not_be_blank():
    with pytest.raises(ValueError, match="billing_currency must not be blank"):
        make_valid_focus_row(billing_currency="")


@pytest.mark.parametrize(
    ("quantity", "unit"),
    [
        (Decimal("10"), None),
        (None, "Hours"),
    ],
)
def test_quantity_and_unit_must_exist_together(quantity, unit):
    with pytest.raises(
        ValueError,
        match="consumed_quantity and consumed_unit",
    ):
        make_valid_focus_row(
            consumed_quantity=quantity,
            consumed_unit=unit,
        )


def test_sub_account_name_requires_sub_account_id():
    with pytest.raises(ValueError, match="sub_account_name cannot exist"):
        make_valid_focus_row(
            sub_account_id=None,
            sub_account_name="production-account",
        )


def test_negative_list_unit_price_is_rejected():
    with pytest.raises(ValueError, match="list_unit_price cannot be negative"):
        make_valid_focus_row(list_unit_price=Decimal("-0.10"))


def test_normal_usage_requires_pricing_category():
    with pytest.raises(ValueError, match="pricing_category is required"):
        make_valid_focus_row(pricing_category=None)


def test_source_row_number_must_be_positive():
    with pytest.raises(ValueError, match="source_row_number must be at least 1"):
        make_valid_focus_row(source_row_number=0)


def test_tags_must_be_a_mapping():
    with pytest.raises(TypeError, match="tags must be a mapping"):
        make_valid_focus_row(tags=["Environment", "prod"])