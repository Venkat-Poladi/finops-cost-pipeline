"""Allocate normalized cloud costs to applications and cost centers.

Allocation order:
1. Directly tagged costs remain with their source owner.
2. Shared costs are distributed using positive direct Usage spend as
   the allocation driver within the same provider, billing month, and
   sub-account.
3. If a sub-account has no driver, provider-month weights are used.
4. Rows without a valid target remain Unallocated.

Run from the project root:

    python -m allocation.allocate_costs
"""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable
import hashlib

import pandas as pd

from allocation.allocation_rules import (
    AllocationRules,
    load_allocation_rules,
)


INPUT_PATH = Path("data/processed/focus_cost_usage.csv")
ALLOCATED_OUTPUT_PATH = Path("data/processed/allocated_cost_usage.csv")
SUMMARY_OUTPUT_PATH = Path("data/outputs/allocation_summary.csv")

REQUIRED_COLUMNS = {
    "record_id",
    "provider_name",
    "sub_account_id",
    "billing_period_start",
    "charge_category",
    "billed_cost",
    "effective_cost",
    "list_cost",
    "consumed_quantity",
    "allocation_status",
    "application",
    "environment",
    "cost_center",
    "owner",
}

SCALED_COLUMNS = (
    "consumed_quantity",
    "list_cost",
    "billed_cost",
    "effective_cost",
)


def _decimal(value: Any) -> Decimal:
    if value is None or pd.isna(value):
        return Decimal("0")

    text = str(value).strip()
    if not text:
        return Decimal("0")

    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Cannot convert value to Decimal: {value!r}") from exc


def _text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _group_key(
    row: dict[str, Any],
    columns: Iterable[str],
) -> tuple[str, ...]:
    return tuple(_text(row.get(column)) for column in columns)


def _target_key(
    row: dict[str, Any],
    columns: Iterable[str],
) -> tuple[str, ...]:
    return tuple(_text(row.get(column)) for column in columns)


def _quantizer(precision: int) -> Decimal:
    return Decimal("1").scaleb(-precision)


def _format_decimal(value: Decimal, precision: int) -> str:
    quantized = value.quantize(
        _quantizer(precision),
        rounding=ROUND_HALF_UP,
    )
    return format(quantized, f".{precision}f")


def _has_direct_target(
    row: dict[str, Any],
    rules: AllocationRules,
) -> bool:
    return (
        _text(row.get("allocation_status")) == "Allocated"
        and bool(_text(row.get("application")))
    )


def _build_driver_maps(
    rows: list[dict[str, Any]],
    rules: AllocationRules,
) -> tuple[
    dict[tuple[str, ...], list[dict[str, Any]]],
    dict[tuple[str, ...], list[dict[str, Any]]],
]:
    """Create primary and fallback proportional allocation weights."""

    primary_costs: dict[
        tuple[str, ...],
        dict[tuple[str, ...], Decimal],
    ] = {}
    fallback_costs: dict[
        tuple[str, ...],
        dict[tuple[str, ...], Decimal],
    ] = {}

    for row in rows:
        if not _has_direct_target(row, rules):
            continue

        if _text(row.get("charge_category")) not in (
            rules.driver_charge_categories
        ):
            continue

        driver_cost = _decimal(row.get("billed_cost"))
        if driver_cost <= Decimal(str(rules.driver_minimum_cost)):
            continue

        target = _target_key(row, rules.target_columns)
        primary = _group_key(row, rules.primary_group_columns)
        fallback = _group_key(row, rules.fallback_group_columns)

        primary_costs.setdefault(primary, {})
        primary_costs[primary][target] = (
            primary_costs[primary].get(target, Decimal("0"))
            + driver_cost
        )

        fallback_costs.setdefault(fallback, {})
        fallback_costs[fallback][target] = (
            fallback_costs[fallback].get(target, Decimal("0"))
            + driver_cost
        )

    def normalize(
        raw: dict[tuple[str, ...], dict[tuple[str, ...], Decimal]]
    ) -> dict[tuple[str, ...], list[dict[str, Any]]]:
        normalized: dict[tuple[str, ...], list[dict[str, Any]]] = {}

        for group, target_costs in raw.items():
            total = sum(target_costs.values(), Decimal("0"))
            if total <= 0:
                continue

            allocations = []
            for target, cost in sorted(target_costs.items()):
                allocations.append(
                    {
                        "target": target,
                        "driver_cost": cost,
                        "weight": cost / total,
                    }
                )

            normalized[group] = allocations

        return normalized

    return normalize(primary_costs), normalize(fallback_costs)


def _unallocated_target(
    rules: AllocationRules,
) -> tuple[str, str, str, str]:
    configured = {
        "application": rules.unallocated_application,
        "environment": rules.unallocated_environment,
        "cost_center": rules.unallocated_cost_center,
        "owner": rules.unallocated_owner,
    }
    return tuple(configured[column] for column in rules.target_columns)


def _allocation_id(
    record_id: str,
    method: str,
    target: tuple[str, ...],
    sequence: int,
) -> str:
    raw = "|".join((record_id, method, *target, str(sequence)))
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{record_id}-alloc-{digest}"


def _copy_and_allocate(
    row: dict[str, Any],
    *,
    target: tuple[str, ...],
    method: str,
    driver: str,
    weight: Decimal,
    sequence: int,
    rules: AllocationRules,
    residuals: dict[str, Decimal] | None = None,
) -> dict[str, Any]:
    result = dict(row)
    result["source_allocation_status"] = _text(
        row.get("allocation_status")
    )

    for column, value in zip(rules.target_columns, target):
        result[column] = value

    if method == "Unallocated":
        result["allocation_status"] = "Unallocated"
    else:
        result["allocation_status"] = "Allocated"

    result["allocation_method"] = method
    result["allocation_driver"] = driver
    result["allocation_weight"] = _format_decimal(
        weight,
        max(rules.cost_precision, 6),
    )
    result["allocation_id"] = _allocation_id(
        _text(row.get("record_id")),
        method,
        target,
        sequence,
    )

    for column in SCALED_COLUMNS:
        original = _decimal(row.get(column))
        allocated = original * weight

        if residuals and column in residuals:
            allocated += residuals[column]

        result[column] = _format_decimal(
            allocated,
            rules.cost_precision,
        )

    return result


def _allocate_shared_row(
    row: dict[str, Any],
    *,
    primary_map: dict[tuple[str, ...], list[dict[str, Any]]],
    fallback_map: dict[tuple[str, ...], list[dict[str, Any]]],
    rules: AllocationRules,
) -> list[dict[str, Any]]:
    primary_key = _group_key(row, rules.primary_group_columns)
    fallback_key = _group_key(row, rules.fallback_group_columns)

    targets = primary_map.get(primary_key)
    driver = "Direct spend: provider + billing month + sub-account"

    if not targets:
        targets = fallback_map.get(fallback_key)
        driver = "Direct spend fallback: provider + billing month"

    if not targets:
        return [
            _copy_and_allocate(
                row,
                target=_unallocated_target(rules),
                method="Unallocated",
                driver="No eligible direct-spend driver",
                weight=Decimal("1"),
                sequence=1,
                rules=rules,
            )
        ]

    allocated_rows: list[dict[str, Any]] = []
    rounded_totals = {
        column: Decimal("0") for column in SCALED_COLUMNS
    }

    for index, allocation in enumerate(targets, start=1):
        allocated = _copy_and_allocate(
            row,
            target=allocation["target"],
            method="Shared-Proportional",
            driver=driver,
            weight=allocation["weight"],
            sequence=index,
            rules=rules,
        )
        allocated_rows.append(allocated)

        for column in SCALED_COLUMNS:
            rounded_totals[column] += _decimal(allocated[column])

    # Apply rounding residual to the largest target so every source amount
    # reconciles exactly to its allocated fragments.
    largest_index = max(
        range(len(targets)),
        key=lambda index: targets[index]["weight"],
    )
    largest_row = allocated_rows[largest_index]

    for column in SCALED_COLUMNS:
        original = _decimal(row.get(column)).quantize(
            _quantizer(rules.cost_precision),
            rounding=ROUND_HALF_UP,
        )
        residual = original - rounded_totals[column]

        if residual:
            corrected = _decimal(largest_row[column]) + residual
            largest_row[column] = _format_decimal(
                corrected,
                rules.cost_precision,
            )

    return allocated_rows


def allocate_dataframe(
    dataframe: pd.DataFrame,
    rules: AllocationRules,
) -> pd.DataFrame:
    """Allocate a normalized FOCUS DataFrame."""

    missing = REQUIRED_COLUMNS - set(dataframe.columns)
    if missing:
        raise ValueError(
            "Normalized data missing required columns: "
            + ", ".join(sorted(missing))
        )

    rows = dataframe.fillna("").to_dict(orient="records")
    primary_map, fallback_map = _build_driver_maps(rows, rules)

    allocated_rows: list[dict[str, Any]] = []

    for row in rows:
        status = _text(row.get("allocation_status"))

        if _has_direct_target(row, rules):
            target = _target_key(row, rules.target_columns)
            allocated_rows.append(
                _copy_and_allocate(
                    row,
                    target=target,
                    method="Direct",
                    driver="Source tags/labels",
                    weight=Decimal("1"),
                    sequence=1,
                    rules=rules,
                )
            )
        elif status == "Shared":
            allocated_rows.extend(
                _allocate_shared_row(
                    row,
                    primary_map=primary_map,
                    fallback_map=fallback_map,
                    rules=rules,
                )
            )
        else:
            allocated_rows.append(
                _copy_and_allocate(
                    row,
                    target=_unallocated_target(rules),
                    method="Unallocated",
                    driver="Missing allocation metadata",
                    weight=Decimal("1"),
                    sequence=1,
                    rules=rules,
                )
            )

    return pd.DataFrame(allocated_rows)


def build_allocation_summary(
    allocated: pd.DataFrame,
) -> pd.DataFrame:
    """Create a business-facing allocation summary."""

    summary_columns = [
        "provider_name",
        "billing_period_start",
        "allocation_method",
        "allocation_status",
        "application",
        "environment",
        "cost_center",
        "owner",
    ]

    summary = allocated.copy()
    summary["billed_cost"] = pd.to_numeric(
        summary["billed_cost"],
        errors="raise",
    )

    grouped = (
        summary.groupby(
            summary_columns,
            dropna=False,
            as_index=False,
        )
        .agg(
            allocated_rows=("allocation_id", "count"),
            allocated_billed_cost=("billed_cost", "sum"),
        )
        .sort_values(
            [
                "billing_period_start",
                "provider_name",
                "allocation_method",
                "application",
            ]
        )
        .reset_index(drop=True)
    )

    return grouped


def run_allocation(
    input_path: Path | str = INPUT_PATH,
    rules_path: Path | str = "config/allocation_rules.json",
    allocated_output_path: Path | str = ALLOCATED_OUTPUT_PATH,
    summary_output_path: Path | str = SUMMARY_OUTPUT_PATH,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run allocation, save outputs, and print control totals."""

    source = pd.read_csv(
        input_path,
        dtype=str,
        keep_default_na=False,
    )
    rules = load_allocation_rules(rules_path)
    allocated = allocate_dataframe(source, rules)
    summary = build_allocation_summary(allocated)

    allocated_path = Path(allocated_output_path)
    summary_path = Path(summary_output_path)
    allocated_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    allocated.to_csv(allocated_path, index=False)
    summary.to_csv(summary_path, index=False, float_format="%.4f")

    source_total = sum(
        (_decimal(value) for value in source["billed_cost"]),
        Decimal("0"),
    )
    allocated_total = sum(
        (_decimal(value) for value in allocated["billed_cost"]),
        Decimal("0"),
    )
    variance = allocated_total - source_total

    print(f"Input rows: {len(source):,}")
    print(f"Allocated output rows: {len(allocated):,}")
    print(
        "Allocation methods:\n"
        + allocated["allocation_method"].value_counts().to_string()
    )
    print(f"\nSource net billed cost: ${source_total:,.4f}")
    print(f"Allocated net billed cost: ${allocated_total:,.4f}")
    print(f"Allocation variance: ${variance:,.4f}")
    print(f"Allocated data: {allocated_path.as_posix()}")
    print(f"Summary: {summary_path.as_posix()}")

    if abs(variance) > _quantizer(rules.cost_precision):
        raise ValueError(
            f"Allocation failed cost conservation: variance={variance}"
        )

    return allocated, summary


if __name__ == "__main__":
    run_allocation()
