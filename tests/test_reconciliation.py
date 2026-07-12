"""Tests for source-to-FOCUS cost reconciliation."""

from pathlib import Path

import pandas as pd
import pytest

from reconciliation.reconcile_costs import (
    build_reconciliation_report,
    run_reconciliation,
    summarize_gcp_source,
)


def _write_fixture_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    aws_path = tmp_path / "aws.csv"
    gcp_path = tmp_path / "gcp.csv"
    normalized_path = tmp_path / "focus.csv"

    pd.DataFrame(
        [
            {
                "line_item_line_item_type": "Usage",
                "line_item_unblended_cost": "100.00",
            },
            {
                "line_item_line_item_type": "Credit",
                "line_item_unblended_cost": "-10.00",
            },
            {
                "line_item_line_item_type": "Refund",
                "line_item_unblended_cost": "-5.00",
            },
        ]
    ).to_csv(aws_path, index=False)

    pd.DataFrame(
        [
            {
                "service_description": "Compute Engine",
                "cost_type": "regular",
                "cost": "50.00",
                "credits": (
                    '[{"amount":-5.00,"name":"CUD",'
                    '"type":"COMMITTED_USAGE_DISCOUNT"}]'
                ),
            },
            {
                "service_description": "Promotional Credits",
                "cost_type": "regular",
                "cost": "0.00",
                "credits": (
                    '[{"amount":-20.00,"name":"Promotion",'
                    '"type":"PROMOTION"}]'
                ),
            },
            {
                "service_description": "Cloud SQL",
                "cost_type": "adjustment",
                "cost": "-3.00",
                "credits": "[]",
            },
        ]
    ).to_csv(gcp_path, index=False)

    pd.DataFrame(
        [
            {
                "provider_name": "AWS",
                "charge_category": "Usage",
                "billed_cost": "100.00",
            },
            {
                "provider_name": "AWS",
                "charge_category": "Credit",
                "billed_cost": "-10.00",
            },
            {
                "provider_name": "AWS",
                "charge_category": "Usage",
                "billed_cost": "-5.00",
            },
            {
                "provider_name": "GCP",
                "charge_category": "Usage",
                "billed_cost": "45.00",
            },
            {
                "provider_name": "GCP",
                "charge_category": "Credit",
                "billed_cost": "-20.00",
            },
            {
                "provider_name": "GCP",
                "charge_category": "Adjustment",
                "billed_cost": "-3.00",
            },
        ]
    ).to_csv(normalized_path, index=False)

    return aws_path, gcp_path, normalized_path


def test_reconciliation_passes_when_totals_match(tmp_path):
    aws_path, gcp_path, normalized_path = _write_fixture_files(tmp_path)

    report = build_reconciliation_report(
        aws_source_path=aws_path,
        gcp_source_path=gcp_path,
        normalized_path=normalized_path,
    )

    assert report["provider_name"].tolist() == ["AWS", "GCP", "ALL"]
    assert report["status"].tolist() == ["PASS", "PASS", "PASS"]
    assert report.loc[report["provider_name"] == "ALL", "net_variance"].item() == 0


def test_reconciliation_detects_normalized_variance(tmp_path):
    aws_path, gcp_path, normalized_path = _write_fixture_files(tmp_path)

    normalized = pd.read_csv(normalized_path)
    normalized.loc[0, "billed_cost"] = 99.00
    normalized.to_csv(normalized_path, index=False)

    report = build_reconciliation_report(
        aws_source_path=aws_path,
        gcp_source_path=gcp_path,
        normalized_path=normalized_path,
    )

    aws_result = report[report["provider_name"] == "AWS"].iloc[0]

    assert aws_result["status"] == "FAIL"
    assert aws_result["net_variance"] == pytest.approx(-1.0)


def test_gcp_usage_credits_reduce_usage_billed_cost(tmp_path):
    _, gcp_path, _ = _write_fixture_files(tmp_path)

    summary = summarize_gcp_source(gcp_path)

    assert float(summary["category_costs"]["Usage"]) == pytest.approx(45.0)
    assert float(summary["category_costs"]["Credit"]) == pytest.approx(-20.0)
    assert float(summary["category_costs"]["Adjustment"]) == pytest.approx(-3.0)


def test_run_reconciliation_writes_report(tmp_path):
    aws_path, gcp_path, normalized_path = _write_fixture_files(tmp_path)
    report_path = tmp_path / "outputs" / "reconciliation_report.csv"

    report = run_reconciliation(
        aws_source_path=aws_path,
        gcp_source_path=gcp_path,
        normalized_path=normalized_path,
        report_path=report_path,
    )

    assert report_path.exists()
    assert len(report) == 3
    assert set(report["status"]) == {"PASS"}
