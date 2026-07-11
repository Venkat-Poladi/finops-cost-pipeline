"""Common FOCUS-aligned schema used by all cloud-provider adapters.

This module defines the normalized row structure for the project.
AWS and GCP adapters must convert their provider-specific billing rows
into FocusRow objects before data is combined or exported.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping


# The project targets a practical subset of the FOCUS cost-and-usage schema.
FOCUS_TARGET_VERSION = "1.2"


class ProviderName(str, Enum):
    """Cloud providers currently supported by the project."""

    AWS = "AWS"
    GCP = "GCP"


class ChargeCategory(str, Enum):
    """FOCUS top-level charge categories."""

    USAGE = "Usage"
    PURCHASE = "Purchase"
    TAX = "Tax"
    CREDIT = "Credit"
    ADJUSTMENT = "Adjustment"


class ChargeClass(str, Enum):
    """Identifies corrections to a previously invoiced billing period."""

    CORRECTION = "Correction"


class ServiceCategory(str, Enum):
    """FOCUS service categories used to compare services across providers."""

    AI_AND_MACHINE_LEARNING = "AI and Machine Learning"
    ANALYTICS = "Analytics"
    BUSINESS_APPLICATIONS = "Business Applications"
    COMPUTE = "Compute"
    DATABASES = "Databases"
    DEVELOPER_TOOLS = "Developer Tools"
    IDENTITY = "Identity"
    INTEGRATION = "Integration"
    INTERNET_OF_THINGS = "Internet of Things"
    MANAGEMENT_AND_GOVERNANCE = "Management and Governance"
    MEDIA = "Media"
    MIGRATION = "Migration"
    MOBILE = "Mobile"
    MULTICLOUD = "Multicloud"
    NETWORKING = "Networking"
    SECURITY = "Security"
    STORAGE = "Storage"
    WEB = "Web"
    OTHER = "Other"

class PricingCategory(str, Enum):
    """FOCUS pricing models used for cloud charges."""

    STANDARD = "Standard"
    COMMITTED = "Committed"
    DYNAMIC = "Dynamic"
    OTHER = "Other"

class AllocationStatus(str, Enum):
    """Project-specific allocation state for chargeback and showback."""

    ALLOCATED = "Allocated"
    SHARED = "Shared"
    UNALLOCATED = "Unallocated"


# Tags and labels in the current fixtures contain simple JSON-compatible values.
TagValue = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class FocusRow:
    """One normalized cloud billing row.

    The dataclass provides a typed contract between provider adapters
    and later pipeline stages.
    """

    # Identification and lineage
    record_id: str
    provider_name: ProviderName
    billing_account_id: str
    sub_account_id: str | None
    sub_account_name: str | None

    # Time periods
    charge_period_start: datetime
    charge_period_end: datetime
    billing_period_start: datetime
    billing_period_end: datetime

    # Service and resource
    service_name: str
    service_category: ServiceCategory
    sku_description: str | None
    resource_id: str | None
    region: str | None
    availability_zone: str | None

    # Usage
    consumed_quantity: Decimal | None
    consumed_unit: str | None
    list_unit_price: Decimal | None
    pricing_category: PricingCategory | None

    # Cost
    billing_currency: str
    list_cost: Decimal
    billed_cost: Decimal
    effective_cost: Decimal

    # Charge classification
    charge_category: ChargeCategory
    charge_class: ChargeClass | None
    charge_description: str | None

    # Ownership and allocation
    tags: Mapping[str, TagValue]
    application: str | None
    environment: str | None
    cost_center: str | None
    owner: str | None
    allocation_status: AllocationStatus

    # Source lineage
    source_file: str
    source_row_number: int

    def __post_init__(self) -> None:
        """Validate important schema rules when a row is created."""

        required_text_fields = {
            "record_id": self.record_id,
            "billing_account_id": self.billing_account_id,
            "service_name": self.service_name,
            "billing_currency": self.billing_currency,
            "source_file": self.source_file,
        }

        for field_name, value in required_text_fields.items():
            if not value or not value.strip():
                raise ValueError(f"{field_name} must not be blank")

        if self.charge_period_start >= self.charge_period_end:
            raise ValueError(
                "charge_period_end must be later than charge_period_start"
            )

        if self.billing_period_start >= self.billing_period_end:
            raise ValueError(
                "billing_period_end must be later than billing_period_start"
            )

        currency = self.billing_currency.strip().upper()

        if len(currency) != 3 or not currency.isalpha():
            raise ValueError(
                "billing_currency must be a three-letter currency code"
            )

        # Store currency consistently, such as USD instead of usd.
        object.__setattr__(self, "billing_currency", currency)

        if self.sub_account_name is not None and self.sub_account_id is None:
            raise ValueError(
                "sub_account_name cannot exist without sub_account_id"
            )

        quantity_missing = self.consumed_quantity is None
        unit_missing = self.consumed_unit is None

        if quantity_missing != unit_missing:
            raise ValueError(
                "consumed_quantity and consumed_unit must either both "
                "have values or both be None"
            )

        if self.list_unit_price is not None and self.list_unit_price < 0:
            raise ValueError("list_unit_price cannot be negative")
        if (
            self.charge_category
            in {ChargeCategory.USAGE, ChargeCategory.PURCHASE}
            and self.charge_class is None
            and self.pricing_category is None
        ):
            raise ValueError(
                "pricing_category is required for normal "
                "Usage and Purchase charges"
            )

        if (
            self.charge_category is ChargeCategory.TAX
            and self.pricing_category is not None
        ):
            raise ValueError(
                "pricing_category must be None for Tax charges"
            )

        if self.source_row_number < 1:
            raise ValueError("source_row_number must be at least 1")

        if not isinstance(self.tags, Mapping):
            raise TypeError("tags must be a mapping such as a dictionary")

    def to_dict(self) -> dict[str, Any]:
        """Convert the row into values suitable for a CSV or DataFrame."""

        return {
            "record_id": self.record_id,
            "provider_name": self.provider_name.value,
            "billing_account_id": self.billing_account_id,
            "sub_account_id": self.sub_account_id,
            "sub_account_name": self.sub_account_name,
            "charge_period_start": self.charge_period_start.isoformat(),
            "charge_period_end": self.charge_period_end.isoformat(),
            "billing_period_start": self.billing_period_start.isoformat(),
            "billing_period_end": self.billing_period_end.isoformat(),
            "service_name": self.service_name,
            "service_category": self.service_category.value,
            "sku_description": self.sku_description,
            "resource_id": self.resource_id,
            "region": self.region,
            "availability_zone": self.availability_zone,
            "consumed_quantity": self._decimal_to_string(
                self.consumed_quantity
            ),
            "consumed_unit": self.consumed_unit,
            "list_unit_price": self._decimal_to_string(
                self.list_unit_price
            ),
            "pricing_category": (
                self.pricing_category.value
                if self.pricing_category is not None
                else None
            ),
            "billing_currency": self.billing_currency,
            "list_cost": self._decimal_to_string(self.list_cost),
            "billed_cost": self._decimal_to_string(self.billed_cost),
            "effective_cost": self._decimal_to_string(
                self.effective_cost
            ),
            "charge_category": self.charge_category.value,
            "charge_class": (
                self.charge_class.value
                if self.charge_class is not None
                else None
            ),
            "charge_description": self.charge_description,
            "tags": json.dumps(
                dict(self.tags),
                sort_keys=True,
                separators=(",", ":"),
            ),
            "application": self.application,
            "environment": self.environment,
            "cost_center": self.cost_center,
            "owner": self.owner,
            "allocation_status": self.allocation_status.value,
            "source_file": self.source_file,
            "source_row_number": self.source_row_number,
        }

    @staticmethod
    def _decimal_to_string(value: Decimal | None) -> str | None:
        """Convert Decimal values without introducing float rounding."""

        if value is None:
            return None

        return format(value, "f")


FOCUS_COLUMNS: tuple[str, ...] = (
    "record_id",
    "provider_name",
    "billing_account_id",
    "sub_account_id",
    "sub_account_name",
    "charge_period_start",
    "charge_period_end",
    "billing_period_start",
    "billing_period_end",
    "service_name",
    "service_category",
    "sku_description",
    "resource_id",
    "region",
    "availability_zone",
    "consumed_quantity",
    "consumed_unit",
    "list_unit_price",
    "pricing_category",
    "billing_currency",
    "list_cost",
    "billed_cost",
    "effective_cost",
    "charge_category",
    "charge_class",
    "charge_description",
    "tags",
    "application",
    "environment",
    "cost_center",
    "owner",
    "allocation_status",
    "source_file",
    "source_row_number",
)