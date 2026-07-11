"""Normalize the synthetic AWS billing CSV into FocusRow objects."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from ingestion.focus_schema import (
    AllocationStatus,
    ChargeCategory,
    FocusRow,
    PricingCategory,
    ProviderName,
    ServiceCategory,
)


AWS_SERVICE_CATEGORY_MAP = {
    "Amazon Elastic Compute Cloud - Compute": ServiceCategory.COMPUTE,
    "Amazon Relational Database Service": ServiceCategory.DATABASES,
    "Amazon Simple Storage Service": ServiceCategory.STORAGE,
    "AWS Lambda": ServiceCategory.COMPUTE,
    "AmazonCloudWatch": ServiceCategory.MANAGEMENT_AND_GOVERNANCE,
    "AWS Promotional Credits": ServiceCategory.OTHER,
}


def adapt_aws_csv(path: str | Path) -> list[FocusRow]:
    source_path = Path(path)
    dataframe = pd.read_csv(source_path)
    return adapt_aws_dataframe(dataframe, source_file=source_path.name)


def adapt_aws_dataframe(
    dataframe: pd.DataFrame,
    source_file: str = "aws_billing_sample.csv",
) -> list[FocusRow]:
    rows: list[FocusRow] = []

    for source_row_number, (_, source) in enumerate(
        dataframe.iterrows(), start=2
    ):
        line_item_type = _clean_text(
            source.get("line_item_line_item_type")
        ) or "Usage"
        charge_category = _map_charge_category(line_item_type)
        pricing_category = _map_pricing_category(
            line_item_type=line_item_type,
            pricing_term=_clean_text(source.get("pricing_term")),
            charge_category=charge_category,
        )

        tags = _parse_json_mapping(source.get("resource_tags"))
        application = _clean_text(source.get("application"))
        environment = _clean_text(source.get("environment"))
        cost_center = _clean_text(source.get("cost_center"))
        owner = _clean_text(source.get("team"))

        quantity, unit = _quantity_and_unit(
            source.get("line_item_usage_amount"),
            source.get("pricing_unit"),
        )

        billed_cost = _to_decimal(
            source.get("line_item_unblended_cost"),
            default=Decimal("0"),
        )
        list_cost = _to_decimal(
            source.get("pricing_public_on_demand_cost"),
            default=Decimal("0"),
        )

        rows.append(
            FocusRow(
                record_id=_required_text(
                    source.get("source_record_id"),
                    "source_record_id",
                ),
                provider_name=ProviderName.AWS,
                billing_account_id=_required_text(
                    source.get("bill_payer_account_id"),
                    "bill_payer_account_id",
                ),
                sub_account_id=_clean_text(
                    source.get("line_item_usage_account_id")
                ),
                sub_account_name=_clean_text(source.get("account_name")),
                charge_period_start=_to_datetime(
                    source.get("line_item_usage_start_date")
                ),
                charge_period_end=_to_datetime(
                    source.get("line_item_usage_end_date")
                ),
                billing_period_start=_to_datetime(
                    source.get("bill_billing_period_start_date")
                ),
                billing_period_end=_to_datetime(
                    source.get("bill_billing_period_end_date")
                ),
                service_name=_required_text(
                    source.get("product_product_name"),
                    "product_product_name",
                ),
                service_category=AWS_SERVICE_CATEGORY_MAP.get(
                    _clean_text(source.get("product_product_name")) or "",
                    ServiceCategory.OTHER,
                ),
                sku_description=_first_text(
                    source.get("line_item_usage_type"),
                    source.get("line_item_operation"),
                ),
                resource_id=_clean_text(
                    source.get("line_item_resource_id")
                ),
                region=_clean_text(source.get("product_region")),
                availability_zone=None,
                consumed_quantity=quantity,
                consumed_unit=unit,
                list_unit_price=_to_decimal(
                    source.get("pricing_public_on_demand_rate")
                ),
                pricing_category=pricing_category,
                billing_currency=_required_text(
                    source.get("currency"), "currency"
                ),
                list_cost=list_cost,
                billed_cost=billed_cost,
                effective_cost=billed_cost,
                charge_category=charge_category,
                charge_class=None,
                charge_description=_build_charge_description(source),
                tags=tags,
                application=application,
                environment=environment,
                cost_center=cost_center,
                owner=owner,
                allocation_status=_allocation_status(
                    application,
                    environment,
                    cost_center,
                    owner,
                ),
                source_file=source_file,
                source_row_number=source_row_number,
            )
        )

    return rows


def _map_charge_category(line_item_type: str) -> ChargeCategory:
    normalized = line_item_type.strip().lower()
    if normalized == "credit":
        return ChargeCategory.CREDIT
    if normalized == "refund":
        return ChargeCategory.USAGE
    if normalized == "tax":
        return ChargeCategory.TAX
    if normalized in {"fee", "purchase"}:
        return ChargeCategory.PURCHASE
    if normalized == "adjustment":
        return ChargeCategory.ADJUSTMENT
    return ChargeCategory.USAGE


def _map_pricing_category(
    *,
    line_item_type: str,
    pricing_term: str | None,
    charge_category: ChargeCategory,
) -> PricingCategory | None:
    if charge_category not in {
        ChargeCategory.USAGE,
        ChargeCategory.PURCHASE,
    }:
        return None

    if line_item_type.strip().lower() == "refund":
        return PricingCategory.OTHER

    normalized = (pricing_term or "").strip().lower()
    if normalized in {"ondemand", "on demand", "standard"}:
        return PricingCategory.STANDARD
    if any(token in normalized for token in ("reserved", "savings", "commit")):
        return PricingCategory.COMMITTED
    if "spot" in normalized:
        return PricingCategory.DYNAMIC
    return PricingCategory.OTHER


def _build_charge_description(source: pd.Series) -> str | None:
    values = [
        _clean_text(source.get("line_item_usage_type")),
        _clean_text(source.get("line_item_operation")),
        _clean_text(source.get("line_item_line_item_type")),
    ]
    unique = [value for index, value in enumerate(values) if value and value not in values[:index]]
    return " | ".join(unique) if unique else None


def _allocation_status(
    application: str | None,
    environment: str | None,
    cost_center: str | None,
    owner: str | None,
) -> AllocationStatus:
    values = [application, environment, cost_center, owner]
    normalized = " ".join(value.lower() for value in values if value)
    if "shared" in normalized:
        return AllocationStatus.SHARED
    if any(values):
        return AllocationStatus.ALLOCATED
    return AllocationStatus.UNALLOCATED


def _quantity_and_unit(
    quantity_value: Any,
    unit_value: Any,
) -> tuple[Decimal | None, str | None]:
    quantity = _to_decimal(quantity_value)
    unit = _clean_text(unit_value)
    if quantity is None or unit is None:
        return None, None
    return quantity, unit


def _parse_json_mapping(value: Any) -> dict[str, Any]:
    if _is_missing(value):
        return {}
    if isinstance(value, dict):
        return value
    parsed = json.loads(str(value))
    if not isinstance(parsed, dict):
        raise ValueError("resource_tags must contain a JSON object")
    return parsed


def _to_datetime(value: Any):
    return pd.to_datetime(value, utc=True).to_pydatetime()


def _to_decimal(
    value: Any,
    default: Decimal | None = None,
) -> Decimal | None:
    if _is_missing(value):
        return default
    return Decimal(str(value))


def _required_text(value: Any, field_name: str) -> str:
    text = _clean_text(value)
    if text is None:
        raise ValueError(f"{field_name} must not be blank")
    return text


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _clean_text(value)
        if text is not None:
            return text
    return None


def _clean_text(value: Any) -> str | None:
    if _is_missing(value):
        return None
    text = str(value).strip()
    return text or None


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False