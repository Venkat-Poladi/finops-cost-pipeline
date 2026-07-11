"""
Generate realistic synthetic AWS and GCP billing data for the FinOps portfolio.

The providers intentionally use different raw schemas so the project can
show provider-specific ingestion followed by FOCUS-aligned normalization.

Outputs:
    data/sample/aws_billing_sample.csv
    data/sample/gcp_billing_sample.csv

Design guarantees:
    - 90 days of deterministic data
    - multiple AWS accounts and GCP projects
    - multiple services, teams, applications, and environments
    - tagged, untagged, and shared-platform costs
    - credits and refunds
    - anomalies that exceed 30% AND $100
    - exact duplicates and invalid negative regular-usage rows
    - billing periods derived from each row's usage date
"""

from __future__ import annotations

import json
import random
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd


SEED = 42
RNG = random.Random(SEED)

START_DATE = date(2026, 4, 1)
NUMBER_OF_DAYS = 90
END_DATE = START_DATE + timedelta(days=NUMBER_OF_DAYS - 1)

OUTPUT_FOLDER = Path(__file__).resolve().parent
AWS_OUTPUT_FILE = OUTPUT_FOLDER / "aws_billing_sample.csv"
GCP_OUTPUT_FILE = OUTPUT_FOLDER / "gcp_billing_sample.csv"

ANOMALY_PERCENT_THRESHOLD = 0.30
ANOMALY_ABSOLUTE_THRESHOLD = 100.00

AWS_PAYER_ACCOUNT_ID = "999999999999"
GCP_BILLING_ACCOUNT_ID = "000000-111111-222222"

AWS_ACCOUNTS: list[dict[str, Any]] = [
    {
        "linked_account_id": "111111111111",
        "account_name": "production-account",
        "team": "Payments",
        "application": "Checkout",
        "environment": "production",
        "cost_center": "CC-1001",
        "cost_multiplier": 1.80,
    },
    {
        "linked_account_id": "222222222222",
        "account_name": "development-account",
        "team": "Data",
        "application": "Analytics",
        "environment": "development",
        "cost_center": "CC-2001",
        "cost_multiplier": 0.70,
    },
]

AWS_SERVICES: list[dict[str, Any]] = [
    {
        "service": "Amazon Elastic Compute Cloud - Compute",
        "usage_type": "BoxUsage:m5.large",
        "operation": "RunInstances",
        "usage_unit": "Hrs",
        "base_daily_usage": 1_200.0,
        "public_rate": 0.096,
        "discount_rate": 0.084,
        "resource_prefix": "i",
        "resource_count": 2,
        "shared": False,
    },
    {
        "service": "Amazon Simple Storage Service",
        "usage_type": "TimedStorage-ByteHrs",
        "operation": "StandardStorage",
        "usage_unit": "GB-Mo",
        "base_daily_usage": 260.0,
        "public_rate": 0.023,
        "discount_rate": 0.0215,
        "resource_prefix": "bucket",
        "resource_count": 2,
        "shared": False,
    },
    {
        "service": "Amazon Relational Database Service",
        "usage_type": "InstanceUsage:db.m5.large",
        "operation": "CreateDBInstance",
        "usage_unit": "Hrs",
        "base_daily_usage": 240.0,
        "public_rate": 0.192,
        "discount_rate": 0.170,
        "resource_prefix": "db",
        "resource_count": 2,
        "shared": False,
    },
    {
        "service": "AWS Lambda",
        "usage_type": "Lambda-GB-Second",
        "operation": "Invoke",
        "usage_unit": "GB-Seconds",
        "base_daily_usage": 5_000_000.0,
        "public_rate": 0.0000166667,
        "discount_rate": 0.0000155,
        "resource_prefix": "function",
        "resource_count": 2,
        "shared": False,
    },
    {
        "service": "AmazonCloudWatch",
        "usage_type": "DataProcessing-Bytes",
        "operation": "PutLogEvents",
        "usage_unit": "GB",
        "base_daily_usage": 250.0,
        "public_rate": 0.50,
        "discount_rate": 0.46,
        "resource_prefix": "log-group",
        "resource_count": 2,
        "shared": True,
    },
]

GCP_PROJECTS: list[dict[str, Any]] = [
    {
        "project_id": "finops-prod-1001",
        "project_name": "customer-platform-prod",
        "team": "Commerce",
        "application": "Storefront",
        "environment": "production",
        "cost_center": "CC-3001",
        "cost_multiplier": 2.00,
    },
    {
        "project_id": "finops-data-2001",
        "project_name": "analytics-development",
        "team": "Data",
        "application": "Lakehouse",
        "environment": "development",
        "cost_center": "CC-4001",
        "cost_multiplier": 0.90,
    },
]

GCP_SERVICES: list[dict[str, Any]] = [
    {
        "service_description": "Compute Engine",
        "sku_description": "N2 Instance Core running in Americas",
        "usage_unit": "vCPU-hours",
        "base_daily_usage": 1_500.0,
        "list_rate": 0.031611,
        "contract_rate": 0.028500,
        "resource_prefix": "instance",
        "resource_count": 2,
        "shared": False,
        "credit_type": "COMMITTED_USAGE_DISCOUNT",
        "credit_rate": 0.10,
    },
    {
        "service_description": "BigQuery",
        "sku_description": "Analysis in US",
        "usage_unit": "TiBy",
        "base_daily_usage": 12.0,
        "list_rate": 6.25,
        "contract_rate": 6.25,
        "resource_prefix": "bq-job",
        "resource_count": 2,
        "shared": False,
        "credit_type": "PROMOTION",
        "credit_rate": 0.05,
    },
    {
        "service_description": "Cloud Storage",
        "sku_description": "Standard Storage US Multi-region",
        "usage_unit": "GiBy-month",
        "base_daily_usage": 320.0,
        "list_rate": 0.026,
        "contract_rate": 0.024,
        "resource_prefix": "bucket",
        "resource_count": 2,
        "shared": False,
        "credit_type": None,
        "credit_rate": 0.0,
    },
    {
        "service_description": "Cloud SQL",
        "sku_description": "Cloud SQL for PostgreSQL: Regional vCPU",
        "usage_unit": "vCPU-hours",
        "base_daily_usage": 420.0,
        "list_rate": 0.0826,
        "contract_rate": 0.0740,
        "resource_prefix": "cloudsql",
        "resource_count": 2,
        "shared": False,
        "credit_type": "COMMITTED_USAGE_DISCOUNT",
        "credit_rate": 0.08,
    },
    {
        "service_description": "Cloud Logging",
        "sku_description": "Log Storage",
        "usage_unit": "GiBy",
        "base_daily_usage": 300.0,
        "list_rate": 0.50,
        "contract_rate": 0.46,
        "resource_prefix": "log-sink",
        "resource_count": 2,
        "shared": True,
        "credit_type": None,
        "credit_rate": 0.0,
    },
]


def month_start(value: date) -> date:
    return value.replace(day=1)


def next_month_start(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def utc_day_bounds(value: date) -> tuple[str, str]:
    start = datetime.combine(value, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()


def json_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def money(value: float) -> float:
    return round(float(value), 4)


def create_aws_tags(
    *,
    team: str,
    application: str,
    environment: str,
    cost_center: str,
    make_untagged: bool,
) -> str:
    if make_untagged:
        return json_text({})
    return json_text(
        {
            "team": team,
            "application": application,
            "environment": environment,
            "cost_center": cost_center,
        }
    )


def create_gcp_labels(
    *,
    team: str,
    application: str,
    environment: str,
    cost_center: str,
    make_untagged: bool,
) -> str:
    if make_untagged:
        return json_text({})
    return json_text(
        {
            "team": team.lower(),
            "application": application.lower(),
            "environment": environment.lower(),
            "cost_center": cost_center.lower(),
        }
    )


def generate_aws_usage_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for day_number in range(NUMBER_OF_DAYS):
        usage_date = START_DATE + timedelta(days=day_number)
        usage_start, usage_end = utc_day_bounds(usage_date)
        billing_start = month_start(usage_date)
        billing_end = next_month_start(usage_date)

        for account in AWS_ACCOUNTS:
            for service_number, service in enumerate(AWS_SERVICES, start=1):
                for resource_number in range(1, service["resource_count"] + 1):
                    usage_variation = RNG.uniform(0.90, 1.10)
                    usage_quantity = (
                        service["base_daily_usage"]
                        * account["cost_multiplier"]
                        * usage_variation
                        / service["resource_count"]
                    )

                    is_anomaly = (
                        day_number == 74
                        and account["environment"] == "production"
                        and service["service"]
                        == "Amazon Elastic Compute Cloud - Compute"
                    )
                    if is_anomaly:
                        usage_quantity *= 4.0

                    public_cost = usage_quantity * service["public_rate"]
                    unblended_cost = usage_quantity * service["discount_rate"]

                    if service["shared"]:
                        team = "Platform"
                        application = "Shared-Observability"
                        cost_center = "CC-SHARED"
                    else:
                        team = account["team"]
                        application = account["application"]
                        cost_center = account["cost_center"]

                    make_untagged = RNG.random() < 0.08
                    resource_id = (
                        f"{service['resource_prefix']}-"
                        f"{account['linked_account_id'][-4:]}-"
                        f"{service_number:02d}-"
                        f"{resource_number:02d}"
                    )
                    source_record_id = (
                        f"aws-{usage_date.isoformat()}-"
                        f"{account['linked_account_id']}-"
                        f"{service_number:02d}-{resource_number:02d}"
                    )

                    rows.append(
                        {
                            "source_record_id": source_record_id,
                            "bill_billing_period_start_date": billing_start.isoformat(),
                            "bill_billing_period_end_date": billing_end.isoformat(),
                            "line_item_usage_start_date": usage_start,
                            "line_item_usage_end_date": usage_end,
                            "bill_payer_account_id": AWS_PAYER_ACCOUNT_ID,
                            "line_item_usage_account_id": account[
                                "linked_account_id"
                            ],
                            "account_name": account["account_name"],
                            "product_product_name": service["service"],
                            "line_item_usage_type": service["usage_type"],
                            "line_item_operation": service["operation"],
                            "product_region": "us-east-1",
                            "line_item_resource_id": resource_id,
                            "line_item_usage_amount": round(usage_quantity, 4),
                            "pricing_unit": service["usage_unit"],
                            "pricing_public_on_demand_rate": service["public_rate"],
                            "pricing_public_on_demand_cost": money(public_cost),
                            "line_item_unblended_rate": service["discount_rate"],
                            "line_item_unblended_cost": money(unblended_cost),
                            "line_item_line_item_type": "Usage",
                            "pricing_term": "OnDemand",
                            "currency": "USD",
                            "team": None if make_untagged else team,
                            "application": None if make_untagged else application,
                            "environment": (
                                None
                                if make_untagged
                                else account["environment"]
                            ),
                            "cost_center": None if make_untagged else cost_center,
                            "resource_tags": create_aws_tags(
                                team=team,
                                application=application,
                                environment=account["environment"],
                                cost_center=cost_center,
                                make_untagged=make_untagged,
                            ),
                            "is_deliberate_anomaly": is_anomaly,
                            "data_quality_scenario": (
                                "untagged" if make_untagged else "valid"
                            ),
                        }
                    )

    return rows


def aws_adjustment_row(
    *,
    usage_date: date,
    linked_account_id: str,
    account_name: str,
    service: str,
    amount: float,
    line_item_type: str,
    team: str,
    application: str,
    environment: str,
    cost_center: str,
) -> dict[str, Any]:
    usage_start, usage_end = utc_day_bounds(usage_date)
    billing_start = month_start(usage_date)
    billing_end = next_month_start(usage_date)

    return {
        "source_record_id": (
            f"aws-adjustment-{line_item_type.lower()}-"
            f"{usage_date.isoformat()}-{linked_account_id}"
        ),
        "bill_billing_period_start_date": billing_start.isoformat(),
        "bill_billing_period_end_date": billing_end.isoformat(),
        "line_item_usage_start_date": usage_start,
        "line_item_usage_end_date": usage_end,
        "bill_payer_account_id": AWS_PAYER_ACCOUNT_ID,
        "line_item_usage_account_id": linked_account_id,
        "account_name": account_name,
        "product_product_name": service,
        "line_item_usage_type": line_item_type,
        "line_item_operation": "BillingAdjustment",
        "product_region": "global",
        "line_item_resource_id": "not-applicable",
        "line_item_usage_amount": 0.0,
        "pricing_unit": None,
        "pricing_public_on_demand_rate": 0.0,
        "pricing_public_on_demand_cost": 0.0,
        "line_item_unblended_rate": 0.0,
        "line_item_unblended_cost": money(amount),
        "line_item_line_item_type": line_item_type,
        "pricing_term": "Adjustment",
        "currency": "USD",
        "team": team,
        "application": application,
        "environment": environment,
        "cost_center": cost_center,
        "resource_tags": json_text(
            {
                "team": team,
                "application": application,
                "environment": environment,
                "cost_center": cost_center,
            }
        ),
        "is_deliberate_anomaly": False,
        "data_quality_scenario": "valid",
    }


def add_aws_adjustments(rows: list[dict[str, Any]]) -> None:
    rows.append(
        aws_adjustment_row(
            usage_date=date(2026, 6, 29),
            linked_account_id="111111111111",
            account_name="production-account",
            service="AWS Promotional Credits",
            amount=-5_000.00,
            line_item_type="Credit",
            team="Finance",
            application="Shared",
            environment="production",
            cost_center="CC-CORPORATE",
        )
    )
    rows.append(
        aws_adjustment_row(
            usage_date=date(2026, 5, 20),
            linked_account_id="222222222222",
            account_name="development-account",
            service="Amazon Relational Database Service",
            amount=-750.00,
            line_item_type="Refund",
            team="Data",
            application="Analytics",
            environment="development",
            cost_center="CC-2001",
        )
    )


def add_aws_data_quality_failures(rows: list[dict[str, Any]]) -> None:
    # Exact physical duplicate: every column, including source_record_id, matches.
    rows.append(rows[10].copy())

    invalid_row = rows[20].copy()
    invalid_row["source_record_id"] = "aws-invalid-negative-usage-cost"
    invalid_row["line_item_unblended_cost"] = -250.00
    invalid_row["line_item_line_item_type"] = "Usage"
    invalid_row["data_quality_scenario"] = "negative_usage_cost"
    rows.append(invalid_row)


def generate_aws_billing_data() -> pd.DataFrame:
    rows = generate_aws_usage_rows()
    add_aws_adjustments(rows)
    add_aws_data_quality_failures(rows)
    return pd.DataFrame(rows)


def gcp_credit_json(credit_type: str | None, amount: float) -> str:
    if credit_type is None or amount == 0:
        return json_text([])
    return json_text(
        [
            {
                "name": credit_type.replace("_", " ").title(),
                "amount": money(amount),
                "type": credit_type,
            }
        ]
    )


def generate_gcp_usage_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for day_number in range(NUMBER_OF_DAYS):
        usage_date = START_DATE + timedelta(days=day_number)
        usage_start, usage_end = utc_day_bounds(usage_date)
        invoice_month = month_start(usage_date).strftime("%Y%m")

        for project in GCP_PROJECTS:
            for service_number, service in enumerate(GCP_SERVICES, start=1):
                for resource_number in range(1, service["resource_count"] + 1):
                    usage_variation = RNG.uniform(0.90, 1.10)
                    usage_amount = (
                        service["base_daily_usage"]
                        * project["cost_multiplier"]
                        * usage_variation
                        / service["resource_count"]
                    )

                    is_anomaly = (
                        day_number == 79
                        and project["environment"] == "production"
                        and service["service_description"] == "Compute Engine"
                    )
                    if is_anomaly:
                        usage_amount *= 4.0

                    list_cost = usage_amount * service["list_rate"]
                    cost = usage_amount * service["contract_rate"]
                    credit_amount = -(cost * service["credit_rate"])

                    if service["shared"]:
                        team = "Platform"
                        application = "Shared-Logging"
                        cost_center = "CC-SHARED"
                    else:
                        team = project["team"]
                        application = project["application"]
                        cost_center = project["cost_center"]

                    make_untagged = RNG.random() < 0.08
                    resource_name = (
                        f"{service['resource_prefix']}-"
                        f"{project['project_id'][-4:]}-"
                        f"{service_number:02d}-"
                        f"{resource_number:02d}"
                    )
                    source_record_id = (
                        f"gcp-{usage_date.isoformat()}-{project['project_id']}-"
                        f"{service_number:02d}-{resource_number:02d}"
                    )

                    rows.append(
                        {
                            "source_record_id": source_record_id,
                            "billing_account_id": GCP_BILLING_ACCOUNT_ID,
                            "invoice_month": invoice_month,
                            "usage_start_time": usage_start,
                            "usage_end_time": usage_end,
                            "project_id": project["project_id"],
                            "project_name": project["project_name"],
                            "service_description": service[
                                "service_description"
                            ],
                            "sku_description": service["sku_description"],
                            "resource_name": resource_name,
                            "location": "us-central1",
                            "usage_amount": round(usage_amount, 4),
                            "usage_unit": service["usage_unit"],
                            "list_cost": money(list_cost),
                            "cost": money(cost),
                            "currency": "USD",
                            "currency_conversion_rate": 1.0,
                            "credits": gcp_credit_json(
                                service["credit_type"], credit_amount
                            ),
                            "cost_type": "regular",
                            "labels": create_gcp_labels(
                                team=team,
                                application=application,
                                environment=project["environment"],
                                cost_center=cost_center,
                                make_untagged=make_untagged,
                            ),
                            "is_deliberate_anomaly": is_anomaly,
                            "data_quality_scenario": (
                                "untagged" if make_untagged else "valid"
                            ),
                        }
                    )

    return rows


def gcp_adjustment_row(
    *,
    usage_date: date,
    project_id: str,
    project_name: str,
    service_description: str,
    sku_description: str,
    amount: float,
    cost_type: str,
    labels: dict[str, str],
) -> dict[str, Any]:
    usage_start, usage_end = utc_day_bounds(usage_date)

    return {
        "source_record_id": (
            f"gcp-adjustment-{cost_type}-{usage_date.isoformat()}-{project_id}"
        ),
        "billing_account_id": GCP_BILLING_ACCOUNT_ID,
        "invoice_month": month_start(usage_date).strftime("%Y%m"),
        "usage_start_time": usage_start,
        "usage_end_time": usage_end,
        "project_id": project_id,
        "project_name": project_name,
        "service_description": service_description,
        "sku_description": sku_description,
        "resource_name": "not-applicable",
        "location": "global",
        "usage_amount": 0.0,
        "usage_unit": None,
        "list_cost": 0.0,
        "cost": money(amount),
        "currency": "USD",
        "currency_conversion_rate": 1.0,
        "credits": json_text([]),
        "cost_type": cost_type,
        "labels": json_text(labels),
        "is_deliberate_anomaly": False,
        "data_quality_scenario": "valid",
    }


def add_gcp_adjustments(rows: list[dict[str, Any]]) -> None:
    promotional_credit = gcp_adjustment_row(
        usage_date=date(2026, 6, 29),
        project_id="finops-prod-1001",
        project_name="customer-platform-prod",
        service_description="Promotional Credits",
        sku_description="Free Trial Credit",
        amount=0.0,
        cost_type="regular",
        labels={
            "team": "finance",
            "application": "shared",
            "environment": "production",
            "cost_center": "cc-corporate",
        },
    )
    promotional_credit["credits"] = gcp_credit_json("PROMOTION", -4_500.00)
    rows.append(promotional_credit)

    rows.append(
        gcp_adjustment_row(
            usage_date=date(2026, 5, 18),
            project_id="finops-data-2001",
            project_name="analytics-development",
            service_description="Cloud SQL",
            sku_description="Billing Adjustment Refund",
            amount=-600.00,
            cost_type="adjustment",
            labels={
                "team": "data",
                "application": "lakehouse",
                "environment": "development",
                "cost_center": "cc-4001",
            },
        )
    )


def add_gcp_data_quality_failures(rows: list[dict[str, Any]]) -> None:
    # Exact physical duplicate: every column, including source_record_id, matches.
    rows.append(rows[15].copy())

    invalid_row = rows[25].copy()
    invalid_row["source_record_id"] = "gcp-invalid-negative-regular-cost"
    invalid_row["cost"] = -300.00
    invalid_row["cost_type"] = "regular"
    invalid_row["data_quality_scenario"] = "negative_regular_cost"
    rows.append(invalid_row)


def generate_gcp_billing_data() -> pd.DataFrame:
    rows = generate_gcp_usage_rows()
    add_gcp_adjustments(rows)
    add_gcp_data_quality_failures(rows)
    return pd.DataFrame(rows)


def parse_gcp_credit_total(value: str) -> float:
    credits = json.loads(value)
    return float(sum(item.get("amount", 0.0) for item in credits))


def validate_billing_period_alignment(
    aws_dataframe: pd.DataFrame,
    gcp_dataframe: pd.DataFrame,
) -> None:
    aws_usage_month = pd.to_datetime(
        aws_dataframe["line_item_usage_start_date"], utc=True
    ).dt.tz_convert(None).dt.to_period("M")
    aws_billing_month = pd.to_datetime(
        aws_dataframe["bill_billing_period_start_date"]
    ).dt.to_period("M")

    if not (aws_usage_month == aws_billing_month).all():
        raise AssertionError("AWS billing period does not match usage month.")

    gcp_usage_month = pd.to_datetime(
        gcp_dataframe["usage_start_time"], utc=True
    ).dt.strftime("%Y%m")

    if not (gcp_usage_month == gcp_dataframe["invoice_month"].astype(str)).all():
        raise AssertionError("GCP invoice_month does not match usage month.")


def validate_anomaly_thresholds(
    aws_dataframe: pd.DataFrame,
    gcp_dataframe: pd.DataFrame,
) -> None:
    def anomaly_passes(
        dataframe: pd.DataFrame,
        *,
        date_column: str,
        cost_column: str,
        grouping_columns: list[str],
    ) -> bool:
        data = dataframe.copy()
        data[date_column] = pd.to_datetime(data[date_column], utc=True)
        anomaly_rows = data[data["is_deliberate_anomaly"]].copy()

        for _, anomaly_row in anomaly_rows.iterrows():
            anomaly_date = anomaly_row[date_column]
            history = data[
                (data[date_column] >= anomaly_date - pd.Timedelta(days=7))
                & (data[date_column] < anomaly_date)
            ].copy()

            for column in grouping_columns:
                history = history[history[column] == anomaly_row[column]]

            if history.empty:
                continue

            baseline = float(history[cost_column].median())
            anomaly_cost = float(anomaly_row[cost_column])
            absolute_change = anomaly_cost - baseline
            percentage_change = (
                absolute_change / baseline if baseline != 0 else float("inf")
            )

            if (
                percentage_change >= ANOMALY_PERCENT_THRESHOLD
                and absolute_change >= ANOMALY_ABSOLUTE_THRESHOLD
            ):
                return True

        return False

    aws_ok = anomaly_passes(
        aws_dataframe,
        date_column="line_item_usage_start_date",
        cost_column="line_item_unblended_cost",
        grouping_columns=[
            "line_item_usage_account_id",
            "product_product_name",
            "line_item_resource_id",
        ],
    )
    gcp_ok = anomaly_passes(
        gcp_dataframe,
        date_column="usage_start_time",
        cost_column="cost",
        grouping_columns=[
            "project_id",
            "service_description",
            "resource_name",
        ],
    )

    if not aws_ok:
        raise AssertionError("AWS anomaly does not exceed 30% AND $100.")
    if not gcp_ok:
        raise AssertionError("GCP anomaly does not exceed 30% AND $100.")


def validate_deliberate_data_quality_cases(
    aws_dataframe: pd.DataFrame,
    gcp_dataframe: pd.DataFrame,
) -> None:
    if int(aws_dataframe.duplicated().sum()) < 1:
        raise AssertionError("Expected at least one exact AWS duplicate.")
    if int(gcp_dataframe.duplicated().sum()) < 1:
        raise AssertionError("Expected at least one exact GCP duplicate.")

    invalid_aws = aws_dataframe[
        (aws_dataframe["line_item_line_item_type"] == "Usage")
        & (aws_dataframe["line_item_unblended_cost"] < 0)
    ]
    if len(invalid_aws) != 1:
        raise AssertionError("Expected exactly one invalid negative AWS Usage row.")

    invalid_gcp = gcp_dataframe[
        (gcp_dataframe["cost_type"] == "regular")
        & (gcp_dataframe["cost"] < 0)
    ]
    if len(invalid_gcp) != 1:
        raise AssertionError(
            "Expected exactly one invalid negative GCP regular-cost row."
        )


def write_outputs(
    aws_dataframe: pd.DataFrame,
    gcp_dataframe: pd.DataFrame,
) -> None:
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
    aws_dataframe.to_csv(AWS_OUTPUT_FILE, index=False)
    gcp_dataframe.to_csv(GCP_OUTPUT_FILE, index=False)


def print_summary(
    aws_dataframe: pd.DataFrame,
    gcp_dataframe: pd.DataFrame,
) -> None:
    aws_usage_cost = aws_dataframe.loc[
        aws_dataframe["line_item_line_item_type"] == "Usage",
        "line_item_unblended_cost",
    ].sum()
    aws_adjustments = aws_dataframe.loc[
        aws_dataframe["line_item_line_item_type"].isin(["Credit", "Refund"]),
        "line_item_unblended_cost",
    ].sum()
    aws_net_cost = aws_dataframe["line_item_unblended_cost"].sum()

    gcp_credit_total = gcp_dataframe["credits"].map(parse_gcp_credit_total).sum()
    gcp_gross_cost = gcp_dataframe["cost"].sum()
    gcp_net_cost = gcp_gross_cost + gcp_credit_total

    print("\nSynthetic billing data created successfully")
    print(f"Date range: {START_DATE} through {END_DATE} ({NUMBER_OF_DAYS} days)")

    print("\nAWS")
    print(f"  File: {AWS_OUTPUT_FILE}")
    print(f"  Rows: {len(aws_dataframe):,}")
    print(f"  Gross Usage cost: ${aws_usage_cost:,.2f}")
    print(f"  Credits and refunds: ${aws_adjustments:,.2f}")
    print(f"  Net cost: ${aws_net_cost:,.2f}")
    print(f"  Exact duplicate rows: {int(aws_dataframe.duplicated().sum()):,}")
    print(
        "  Untagged rows: "
        f"{int((aws_dataframe['resource_tags'] == json_text({})).sum()):,}"
    )

    print("\nGCP")
    print(f"  File: {GCP_OUTPUT_FILE}")
    print(f"  Rows: {len(gcp_dataframe):,}")
    print(f"  Gross cost: ${gcp_gross_cost:,.2f}")
    print(f"  Credits: ${gcp_credit_total:,.2f}")
    print(f"  Net cost: ${gcp_net_cost:,.2f}")
    print(f"  Exact duplicate rows: {int(gcp_dataframe.duplicated().sum()):,}")
    print(
        "  Untagged rows: "
        f"{int((gcp_dataframe['labels'] == json_text({})).sum()):,}"
    )


def main() -> None:
    aws_dataframe = generate_aws_billing_data()
    gcp_dataframe = generate_gcp_billing_data()

    validate_billing_period_alignment(aws_dataframe, gcp_dataframe)
    validate_anomaly_thresholds(aws_dataframe, gcp_dataframe)
    validate_deliberate_data_quality_cases(aws_dataframe, gcp_dataframe)

    write_outputs(aws_dataframe, gcp_dataframe)
    print_summary(aws_dataframe, gcp_dataframe)


if __name__ == "__main__":
    main()