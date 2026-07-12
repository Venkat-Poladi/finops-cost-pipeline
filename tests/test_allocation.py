"""Tests for proportional cloud-cost allocation."""

from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from allocation.allocate_costs import (
    allocate_dataframe,
    run_allocation,
)
from allocation.allocation_rules import AllocationRules


@pytest.fixture
def rules() -> AllocationRules:
    return AllocationRules.from_dict(
        {
            "primary_group_columns": [
                "provider_name",
                "billing_period_start",
                "sub_account_id",
            ],
            "fallback_group_columns": [
                "provider_name",
                "billing_period_start",
            ],
            "target_columns": [
                "application",
                "environment",
                "cost_center",
                "owner",
            ],
            "driver_charge_categories": ["Usage"],
            "driver_minimum_cost": 0,
            "cost_precision": 4,
            "unallocated_values": {
                "application": "Unallocated",
                "environment": "unknown",
                "cost_center": "UNALLOCATED",
                "owner": "Unassigned",
            },
        }
    )


def _row(
    record_id: str,
    billed_cost: str,
    *,
    status: str,
    application: str = "",
    environment: str = "",
    cost_center: str = "",
    owner: str = "",
    provider: str = "AWS",
    sub_account: str = "acct-1",
    period: str = "2026-04-01T00:00:00+00:00",
    charge_category: str = "Usage",
) -> dict[str, str]:
    return {
        "record_id": record_id,
        "provider_name": provider,
        "sub_account_id": sub_account,
        "billing_period_start": period,
        "charge_category": charge_category,
        "billed_cost": billed_cost,
        "effective_cost": billed_cost,
        "list_cost": billed_cost,
        "consumed_quantity": "10.0000",
        "allocation_status": status,
        "application": application,
        "environment": environment,
        "cost_center": cost_center,
        "owner": owner,
    }


def test_direct_cost_remains_with_source_target(rules):
    source = pd.DataFrame(
        [
            _row(
                "direct-1",
                "100.00",
                status="Allocated",
                application="Checkout",
                environment="production",
                cost_center="CC-1001",
                owner="Payments",
            )
        ]
    )

    result = allocate_dataframe(source, rules)

    assert len(result) == 1
    assert result.iloc[0]["allocation_method"] == "Direct"
    assert result.iloc[0]["application"] == "Checkout"
    assert Decimal(result.iloc[0]["billed_cost"]) == Decimal("100.0000")


def test_shared_cost_uses_proportional_direct_spend(rules):
    source = pd.DataFrame(
        [
            _row(
                "direct-a",
                "100.00",
                status="Allocated",
                application="App-A",
                environment="production",
                cost_center="CC-A",
                owner="Team-A",
            ),
            _row(
                "direct-b",
                "300.00",
                status="Allocated",
                application="App-B",
                environment="production",
                cost_center="CC-B",
                owner="Team-B",
            ),
            _row("shared-1", "40.00", status="Shared"),
        ]
    )

    result = allocate_dataframe(source, rules)
    shared = result[
        result["record_id"] == "shared-1"
    ].sort_values("application")

    assert len(shared) == 2
    assert shared["application"].tolist() == ["App-A", "App-B"]
    assert [
        Decimal(value) for value in shared["billed_cost"]
    ] == [Decimal("10.0000"), Decimal("30.0000")]
    assert sum(
        Decimal(value) for value in shared["billed_cost"]
    ) == Decimal("40.0000")


def test_shared_negative_credit_preserves_sign_and_total(rules):
    source = pd.DataFrame(
        [
            _row(
                "direct-a",
                "100.00",
                status="Allocated",
                application="App-A",
                environment="production",
                cost_center="CC-A",
                owner="Team-A",
            ),
            _row(
                "direct-b",
                "300.00",
                status="Allocated",
                application="App-B",
                environment="production",
                cost_center="CC-B",
                owner="Team-B",
            ),
            _row(
                "shared-credit",
                "-20.00",
                status="Shared",
                charge_category="Credit",
            ),
        ]
    )

    result = allocate_dataframe(source, rules)
    shared = result[result["record_id"] == "shared-credit"]

    assert sum(
        Decimal(value) for value in shared["billed_cost"]
    ) == Decimal("-20.0000")
    assert all(
        Decimal(value) < 0 for value in shared["billed_cost"]
    )


def test_shared_cost_uses_provider_month_fallback(rules):
    source = pd.DataFrame(
        [
            _row(
                "driver",
                "100.00",
                status="Allocated",
                application="App-A",
                environment="production",
                cost_center="CC-A",
                owner="Team-A",
                sub_account="acct-1",
            ),
            _row(
                "shared",
                "25.00",
                status="Shared",
                sub_account="acct-2",
            ),
        ]
    )

    result = allocate_dataframe(source, rules)
    allocated_shared = result[result["record_id"] == "shared"].iloc[0]

    assert allocated_shared["application"] == "App-A"
    assert (
        allocated_shared["allocation_driver"]
        == "Direct spend fallback: provider + billing month"
    )


def test_row_without_target_remains_unallocated(rules):
    source = pd.DataFrame(
        [_row("untagged", "50.00", status="Unallocated")]
    )

    result = allocate_dataframe(source, rules)
    row = result.iloc[0]

    assert row["allocation_method"] == "Unallocated"
    assert row["application"] == "Unallocated"
    assert row["cost_center"] == "UNALLOCATED"
    assert row["allocation_status"] == "Unallocated"


def test_allocation_conserves_total_cost(rules):
    source = pd.DataFrame(
        [
            _row(
                "direct-a",
                "33.33",
                status="Allocated",
                application="App-A",
                environment="production",
                cost_center="CC-A",
                owner="Team-A",
            ),
            _row(
                "direct-b",
                "66.67",
                status="Allocated",
                application="App-B",
                environment="production",
                cost_center="CC-B",
                owner="Team-B",
            ),
            _row("shared", "10.01", status="Shared"),
            _row("unallocated", "5.55", status="Unallocated"),
        ]
    )

    result = allocate_dataframe(source, rules)

    source_total = sum(
        Decimal(value) for value in source["billed_cost"]
    )
    allocated_total = sum(
        Decimal(value) for value in result["billed_cost"]
    )

    assert allocated_total == source_total


def test_run_allocation_writes_both_outputs(tmp_path, rules):
    source_path = tmp_path / "focus.csv"
    rules_path = tmp_path / "rules.json"
    allocated_path = tmp_path / "processed" / "allocated.csv"
    summary_path = tmp_path / "outputs" / "summary.csv"

    source = pd.DataFrame(
        [
            _row(
                "direct",
                "100.00",
                status="Allocated",
                application="App-A",
                environment="production",
                cost_center="CC-A",
                owner="Team-A",
            ),
            _row("shared", "20.00", status="Shared"),
        ]
    )
    source.to_csv(source_path, index=False)

    rules_payload = {
        "primary_group_columns": list(rules.primary_group_columns),
        "fallback_group_columns": list(rules.fallback_group_columns),
        "target_columns": list(rules.target_columns),
        "driver_charge_categories": list(
            rules.driver_charge_categories
        ),
        "driver_minimum_cost": rules.driver_minimum_cost,
        "cost_precision": rules.cost_precision,
        "unallocated_values": {
            "application": rules.unallocated_application,
            "environment": rules.unallocated_environment,
            "cost_center": rules.unallocated_cost_center,
            "owner": rules.unallocated_owner,
        },
    }
    rules_path.write_text(
        __import__("json").dumps(rules_payload),
        encoding="utf-8",
    )

    allocated, summary = run_allocation(
        input_path=source_path,
        rules_path=rules_path,
        allocated_output_path=allocated_path,
        summary_output_path=summary_path,
    )

    assert allocated_path.exists()
    assert summary_path.exists()
    assert len(allocated) == 2
    assert not summary.empty
