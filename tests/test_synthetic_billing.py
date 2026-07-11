"""Regression tests for the synthetic billing-data generator."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENERATOR = PROJECT_ROOT / "data" / "sample" / "generate_synthetic_billing.py"
AWS_FILE = PROJECT_ROOT / "data" / "sample" / "aws_billing_sample.csv"
GCP_FILE = PROJECT_ROOT / "data" / "sample" / "gcp_billing_sample.csv"


def file_hash(path: Path) -> str:
    """Return a SHA-256 hash for reproducibility testing."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def billing_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run the generator once and load both output files."""

    subprocess.run(
        [sys.executable, str(GENERATOR)],
        cwd=PROJECT_ROOT,
        check=True,
    )

    aws = pd.read_csv(
        AWS_FILE,
        dtype={
            "bill_payer_account_id": "string",
            "line_item_usage_account_id": "string",
        },
    )

    gcp = pd.read_csv(
        GCP_FILE,
        dtype={
            "billing_account_id": "string",
            "invoice_month": "string",
            "project_id": "string",
        },
    )

    return aws, gcp


def test_generator_is_reproducible() -> None:
    """The fixed random seed must produce identical files on every run."""

    subprocess.run(
        [sys.executable, str(GENERATOR)],
        cwd=PROJECT_ROOT,
        check=True,
    )

    first_aws_hash = file_hash(AWS_FILE)
    first_gcp_hash = file_hash(GCP_FILE)

    subprocess.run(
        [sys.executable, str(GENERATOR)],
        cwd=PROJECT_ROOT,
        check=True,
    )

    assert file_hash(AWS_FILE) == first_aws_hash
    assert file_hash(GCP_FILE) == first_gcp_hash


def test_usage_dates_and_billing_periods_are_valid(
    billing_data: tuple[pd.DataFrame, pd.DataFrame],
) -> None:
    aws, gcp = billing_data

    aws_usage_dates = pd.to_datetime(
        aws["line_item_usage_start_date"],
        utc=True,
    )
    aws_billing_months = pd.to_datetime(
        aws["bill_billing_period_start_date"],
    ).dt.strftime("%Y%m")

    gcp_usage_dates = pd.to_datetime(
        gcp["usage_start_time"],
        utc=True,
    )
    gcp_invoice_months = gcp["invoice_month"].astype(str)

    assert aws_usage_dates.dt.date.nunique() == 90
    assert gcp_usage_dates.dt.date.nunique() == 90

    assert aws_usage_dates.min().date().isoformat() == "2026-04-01"
    assert aws_usage_dates.max().date().isoformat() == "2026-06-29"

    assert (
        aws_usage_dates.dt.strftime("%Y%m").reset_index(drop=True)
        == aws_billing_months.reset_index(drop=True)
    ).all()

    assert (
        gcp_usage_dates.dt.strftime("%Y%m").reset_index(drop=True)
        == gcp_invoice_months.reset_index(drop=True)
    ).all()


def test_required_synthetic_scenarios_exist(
    billing_data: tuple[pd.DataFrame, pd.DataFrame],
) -> None:
    aws, gcp = billing_data

    assert aws.duplicated().sum() >= 1
    assert gcp.duplicated().sum() >= 1

    invalid_aws = aws[
        (aws["line_item_line_item_type"] == "Usage")
        & (aws["line_item_unblended_cost"] < 0)
    ]

    invalid_gcp = gcp[
        (gcp["cost_type"] == "regular")
        & (gcp["cost"] < 0)
    ]

    assert len(invalid_aws) == 1
    assert len(invalid_gcp) == 1

    assert aws["is_deliberate_anomaly"].astype(bool).any()
    assert gcp["is_deliberate_anomaly"].astype(bool).any()

    assert {"Usage", "Credit", "Refund"}.issubset(
        set(aws["line_item_line_item_type"])
    )

    assert "adjustment" in set(gcp["cost_type"])


def test_provider_schemas_and_json_fields_are_valid(
    billing_data: tuple[pd.DataFrame, pd.DataFrame],
) -> None:
    aws, gcp = billing_data

    assert set(aws.columns) != set(gcp.columns)

    assert {
        "line_item_unblended_cost",
        "product_product_name",
        "resource_tags",
    }.issubset(aws.columns)

    assert {
        "cost",
        "service_description",
        "credits",
        "labels",
    }.issubset(gcp.columns)

    for value in aws["resource_tags"]:
        parsed = json.loads(value)
        assert isinstance(parsed, dict)

    for value in gcp["labels"]:
        parsed = json.loads(value)
        assert isinstance(parsed, dict)

    for value in gcp["credits"]:
        parsed = json.loads(value)
        assert isinstance(parsed, list)