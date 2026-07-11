"""Tests for the synthetic AWS adapter."""

from decimal import Decimal

import pandas as pd

from ingestion.aws_synthetic_adapter import adapt_aws_dataframe
from ingestion.focus_schema import (
    AllocationStatus,
    ChargeCategory,
    PricingCategory,
    ProviderName,
    ServiceCategory,
)


def _aws_dataframe() -> pd.DataFrame:
    base = {
        "bill_billing_period_start_date": "2026-04-01",
        "bill_billing_period_end_date": "2026-05-01",
        "line_item_usage_start_date": "2026-04-01T00:00:00+00:00",
        "line_item_usage_end_date": "2026-04-02T00:00:00+00:00",
        "bill_payer_account_id": "999999999999",
        "line_item_usage_account_id": "111111111111",
        "account_name": "production-account",
        "product_region": "us-east-1",
        "line_item_usage_amount": 24,
        "pricing_unit": "Hours",
        "pricing_public_on_demand_rate": 0.10,
        "currency": "USD",
        "line_item_operation": "RunInstances",
        "team": "commerce",
        "application": "storefront",
        "environment": "production",
        "cost_center": "cc-1001",
        "resource_tags": '{"application":"storefront","team":"commerce"}',
    }

    return pd.DataFrame(
        [
            {
                **base,
                "source_record_id": "aws-usage-1",
                "product_product_name": "Amazon Elastic Compute Cloud - Compute",
                "line_item_usage_type": "BoxUsage",
                "line_item_resource_id": "i-123",
                "pricing_public_on_demand_cost": 2.40,
                "line_item_unblended_rate": 0.09,
                "line_item_unblended_cost": 2.10,
                "line_item_line_item_type": "Usage",
                "pricing_term": "OnDemand",
            },
            {
                **base,
                "source_record_id": "aws-credit-1",
                "product_product_name": "AWS Promotional Credits",
                "line_item_usage_type": "Credit",
                "line_item_resource_id": None,
                "line_item_usage_amount": None,
                "pricing_unit": None,
                "pricing_public_on_demand_rate": 0,
                "pricing_public_on_demand_cost": 0,
                "line_item_unblended_rate": 0,
                "line_item_unblended_cost": -5000,
                "line_item_line_item_type": "Credit",
                "pricing_term": "Adjustment",
            },
            {
                **base,
                "source_record_id": "aws-refund-1",
                "product_product_name": "Amazon Relational Database Service",
                "line_item_usage_type": "Refund",
                "line_item_resource_id": "db-123",
                "line_item_usage_amount": None,
                "pricing_unit": None,
                "pricing_public_on_demand_rate": 0,
                "pricing_public_on_demand_cost": 0,
                "line_item_unblended_rate": 0,
                "line_item_unblended_cost": -750,
                "line_item_line_item_type": "Refund",
                "pricing_term": "Adjustment",
            },
        ]
    )


def test_aws_adapter_maps_usage_credit_and_refund():
    rows = adapt_aws_dataframe(_aws_dataframe())

    usage, credit, refund = rows

    assert len(rows) == 3
    assert usage.provider_name is ProviderName.AWS
    assert usage.service_category is ServiceCategory.COMPUTE
    assert usage.charge_category is ChargeCategory.USAGE
    assert usage.pricing_category is PricingCategory.STANDARD
    assert usage.billed_cost == Decimal("2.1")
    assert usage.allocation_status is AllocationStatus.ALLOCATED
    assert usage.source_row_number == 2

    assert credit.charge_category is ChargeCategory.CREDIT
    assert credit.pricing_category is None
    assert credit.billed_cost == Decimal("-5000")
    assert credit.source_row_number == 3

    assert refund.charge_category is ChargeCategory.USAGE
    assert refund.pricing_category is PricingCategory.OTHER
    assert refund.billed_cost == Decimal("-750")
    assert refund.source_row_number == 4