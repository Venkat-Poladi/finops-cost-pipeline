"""Tests for normalized FOCUS data validation."""

from __future__ import annotations

import json

import pandas as pd

from ingestion.focus_schema import FOCUS_COLUMNS
from validation.validate_focus_data import (
    ISSUE_COLUMNS,
    validate_focus_csv,
    validate_focus_dataframe,
)


def make_valid_row(**overrides):
    row = {
        "record_id": "aws-row-1",
        "provider_name": "AWS",
        "billing_account_id": "999999999999",
        "sub_account_id": "111111111111",
        "sub_account_name": "production-account",
        "charge_period_start": "2026-04-01T00:00:00+00:00",
        "charge_period_end": "2026-04-02T00:00:00+00:00",
        "billing_period_start": "2026-04-01T00:00:00+00:00",
        "billing_period_end": "2026-05-01T00:00:00+00:00",
        "service_name": "Amazon Elastic Compute Cloud - Compute",
        "service_category": "Compute",
        "sku_description": "BoxUsage:m5.large",
        "resource_id": "i-123",
        "region": "us-east-1",
        "availability_zone": "us-east-1a",
        "consumed_quantity": "10",
        "consumed_unit": "Hrs",
        "list_unit_price": "2.00",
        "pricing_category": "Standard",
        "billing_currency": "USD",
        "list_cost": "20.00",
        "billed_cost": "18.00",
        "effective_cost": "18.00",
        "charge_category": "Usage",
        "charge_class": None,
        "charge_description": "Compute usage",
        "tags": json.dumps(
            {
                "application": "Checkout",
                "environment": "production",
                "cost_center": "CC-1001",
                "team": "Payments",
            }
        ),
        "application": "Checkout",
        "environment": "production",
        "cost_center": "CC-1001",
        "owner": "Payments",
        "allocation_status": "Allocated",
        "source_file": "aws_billing_sample.csv",
        "source_row_number": 2,
    }
    row.update(overrides)
    return row


def make_dataframe(*rows):
    return pd.DataFrame(rows, columns=FOCUS_COLUMNS)


def test_valid_dataframe_has_no_issues():
    report = validate_focus_dataframe(make_dataframe(make_valid_row()))

    assert tuple(report.columns) == ISSUE_COLUMNS
    assert report.empty


def test_duplicate_record_is_an_error():
    first = make_valid_row()
    duplicate = make_valid_row(source_row_number=3)

    report = validate_focus_dataframe(make_dataframe(first, duplicate))

    duplicate_issues = report[report["rule_id"] == "duplicate.record_id"]
    assert len(duplicate_issues) == 1
    assert duplicate_issues.iloc[0]["severity"] == "ERROR"


def test_negative_regular_usage_is_an_error_but_refund_is_allowed():
    invalid = make_valid_row(
        record_id="aws-negative-usage",
        billed_cost="-10.00",
        effective_cost="-10.00",
        charge_description="Compute usage",
    )
    refund = make_valid_row(
        record_id="aws-refund",
        billed_cost="-10.00",
        effective_cost="-10.00",
        list_cost="0",
        consumed_quantity=None,
        consumed_unit=None,
        list_unit_price=None,
        pricing_category="Other",
        charge_description="RDS Refund",
        source_row_number=3,
    )

    report = validate_focus_dataframe(make_dataframe(invalid, refund))

    negative_issues = report[report["rule_id"] == "cost.negative_usage"]
    assert len(negative_issues) == 1
    assert negative_issues.iloc[0]["record_id"] == "aws-negative-usage"


def test_unallocated_row_is_a_warning_not_an_error():
    row = make_valid_row(
        tags="{}",
        application=None,
        environment=None,
        cost_center=None,
        owner=None,
        allocation_status="Unallocated",
    )

    report = validate_focus_dataframe(make_dataframe(row))

    assert len(report) == 1
    assert report.iloc[0]["rule_id"] == "allocation.unallocated"
    assert report.iloc[0]["severity"] == "WARNING"


def test_format_period_and_pairing_errors_are_reported():
    row = make_valid_row(
        billing_currency="usd",
        charge_period_end="2026-03-31T00:00:00+00:00",
        consumed_unit=None,
    )

    report = validate_focus_dataframe(make_dataframe(row))
    rules = set(report["rule_id"])

    assert "currency.invalid_code" in rules
    assert "period.invalid_charge_range" in rules
    assert "usage.quantity_unit_mismatch" in rules


def test_list_cost_math_mismatch_is_reported():
    row = make_valid_row(list_cost="99.00")

    report = validate_focus_dataframe(make_dataframe(row))

    assert "cost.list_cost_mismatch" in set(report["rule_id"])


def test_missing_schema_column_stops_row_checks():
    dataframe = make_dataframe(make_valid_row()).drop(columns="record_id")

    report = validate_focus_dataframe(dataframe)

    assert len(report) == 1
    assert report.iloc[0]["rule_id"] == "schema.missing_column"
    assert report.iloc[0]["field_name"] == "record_id"


def test_validate_csv_writes_report(tmp_path):
    source = tmp_path / "focus.csv"
    destination = tmp_path / "validation_report.csv"
    make_dataframe(
        make_valid_row(
            tags="{}",
            application=None,
            environment=None,
            cost_center=None,
            owner=None,
            allocation_status="Unallocated",
        )
    ).to_csv(source, index=False)

    report, summary = validate_focus_csv(source, destination)

    assert destination.exists()
    assert len(report) == 1
    assert summary["warning_count"] == 1
    assert summary["error_count"] == 0
    assert summary["passed"] is True
