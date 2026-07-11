"""Tests for the synthetic GCP adapter."""

from decimal import Decimal

import pandas as pd

from ingestion.focus_schema import (
    ChargeCategory,
    PricingCategory,
    ProviderName,
    ServiceCategory,
)
from ingestion.gcp_synthetic_adapter import adapt_gcp_dataframe


def _gcp_dataframe() -> pd.DataFrame:
    base = {
        "billing_account_id": "000000-111111-222222",
        "invoice_month": 202604,
        "usage_start_time": "2026-04-01T00:00:00+00:00",
        "usage_end_time": "2026-04-02T00:00:00+00:00",
        "project_id": "finops-prod-1001",
        "project_name": "customer-platform-prod",
        "location": "us-central1",
        "currency": "USD",
        "currency_conversion_rate": 1.0,
        "labels": '{"application":"storefront","cost_center":"cc-3001","environment":"production","team":"commerce"}',
    }

    return pd.DataFrame(
        [
            {
                **base,
                "source_record_id": "gcp-usage-1",
                "service_description": "Compute Engine",
                "sku_description": "N2 Instance Core running in Americas",
                "resource_name": "instance-1001",
                "usage_amount": 1539.7750,
                "usage_unit": "vCPU-hours",
                "list_cost": 48.6738,
                "cost": 43.8836,
                "credits": '[{"amount":-4.3884,"name":"Committed Usage Discount","type":"COMMITTED_USAGE_DISCOUNT"}]',
                "cost_type": "regular",
            },
            {
                **base,
                "source_record_id": "gcp-credit-1",
                "service_description": "Promotional Credits",
                "sku_description": "Promotion",
                "resource_name": None,
                "usage_amount": None,
                "usage_unit": None,
                "list_cost": 0,
                "cost": 0,
                "credits": '[{"amount":-4500.0,"name":"Promotion","type":"PROMOTION"}]',
                "cost_type": "regular",
            },
            {
                **base,
                "source_record_id": "gcp-adjustment-1",
                "service_description": "Cloud SQL",
                "sku_description": "Adjustment",
                "resource_name": None,
                "usage_amount": None,
                "usage_unit": None,
                "list_cost": 0,
                "cost": -600,
                "credits": "[]",
                "cost_type": "adjustment",
            },
        ]
    )


def test_gcp_adapter_maps_usage_credit_and_adjustment():
    rows = adapt_gcp_dataframe(_gcp_dataframe())

    usage, credit, adjustment = rows

    assert len(rows) == 3
    assert usage.provider_name is ProviderName.GCP
    assert usage.service_category is ServiceCategory.COMPUTE
    assert usage.charge_category is ChargeCategory.USAGE
    assert usage.pricing_category is PricingCategory.COMMITTED
    assert usage.list_cost == Decimal("48.6738")
    assert usage.billed_cost == Decimal("39.4952")
    assert usage.billing_period_start.month == 4
    assert usage.billing_period_end.month == 5
    assert usage.application == "storefront"

    assert credit.charge_category is ChargeCategory.CREDIT
    assert credit.pricing_category is None
    assert credit.billed_cost == Decimal("-4500.0")

    assert adjustment.service_category is ServiceCategory.DATABASES
    assert adjustment.charge_category is ChargeCategory.ADJUSTMENT
    assert adjustment.pricing_category is None
    assert adjustment.billed_cost == Decimal("-600")