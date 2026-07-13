"""Configuration model for cost-allocation rules."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_RULES_PATH = Path("config/allocation_rules.json")


@dataclass(frozen=True, slots=True)
class AllocationRules:
    """Validated allocation configuration."""

    primary_group_columns: tuple[str, ...]
    fallback_group_columns: tuple[str, ...]
    target_columns: tuple[str, ...]
    driver_charge_categories: tuple[str, ...]
    driver_minimum_cost: float
    cost_precision: int
    unallocated_application: str
    unallocated_environment: str
    unallocated_cost_center: str
    unallocated_owner: str

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "AllocationRules":
        required = {
            "primary_group_columns",
            "fallback_group_columns",
            "target_columns",
            "driver_charge_categories",
            "driver_minimum_cost",
            "cost_precision",
            "unallocated_values",
        }

        missing = required - values.keys()
        if missing:
            raise ValueError(
                "Allocation rules missing keys: "
                + ", ".join(sorted(missing))
            )

        unallocated = values["unallocated_values"]
        unallocated_required = {
            "application",
            "environment",
            "cost_center",
            "owner",
        }
        missing_unallocated = unallocated_required - unallocated.keys()
        if missing_unallocated:
            raise ValueError(
                "unallocated_values missing keys: "
                + ", ".join(sorted(missing_unallocated))
            )

        precision = int(values["cost_precision"])
        if precision < 0 or precision > 8:
            raise ValueError("cost_precision must be between 0 and 8")

        return cls(
            primary_group_columns=tuple(values["primary_group_columns"]),
            fallback_group_columns=tuple(values["fallback_group_columns"]),
            target_columns=tuple(values["target_columns"]),
            driver_charge_categories=tuple(
                values["driver_charge_categories"]
            ),
            driver_minimum_cost=float(values["driver_minimum_cost"]),
            cost_precision=precision,
            unallocated_application=str(unallocated["application"]),
            unallocated_environment=str(unallocated["environment"]),
            unallocated_cost_center=str(unallocated["cost_center"]),
            unallocated_owner=str(unallocated["owner"]),
        )


def load_allocation_rules(
    path: Path | str = DEFAULT_RULES_PATH,
) -> AllocationRules:
    """Load and validate allocation rules from JSON."""

    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        values = json.load(handle)

    if not isinstance(values, dict):
        raise ValueError("Allocation rules JSON must contain an object")

    return AllocationRules.from_dict(values)
