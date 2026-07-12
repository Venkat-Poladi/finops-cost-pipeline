"""Validate the normalized multi-cloud FOCUS dataset.

The validator separates hard data errors from FinOps allocation warnings.
It reports issues without modifying or deleting source records.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from ingestion.focus_schema import (
    AllocationStatus,
    ChargeCategory,
    ChargeClass,
    FOCUS_COLUMNS,
    PricingCategory,
    ProviderName,
    ServiceCategory,
)


ISSUE_COLUMNS: tuple[str, ...] = (
    "rule_id",
    "severity",
    "dataset_row_number",
    "record_id",
    "provider_name",
    "source_file",
    "source_row_number",
    "field_name",
    "observed_value",
    "message",
)

REQUIRED_FIELDS: tuple[str, ...] = (
    "record_id",
    "provider_name",
    "billing_account_id",
    "charge_period_start",
    "charge_period_end",
    "billing_period_start",
    "billing_period_end",
    "service_name",
    "service_category",
    "billing_currency",
    "list_cost",
    "billed_cost",
    "effective_cost",
    "charge_category",
    "allocation_status",
    "source_file",
    "source_row_number",
)

DATE_FIELDS: tuple[str, ...] = (
    "charge_period_start",
    "charge_period_end",
    "billing_period_start",
    "billing_period_end",
)

NUMERIC_FIELDS: tuple[str, ...] = (
    "consumed_quantity",
    "list_unit_price",
    "list_cost",
    "billed_cost",
    "effective_cost",
    "source_row_number",
)


def validate_focus_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Return one report row for every validation issue found."""

    issues: list[dict[str, Any]] = []
    frame = dataframe.copy().reset_index(drop=True)

    missing_columns = [
        column for column in FOCUS_COLUMNS if column not in frame.columns
    ]
    extra_columns = [
        column for column in frame.columns if column not in FOCUS_COLUMNS
    ]

    for column in missing_columns:
        _append_dataset_issue(
            issues,
            rule_id="schema.missing_column",
            severity="ERROR",
            field_name=column,
            observed_value="missing",
            message=f"Required normalized column '{column}' is missing.",
        )

    for column in extra_columns:
        _append_dataset_issue(
            issues,
            rule_id="schema.extra_column",
            severity="WARNING",
            field_name=column,
            observed_value="present",
            message=f"Unexpected column '{column}' is not in FOCUS_COLUMNS.",
        )

    # Row-level checks require the complete schema.
    if missing_columns:
        return _issues_dataframe(issues)

    blank_masks = {
        column: _blank_mask(frame[column]) for column in frame.columns
    }

    for field_name in REQUIRED_FIELDS:
        _append_masked_issues(
            issues,
            frame,
            blank_masks[field_name],
            rule_id="required.missing_value",
            severity="ERROR",
            field_name=field_name,
            message=f"Required field '{field_name}' is blank.",
        )

    parsed_dates: dict[str, pd.Series] = {}
    for field_name in DATE_FIELDS:
        parsed = pd.to_datetime(frame[field_name], errors="coerce", utc=True)
        parsed_dates[field_name] = parsed
        invalid = ~blank_masks[field_name] & parsed.isna()
        _append_masked_issues(
            issues,
            frame,
            invalid,
            rule_id="format.invalid_datetime",
            severity="ERROR",
            field_name=field_name,
            message=f"'{field_name}' is not a valid datetime.",
        )

    parsed_numbers: dict[str, pd.Series] = {}
    for field_name in NUMERIC_FIELDS:
        parsed = pd.to_numeric(frame[field_name], errors="coerce")
        parsed_numbers[field_name] = parsed
        invalid = ~blank_masks[field_name] & parsed.isna()
        _append_masked_issues(
            issues,
            frame,
            invalid,
            rule_id="format.invalid_number",
            severity="ERROR",
            field_name=field_name,
            message=f"'{field_name}' is not numeric.",
        )

    _validate_allowed_values(issues, frame, blank_masks)
    _validate_currency(issues, frame, blank_masks)
    _validate_periods(issues, frame, parsed_dates)
    _validate_source_row_numbers(
        issues,
        frame,
        parsed_numbers["source_row_number"],
    )
    _validate_quantity_unit_pair(issues, frame, blank_masks)
    _validate_pricing_category(issues, frame, blank_masks)
    _validate_tags(issues, frame, blank_masks)
    _validate_duplicate_records(issues, frame, blank_masks)
    _validate_negative_usage_costs(
        issues,
        frame,
        parsed_numbers["billed_cost"],
    )
    _validate_list_cost_math(issues, frame, parsed_numbers)
    _validate_allocation(issues, frame, blank_masks)

    return _issues_dataframe(issues)


def validate_focus_csv(
    input_path: str | Path = "data/processed/focus_cost_usage.csv",
    output_path: str | Path = "data/outputs/validation_report.csv",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Validate a CSV, save the issue report, and return its summary."""

    source = Path(input_path)
    if not source.exists():
        raise FileNotFoundError(f"Input file does not exist: {source}")

    dataframe = pd.read_csv(source, dtype={"record_id": "string"})
    issues = validate_focus_dataframe(dataframe)

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    issues.to_csv(destination, index=False)

    return issues, summarize_validation(dataframe, issues)


def summarize_validation(
    dataframe: pd.DataFrame,
    issues: pd.DataFrame,
) -> dict[str, Any]:
    """Create a compact operational summary of the validation run."""

    if issues.empty:
        error_count = 0
        warning_count = 0
        affected_rows = 0
    else:
        error_count = int((issues["severity"] == "ERROR").sum())
        warning_count = int((issues["severity"] == "WARNING").sum())
        affected_rows = int(
            issues["dataset_row_number"].dropna().nunique()
        )

    billed_cost = pd.to_numeric(
        dataframe.get("billed_cost", pd.Series(dtype=float)),
        errors="coerce",
    ).sum()

    return {
        "total_rows": int(len(dataframe)),
        "total_issues": int(len(issues)),
        "error_count": error_count,
        "warning_count": warning_count,
        "affected_rows": affected_rows,
        "net_billed_cost": float(billed_cost),
        "passed": error_count == 0,
    }


def _validate_allowed_values(
    issues: list[dict[str, Any]],
    frame: pd.DataFrame,
    blank_masks: dict[str, pd.Series],
) -> None:
    allowed_by_field = {
        "provider_name": {item.value for item in ProviderName},
        "service_category": {item.value for item in ServiceCategory},
        "pricing_category": {item.value for item in PricingCategory},
        "charge_category": {item.value for item in ChargeCategory},
        "charge_class": {item.value for item in ChargeClass},
        "allocation_status": {item.value for item in AllocationStatus},
    }

    optional_fields = {"pricing_category", "charge_class"}

    for field_name, allowed_values in allowed_by_field.items():
        values = frame[field_name].astype("string").str.strip()
        invalid = ~values.isin(allowed_values)
        if field_name in optional_fields:
            invalid &= ~blank_masks[field_name]

        _append_masked_issues(
            issues,
            frame,
            invalid,
            rule_id="enum.invalid_value",
            severity="ERROR",
            field_name=field_name,
            message=(
                f"'{field_name}' must be one of: "
                f"{', '.join(sorted(allowed_values))}."
            ),
        )


def _validate_currency(
    issues: list[dict[str, Any]],
    frame: pd.DataFrame,
    blank_masks: dict[str, pd.Series],
) -> None:
    values = frame["billing_currency"].astype("string").str.strip()
    valid = values.str.fullmatch(r"[A-Z]{3}", na=False)
    invalid = ~blank_masks["billing_currency"] & ~valid
    _append_masked_issues(
        issues,
        frame,
        invalid,
        rule_id="currency.invalid_code",
        severity="ERROR",
        field_name="billing_currency",
        message="Billing currency must be three uppercase letters.",
    )


def _validate_periods(
    issues: list[dict[str, Any]],
    frame: pd.DataFrame,
    dates: dict[str, pd.Series],
) -> None:
    valid_charge_dates = (
        dates["charge_period_start"].notna()
        & dates["charge_period_end"].notna()
    )
    invalid_charge_range = valid_charge_dates & (
        dates["charge_period_start"] >= dates["charge_period_end"]
    )
    _append_masked_issues(
        issues,
        frame,
        invalid_charge_range,
        rule_id="period.invalid_charge_range",
        severity="ERROR",
        field_name="charge_period_end",
        message="Charge period end must be later than its start.",
    )

    valid_billing_dates = (
        dates["billing_period_start"].notna()
        & dates["billing_period_end"].notna()
    )
    invalid_billing_range = valid_billing_dates & (
        dates["billing_period_start"] >= dates["billing_period_end"]
    )
    _append_masked_issues(
        issues,
        frame,
        invalid_billing_range,
        rule_id="period.invalid_billing_range",
        severity="ERROR",
        field_name="billing_period_end",
        message="Billing period end must be later than its start.",
    )

    all_dates_valid = valid_charge_dates & valid_billing_dates
    charge_outside_billing = all_dates_valid & (
        (dates["charge_period_start"] < dates["billing_period_start"])
        | (dates["charge_period_start"] >= dates["billing_period_end"])
    )
    _append_masked_issues(
        issues,
        frame,
        charge_outside_billing,
        rule_id="period.charge_outside_billing",
        severity="ERROR",
        field_name="charge_period_start",
        message="Charge start must fall inside its billing period.",
    )


def _validate_source_row_numbers(
    issues: list[dict[str, Any]],
    frame: pd.DataFrame,
    values: pd.Series,
) -> None:
    invalid = values.notna() & ((values < 1) | (values % 1 != 0))
    _append_masked_issues(
        issues,
        frame,
        invalid,
        rule_id="lineage.invalid_source_row",
        severity="ERROR",
        field_name="source_row_number",
        message="Source row number must be a positive whole number.",
    )


def _validate_quantity_unit_pair(
    issues: list[dict[str, Any]],
    frame: pd.DataFrame,
    blank_masks: dict[str, pd.Series],
) -> None:
    mismatch = (
        blank_masks["consumed_quantity"]
        != blank_masks["consumed_unit"]
    )
    _append_masked_issues(
        issues,
        frame,
        mismatch,
        rule_id="usage.quantity_unit_mismatch",
        severity="ERROR",
        field_name="consumed_quantity,consumed_unit",
        message=(
            "Consumed quantity and consumed unit must both be populated "
            "or both be blank."
        ),
    )


def _validate_pricing_category(
    issues: list[dict[str, Any]],
    frame: pd.DataFrame,
    blank_masks: dict[str, pd.Series],
) -> None:
    category = frame["charge_category"].astype("string").str.strip()
    charge_class_blank = blank_masks["charge_class"]
    missing_pricing = (
        category.isin(
            [ChargeCategory.USAGE.value, ChargeCategory.PURCHASE.value]
        )
        & charge_class_blank
        & blank_masks["pricing_category"]
    )
    _append_masked_issues(
        issues,
        frame,
        missing_pricing,
        rule_id="pricing.missing_category",
        severity="ERROR",
        field_name="pricing_category",
        message="Normal Usage and Purchase rows require pricing_category.",
    )


def _validate_tags(
    issues: list[dict[str, Any]],
    frame: pd.DataFrame,
    blank_masks: dict[str, pd.Series],
) -> None:
    invalid = pd.Series(False, index=frame.index)

    for position, value in frame["tags"].items():
        if blank_masks["tags"].iloc[position]:
            continue
        try:
            parsed = value if isinstance(value, dict) else json.loads(str(value))
            if not isinstance(parsed, dict):
                invalid.iloc[position] = True
        except (TypeError, ValueError, json.JSONDecodeError):
            invalid.iloc[position] = True

    _append_masked_issues(
        issues,
        frame,
        invalid,
        rule_id="tags.invalid_json",
        severity="ERROR",
        field_name="tags",
        message="Tags must contain a valid JSON object.",
    )


def _validate_duplicate_records(
    issues: list[dict[str, Any]],
    frame: pd.DataFrame,
    blank_masks: dict[str, pd.Series],
) -> None:
    duplicate = frame.duplicated(
        subset=["provider_name", "record_id"],
        keep="first",
    )
    duplicate &= ~blank_masks["record_id"]
    _append_masked_issues(
        issues,
        frame,
        duplicate,
        rule_id="duplicate.record_id",
        severity="ERROR",
        field_name="record_id",
        message="Provider and record_id combination is duplicated.",
    )


def _validate_negative_usage_costs(
    issues: list[dict[str, Any]],
    frame: pd.DataFrame,
    billed_cost: pd.Series,
) -> None:
    category = frame["charge_category"].astype("string").str.strip()
    charge_class = frame["charge_class"].astype("string").str.strip()
    descriptive_text = (
        frame["record_id"].fillna("").astype(str)
        + " "
        + frame["service_name"].fillna("").astype(str)
        + " "
        + frame["charge_description"].fillna("").astype(str)
    ).str.lower()

    legitimate_refund = descriptive_text.str.contains(
        r"\brefund\b", regex=True, na=False
    )
    correction = charge_class.eq(ChargeClass.CORRECTION.value).fillna(False)

    invalid = (
        category.eq(ChargeCategory.USAGE.value)
        & billed_cost.notna()
        & billed_cost.lt(0)
        & ~legitimate_refund
        & ~correction
    )
    _append_masked_issues(
        issues,
        frame,
        invalid,
        rule_id="cost.negative_usage",
        severity="ERROR",
        field_name="billed_cost",
        message=(
            "Negative Usage cost is invalid unless the row is a refund "
            "or correction."
        ),
    )


def _validate_list_cost_math(
    issues: list[dict[str, Any]],
    frame: pd.DataFrame,
    numbers: dict[str, pd.Series],
) -> None:
    quantity = numbers["consumed_quantity"]
    unit_price = numbers["list_unit_price"]
    list_cost = numbers["list_cost"]
    category = frame["charge_category"].astype("string").str.strip()

    comparable = (
        quantity.notna()
        & unit_price.notna()
        & list_cost.notna()
        & quantity.ne(0)
        & category.isin(
            [ChargeCategory.USAGE.value, ChargeCategory.PURCHASE.value]
        )
    )
    expected = quantity * unit_price
    tolerance = (list_cost.abs() * 0.0001).clip(lower=0.01)
    mismatch = comparable & (expected.sub(list_cost).abs() > tolerance)

    _append_masked_issues(
        issues,
        frame,
        mismatch,
        rule_id="cost.list_cost_mismatch",
        severity="ERROR",
        field_name="list_cost",
        message=(
            "List cost does not equal consumed_quantity × "
            "list_unit_price within tolerance."
        ),
    )


def _validate_allocation(
    issues: list[dict[str, Any]],
    frame: pd.DataFrame,
    blank_masks: dict[str, pd.Series],
) -> None:
    status = frame["allocation_status"].astype("string").str.strip()
    unallocated = status.eq(AllocationStatus.UNALLOCATED.value)
    _append_masked_issues(
        issues,
        frame,
        unallocated,
        rule_id="allocation.unallocated",
        severity="WARNING",
        field_name="allocation_status",
        message=(
            "Row is valid but lacks sufficient ownership metadata for "
            "showback or chargeback."
        ),
    )

    ownership_blank = (
        blank_masks["application"]
        & blank_masks["environment"]
        & blank_masks["cost_center"]
        & blank_masks["owner"]
    )
    inconsistent = (
        status.eq(AllocationStatus.ALLOCATED.value) & ownership_blank
    )
    _append_masked_issues(
        issues,
        frame,
        inconsistent,
        rule_id="allocation.status_inconsistent",
        severity="ERROR",
        field_name="allocation_status",
        message=(
            "Allocation status is Allocated but all ownership fields are blank."
        ),
    )


def _append_masked_issues(
    issues: list[dict[str, Any]],
    frame: pd.DataFrame,
    mask: pd.Series,
    *,
    rule_id: str,
    severity: str,
    field_name: str,
    message: str,
) -> None:
    for position in frame.index[mask.fillna(False)]:
        row = frame.iloc[position]
        observed = (
            _display_value(row.get(field_name))
            if field_name in frame.columns
            else ""
        )
        _append_row_issue(
            issues,
            row,
            position=position,
            rule_id=rule_id,
            severity=severity,
            field_name=field_name,
            observed_value=observed,
            message=message,
        )


def _append_row_issue(
    issues: list[dict[str, Any]],
    row: pd.Series,
    *,
    position: int,
    rule_id: str,
    severity: str,
    field_name: str,
    observed_value: str,
    message: str,
) -> None:
    issues.append(
        {
            "rule_id": rule_id,
            "severity": severity,
            "dataset_row_number": position + 2,
            "record_id": _display_value(row.get("record_id")),
            "provider_name": _display_value(row.get("provider_name")),
            "source_file": _display_value(row.get("source_file")),
            "source_row_number": _display_value(
                row.get("source_row_number")
            ),
            "field_name": field_name,
            "observed_value": observed_value,
            "message": message,
        }
    )


def _append_dataset_issue(
    issues: list[dict[str, Any]],
    *,
    rule_id: str,
    severity: str,
    field_name: str,
    observed_value: str,
    message: str,
) -> None:
    issues.append(
        {
            "rule_id": rule_id,
            "severity": severity,
            "dataset_row_number": None,
            "record_id": "",
            "provider_name": "",
            "source_file": "",
            "source_row_number": "",
            "field_name": field_name,
            "observed_value": observed_value,
            "message": message,
        }
    )


def _blank_mask(series: pd.Series) -> pd.Series:
    return series.isna() | series.astype("string").str.strip().eq("")


def _display_value(value: Any) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _issues_dataframe(issues: list[dict[str, Any]]) -> pd.DataFrame:
    if not issues:
        return pd.DataFrame(columns=ISSUE_COLUMNS)

    report = pd.DataFrame(issues, columns=ISSUE_COLUMNS)
    severity_order = pd.Categorical(
        report["severity"],
        categories=["ERROR", "WARNING"],
        ordered=True,
    )
    report = (
        report.assign(_severity_order=severity_order)
        .sort_values(
            ["_severity_order", "rule_id", "dataset_row_number"],
            na_position="first",
        )
        .drop(columns="_severity_order")
        .reset_index(drop=True)
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a normalized FOCUS cost dataset."
    )
    parser.add_argument(
        "--input",
        default="data/processed/focus_cost_usage.csv",
        help="Normalized input CSV.",
    )
    parser.add_argument(
        "--output",
        default="data/outputs/validation_report.csv",
        help="Validation issue report CSV.",
    )
    parser.add_argument(
        "--fail-on-errors",
        action="store_true",
        help="Exit with status 1 when hard errors are found.",
    )
    args = parser.parse_args()

    issues, summary = validate_focus_csv(args.input, args.output)

    print(f"Validated {summary['total_rows']:,} rows.")
    print(
        f"Errors: {summary['error_count']:,} | "
        f"Warnings: {summary['warning_count']:,} | "
        f"Affected rows: {summary['affected_rows']:,}"
    )
    print(f"Net billed cost: ${summary['net_billed_cost']:,.2f}")
    print(f"Report: {args.output}")

    if not issues.empty:
        counts = issues.groupby(["severity", "rule_id"]).size()
        print("\nIssues by rule:")
        print(counts.to_string())

    if args.fail_on_errors and summary["error_count"] > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
