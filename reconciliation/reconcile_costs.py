"""Reconcile provider source billing totals to normalized FOCUS totals.

The reconciliation control proves that normalization preserved:
- row counts
- Usage, Credit, and Adjustment costs
- total net billed cost

Run from the project root:

    python -m reconciliation.reconcile_costs
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd


AWS_SOURCE_PATH = Path("data/sample/aws_billing_sample.csv")
GCP_SOURCE_PATH = Path("data/sample/gcp_billing_sample.csv")
NORMALIZED_PATH = Path("data/processed/focus_cost_usage.csv")
REPORT_PATH = Path("data/outputs/reconciliation_report.csv")

CATEGORIES = ("Usage", "Credit", "Adjustment")
TOLERANCE = Decimal("0.01")


def _to_decimal(value: Any) -> Decimal:
    """Convert CSV values to Decimal safely."""

    if value is None or pd.isna(value):
        return Decimal("0")

    text = str(value).strip()

    if not text:
        return Decimal("0")

    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Cannot convert value to Decimal: {value!r}") from exc


def _parse_credits(value: Any) -> list[dict[str, Any]]:
    """Parse GCP credits stored as JSON in the synthetic CSV."""

    if value is None or pd.isna(value):
        return []

    text = str(value).strip()

    if not text:
        return []

    parsed = json.loads(text)

    if not isinstance(parsed, list):
        raise ValueError("GCP credits must be a JSON list")

    return parsed


def _empty_summary(provider_name: str) -> dict[str, Any]:
    return {
        "provider_name": provider_name,
        "row_count": 0,
        "category_counts": {category: 0 for category in CATEGORIES},
        "category_costs": {
            category: Decimal("0") for category in CATEGORIES
        },
    }


def summarize_aws_source(path: Path | str) -> dict[str, Any]:
    """Summarize the AWS synthetic CUR-style source file."""

    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    summary = _empty_summary("AWS")
    summary["row_count"] = len(df)

    for row in df.to_dict(orient="records"):
        line_item_type = row["line_item_line_item_type"].strip()
        cost = _to_decimal(row["line_item_unblended_cost"])

        if line_item_type == "Credit":
            category = "Credit"
        elif line_item_type in {"Usage", "Refund"}:
            # FOCUS treats a usage-related refund as a Usage charge.
            category = "Usage"
        else:
            category = "Adjustment"

        summary["category_counts"][category] += 1
        summary["category_costs"][category] += cost

    return summary


def summarize_gcp_source(path: Path | str) -> dict[str, Any]:
    """Summarize the GCP synthetic billing-export source file."""

    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    summary = _empty_summary("GCP")
    summary["row_count"] = len(df)

    for row in df.to_dict(orient="records"):
        service_name = row["service_description"].strip()
        cost_type = row["cost_type"].strip().lower()
        cost = _to_decimal(row["cost"])

        credit_total = sum(
            (_to_decimal(item.get("amount", 0)) for item in _parse_credits(
                row["credits"]
            )),
            Decimal("0"),
        )
        billed_cost = cost + credit_total

        if cost_type == "adjustment":
            category = "Adjustment"
        elif service_name == "Promotional Credits":
            category = "Credit"
        else:
            category = "Usage"

        summary["category_counts"][category] += 1
        summary["category_costs"][category] += billed_cost

    return summary


def summarize_normalized(
    path: Path | str,
    provider_name: str,
) -> dict[str, Any]:
    """Summarize normalized FOCUS rows for one provider."""

    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    provider_df = df[df["provider_name"] == provider_name]

    summary = _empty_summary(provider_name)
    summary["row_count"] = len(provider_df)

    for row in provider_df.to_dict(orient="records"):
        category = row["charge_category"].strip()

        if category not in CATEGORIES:
            raise ValueError(
                f"Unsupported normalized charge category: {category!r}"
            )

        summary["category_counts"][category] += 1
        summary["category_costs"][category] += _to_decimal(
            row["billed_cost"]
        )

    return summary


def _combine_summaries(
    provider_name: str,
    summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Combine AWS and GCP summaries into a multi-cloud total."""

    combined = _empty_summary(provider_name)
    combined["row_count"] = sum(
        summary["row_count"] for summary in summaries
    )

    for category in CATEGORIES:
        combined["category_counts"][category] = sum(
            summary["category_counts"][category]
            for summary in summaries
        )
        combined["category_costs"][category] = sum(
            (
                summary["category_costs"][category]
                for summary in summaries
            ),
            Decimal("0"),
        )

    return combined


def _net_cost(summary: dict[str, Any]) -> Decimal:
    return sum(
        (summary["category_costs"][category] for category in CATEGORIES),
        Decimal("0"),
    )


def _report_row(
    source: dict[str, Any],
    normalized: dict[str, Any],
) -> dict[str, Any]:
    """Create one reconciliation result row."""

    row: dict[str, Any] = {
        "provider_name": source["provider_name"],
        "source_row_count": source["row_count"],
        "normalized_row_count": normalized["row_count"],
        "row_count_variance": (
            normalized["row_count"] - source["row_count"]
        ),
    }

    passed = row["row_count_variance"] == 0

    for category in CATEGORIES:
        key = category.lower()
        source_count = source["category_counts"][category]
        normalized_count = normalized["category_counts"][category]
        source_cost = source["category_costs"][category]
        normalized_cost = normalized["category_costs"][category]
        cost_variance = normalized_cost - source_cost

        row[f"source_{key}_rows"] = source_count
        row[f"normalized_{key}_rows"] = normalized_count
        row[f"{key}_row_variance"] = normalized_count - source_count
        row[f"source_{key}_cost"] = float(source_cost)
        row[f"normalized_{key}_cost"] = float(normalized_cost)
        row[f"{key}_cost_variance"] = float(cost_variance)

        if normalized_count != source_count:
            passed = False

        if abs(cost_variance) > TOLERANCE:
            passed = False

    source_net = _net_cost(source)
    normalized_net = _net_cost(normalized)
    net_variance = normalized_net - source_net

    row["source_net_cost"] = float(source_net)
    row["normalized_net_cost"] = float(normalized_net)
    row["net_variance"] = float(net_variance)
    row["net_variance_pct"] = (
        float((net_variance / source_net) * Decimal("100"))
        if source_net != 0
        else None
    )

    if abs(net_variance) > TOLERANCE:
        passed = False

    row["status"] = "PASS" if passed else "FAIL"

    return row


def build_reconciliation_report(
    aws_source_path: Path | str = AWS_SOURCE_PATH,
    gcp_source_path: Path | str = GCP_SOURCE_PATH,
    normalized_path: Path | str = NORMALIZED_PATH,
) -> pd.DataFrame:
    """Build AWS, GCP, and combined reconciliation results."""

    aws_source = summarize_aws_source(aws_source_path)
    gcp_source = summarize_gcp_source(gcp_source_path)

    aws_normalized = summarize_normalized(normalized_path, "AWS")
    gcp_normalized = summarize_normalized(normalized_path, "GCP")

    all_source = _combine_summaries(
        "ALL",
        [aws_source, gcp_source],
    )
    all_normalized = _combine_summaries(
        "ALL",
        [aws_normalized, gcp_normalized],
    )

    rows = [
        _report_row(aws_source, aws_normalized),
        _report_row(gcp_source, gcp_normalized),
        _report_row(all_source, all_normalized),
    ]

    return pd.DataFrame(rows)


def run_reconciliation(
    aws_source_path: Path | str = AWS_SOURCE_PATH,
    gcp_source_path: Path | str = GCP_SOURCE_PATH,
    normalized_path: Path | str = NORMALIZED_PATH,
    report_path: Path | str = REPORT_PATH,
) -> pd.DataFrame:
    """Run reconciliation, save the report, and print a summary."""

    report = build_reconciliation_report(
        aws_source_path=aws_source_path,
        gcp_source_path=gcp_source_path,
        normalized_path=normalized_path,
    )

    output_path = Path(report_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(output_path, index=False, float_format="%.4f")

    print(report[
        [
            "provider_name",
            "source_row_count",
            "normalized_row_count",
            "source_net_cost",
            "normalized_net_cost",
            "net_variance",
            "status",
        ]
    ].to_string(index=False))

    failed = report[report["status"] == "FAIL"]

    print(f"\nReport: {output_path.as_posix()}")

    if failed.empty:
        print("Reconciliation passed for AWS, GCP, and combined totals.")
    else:
        print(
            "Reconciliation failed for: "
            + ", ".join(failed["provider_name"].tolist())
        )

    return report


if __name__ == "__main__":
    run_reconciliation()
