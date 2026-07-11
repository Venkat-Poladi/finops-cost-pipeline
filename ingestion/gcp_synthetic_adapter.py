"""Normalize the synthetic GCP billing CSV into FocusRow objects."""

from __future__ import annotations

import json
from datetime import datetime, timezone
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


GCP_SERVICE_CATEGORY_MAP = {
    "Compute Engine": ServiceCategory.COMPUTE,
    "Cloud Storage": ServiceCategory.STORAGE,
    "Cloud SQL": ServiceCategory.DATABASES,
    "BigQuery": ServiceCategory.ANALYTICS,
    "Cloud Logging": ServiceCategory.MANAGEMENT_AND_GOVERNANCE,
    "Promotional Credits": ServiceCategory.OTHER,
}


def adapt_gcp_csv(path: str | Path) -> list[FocusRow]:
    source_path = Path(path)
    dataframe = pd.read_csv(source_path)
    return adapt_gcp_dataframe(dataframe, source_file=source_path.name)


def adapt_gcp_dataframe(
    dataframe: pd.DataFrame,
    source_file: str = "gcp_billing_sample.csv",
) -> list[FocusRow]:
    rows: list[FocusRow] = []

    for source_row_number, (_, source) in enumerate(
        dataframe.iterrows(), start=2
    ):
        service_name = _required_text(
            source.get("service_description"),
            "service_description",
        )
        cost_type = (
            _clean_text(source.get("cost_type")) or "regular"
        ).lower()
        credits = _parse_credits(source.get("credits"))
        credit_total = sum(
            (_to_decimal(item.get("amount"), Decimal("0")) or Decimal("0"))
            for item in credits
        )
        source_cost = _to_decimal(
            source.get("cost"), default=Decimal("0")
        )
        billed_cost = source_cost + credit_total

        charge_category = _map_charge_category(
            service_name=service_name,
            cost_type=cost_type,
            credits=credits,
        )
        pricing_category = _map_pricing_category(
            charge_category=charge_category,
            credits=credits,
        )

        labels = _parse_json_mapping(source.get("labels"), "labels")
        application = _label_text(labels, "application")
        environment = _label_text(labels, "environment")
        cost_center = _label_text(labels, "cost_center")
        owner = _label_text(labels, "team") or _label_text(labels, "owner")

        quantity, unit = _quantity_and_unit(
            source.get("usage_amount"),
            source.get("usage_unit"),
        )
        list_cost = _to_decimal(
            source.get("list_cost"), default=Decimal("0")
        )
        list_unit_price = _derive_list_unit_price(
            list_cost=list_cost,
            quantity=quantity,
        )
        billing_period_start, billing_period_end = _invoice_period(
            source.get("invoice_month")
        )

        rows.append(
            FocusRow(
                record_id=_required_text(
                    source.get("source_record_id"),
                    "source_record_id",
                ),
                provider_name=ProviderName.GCP,
                billing_account_id=_required_text(
                    source.get("billing_account_id"),
                    "billing_account_id",
                ),
                sub_account_id=_clean_text(source.get("project_id")),
                sub_account_name=_clean_text(source.get("project_name")),
                charge_period_start=_to_datetime(
                    source.get("usage_start_time")
                ),
                charge_period_end=_to_datetime(
                    source.get("usage_end_time")
                ),
                billing_period_start=billing_period_start,
                billing_period_end=billing_period_end,
                service_name=service_name,
                service_category=GCP_SERVICE_CATEGORY_MAP.get(
                    service_name,
                    ServiceCategory.OTHER,
                ),
                sku_description=_clean_text(
                    source.get("sku_description")
                ),
                resource_id=_clean_text(source.get("resource_name")),
                region=_clean_text(source.get("location")),
                availability_zone=None,
                consumed_quantity=quantity,
                consumed_unit=unit,
                list_unit_price=list_unit_price,
                pricing_category=pricing_category,
                billing_currency=_required_text(
                    source.get("currency"), "currency"
                ),
                list_cost=list_cost,
                billed_cost=billed_cost,
                effective_cost=billed_cost,
                charge_category=charge_category,
                charge_class=None,
                charge_description=_clean_text(
                    source.get("sku_description")
                ) or service_name,
                tags=labels,
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


def _map_charge_category(
    *,
    service_name: str,
    cost_type: str,
    credits: list[dict[str, Any]],
) -> ChargeCategory:
    """Map GCP billing rows to FOCUS charge categories.

    Credits attached to normal usage rows reduce billed cost but do not
    change the row itself from Usage to Credit. Only a standalone
    promotional-credit row is classified as Credit.
    """

    if cost_type == "adjustment":
        return ChargeCategory.ADJUSTMENT

    if service_name == "Promotional Credits":
        return ChargeCategory.CREDIT

    return ChargeCategory.USAGE


def _map_pricing_category(
    *,
    charge_category: ChargeCategory,
    credits: list[dict[str, Any]],
) -> PricingCategory | None:
    if charge_category not in {
        ChargeCategory.USAGE,
        ChargeCategory.PURCHASE,
    }:
        return None

    credit_types = {
        str(item.get("type", "")).upper() for item in credits
    }
    if any("COMMITTED" in credit_type for credit_type in credit_types):
        return PricingCategory.COMMITTED
    return PricingCategory.STANDARD


def _invoice_period(value: Any) -> tuple[datetime, datetime]:
    text = _required_text(value, "invoice_month")
    if text.endswith(".0"):
        text = text[:-2]
    if len(text) != 6 or not text.isdigit():
        raise ValueError("invoice_month must use YYYYMM format")

    year = int(text[:4])
    month = int(text[4:])
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def _derive_list_unit_price(
    *,
    list_cost: Decimal,
    quantity: Decimal | None,
) -> Decimal | None:
    if quantity in {None, Decimal("0")}:
        return None
    return list_cost / quantity


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


def _parse_credits(value: Any) -> list[dict[str, Any]]:
    if _is_missing(value):
        return []
    if isinstance(value, list):
        parsed = value
    else:
        parsed = json.loads(str(value))
    if not isinstance(parsed, list) or not all(
        isinstance(item, dict) for item in parsed
    ):
        raise ValueError("credits must contain a JSON array of objects")
    return parsed


def _parse_json_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if _is_missing(value):
        return {}
    if isinstance(value, dict):
        return value
    parsed = json.loads(str(value))
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} must contain a JSON object")
    return parsed


def _label_text(labels: dict[str, Any], key: str) -> str | None:
    return _clean_text(labels.get(key))


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