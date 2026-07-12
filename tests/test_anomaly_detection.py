"""Tests for cloud-cost anomaly detection."""

from pathlib import Path
import json

import pandas as pd
import pytest

from anomaly.anomaly_rules import AnomalyRules
from anomaly.detect_anomalies import (
    detect_anomalies,
    run_anomaly_detection,
)


@pytest.fixture
def rules() -> AnomalyRules:
    return AnomalyRules.from_dict(
        {
            "cost_column": "effective_cost",
            "date_column": "charge_period_start",
            "group_columns": [
                "provider_name",
                "service_name",
                "sub_account_id",
                "application",
            ],
            "included_charge_categories": ["Usage"],
            "baseline_window_days": 7,
            "minimum_history_days": 3,
            "relative_threshold": 0.30,
            "absolute_threshold": 100.0,
            "critical_relative_threshold": 1.0,
            "critical_absolute_threshold": 500.0,
            "detect_decreases": False,
        }
    )


def _series(costs: list[float]) -> pd.DataFrame:
    rows = []

    for index, cost in enumerate(costs):
        rows.append(
            {
                "allocation_id": f"alloc-{index}",
                "record_id": f"record-{index}",
                "provider_name": "AWS",
                "service_name": "Amazon EC2",
                "sub_account_id": "acct-1",
                "application": "Checkout",
                "charge_period_start": (
                    pd.Timestamp("2026-04-01", tz="UTC")
                    + pd.Timedelta(days=index)
                ).isoformat(),
                "charge_category": "Usage",
                "effective_cost": str(cost),
            }
        )

    return pd.DataFrame(rows)


def test_detects_spike_when_both_thresholds_pass(rules):
    source = _series([100, 105, 95, 102, 98, 101, 100, 350])

    anomalies, _, metrics = detect_anomalies(source, rules)

    assert len(anomalies) == 1
    assert anomalies.iloc[0]["actual_cost"] == pytest.approx(350)
    assert anomalies.iloc[0]["absolute_variance"] > 100
    assert anomalies.iloc[0]["relative_variance"] > 0.30
    assert metrics["anomalies_detected"] == 1


def test_relative_change_alone_is_not_enough(rules):
    source = _series([10, 10, 10, 10, 10, 10, 10, 50])

    anomalies, _, _ = detect_anomalies(source, rules)

    assert anomalies.empty


def test_absolute_change_alone_is_not_enough(rules):
    source = _series(
        [1000, 1000, 1000, 1000, 1000, 1000, 1000, 1200]
    )

    anomalies, _, _ = detect_anomalies(source, rules)

    assert anomalies.empty


def test_negative_usage_and_duplicates_are_excluded(rules):
    source = _series([100, 100, 100, 100, 100, 100, 100, 350])

    duplicate = source.iloc[[0]].copy()
    invalid = source.iloc[[1]].copy()
    invalid["allocation_id"] = "invalid-negative"
    invalid["record_id"] = "invalid-negative"
    invalid["effective_cost"] = "-500"

    source = pd.concat([source, duplicate, invalid], ignore_index=True)

    anomalies, _, metrics = detect_anomalies(source, rules)

    assert len(anomalies) == 1
    assert metrics["duplicate_rows_removed"] == 1
    assert metrics["invalid_negative_rows_removed"] == 1


def test_requires_minimum_history(rules):
    source = _series([100, 500])

    anomalies, scored, _ = detect_anomalies(source, rules)

    assert anomalies.empty
    assert scored["baseline_cost"].isna().all()


def test_run_anomaly_detection_writes_outputs(tmp_path, rules):
    input_path = tmp_path / "allocated.csv"
    rules_path = tmp_path / "rules.json"
    report_path = tmp_path / "outputs" / "anomalies.csv"
    daily_path = tmp_path / "outputs" / "daily.csv"

    _series([100, 100, 100, 100, 100, 100, 100, 350]).to_csv(
        input_path,
        index=False,
    )

    rules_payload = {
        "cost_column": rules.cost_column,
        "date_column": rules.date_column,
        "group_columns": list(rules.group_columns),
        "included_charge_categories": list(
            rules.included_charge_categories
        ),
        "baseline_window_days": rules.baseline_window_days,
        "minimum_history_days": rules.minimum_history_days,
        "relative_threshold": rules.relative_threshold,
        "absolute_threshold": rules.absolute_threshold,
        "critical_relative_threshold": (
            rules.critical_relative_threshold
        ),
        "critical_absolute_threshold": (
            rules.critical_absolute_threshold
        ),
        "detect_decreases": rules.detect_decreases,
    }
    rules_path.write_text(
        json.dumps(rules_payload),
        encoding="utf-8",
    )

    anomalies, scored = run_anomaly_detection(
        input_path=input_path,
        rules_path=rules_path,
        report_path=report_path,
        daily_series_path=daily_path,
    )

    assert report_path.exists()
    assert daily_path.exists()
    assert len(anomalies) == 1
    assert not scored.empty
