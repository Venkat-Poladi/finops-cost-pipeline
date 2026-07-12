"""Detect daily cloud-cost anomalies using a trailing median baseline.

Run from the project root:

    python -m anomaly.detect_anomalies
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from anomaly.anomaly_rules import AnomalyRules, load_anomaly_rules


INPUT_PATH = Path("data/processed/allocated_cost_usage.csv")
REPORT_PATH = Path("data/outputs/anomaly_report.csv")
DAILY_SERIES_PATH = Path("data/outputs/anomaly_daily_series.csv")


def _required_columns(rules: AnomalyRules) -> set[str]:
    return {
        rules.date_column,
        rules.cost_column,
        "record_id",
        "charge_category",
        *rules.group_columns,
    }


def prepare_anomaly_input(
    dataframe: pd.DataFrame,
    rules: AnomalyRules,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Clean allocation data before anomaly analysis."""

    missing = _required_columns(rules) - set(dataframe.columns)
    if missing:
        raise ValueError(
            "Anomaly input missing required columns: "
            + ", ".join(sorted(missing))
        )

    cleaned = dataframe.copy()
    input_rows = len(cleaned)

    dedupe_column = (
        "allocation_id"
        if "allocation_id" in cleaned.columns
        else "record_id"
    )
    duplicate_mask = cleaned.duplicated(
        subset=[dedupe_column],
        keep="first",
    )
    duplicate_rows_removed = int(duplicate_mask.sum())
    cleaned = cleaned.loc[~duplicate_mask].copy()

    cleaned[rules.cost_column] = pd.to_numeric(
        cleaned[rules.cost_column],
        errors="raise",
    )

    category_mask = cleaned["charge_category"].isin(
        rules.included_charge_categories
    )
    excluded_category_rows = int((~category_mask).sum())
    cleaned = cleaned.loc[category_mask].copy()

    invalid_negative_usage = (
        cleaned["charge_category"].eq("Usage")
        & cleaned[rules.cost_column].lt(0)
    )
    invalid_negative_rows_removed = int(
        invalid_negative_usage.sum()
    )
    cleaned = cleaned.loc[~invalid_negative_usage].copy()

    cleaned[rules.date_column] = pd.to_datetime(
        cleaned[rules.date_column],
        utc=True,
        errors="raise",
    ).dt.floor("D")

    for column in rules.group_columns:
        cleaned[column] = (
            cleaned[column]
            .fillna("Unallocated")
            .astype(str)
            .str.strip()
            .replace("", "Unallocated")
        )

    metrics = {
        "input_rows": input_rows,
        "duplicate_rows_removed": duplicate_rows_removed,
        "excluded_category_rows": excluded_category_rows,
        "invalid_negative_rows_removed": (
            invalid_negative_rows_removed
        ),
        "analysis_rows": len(cleaned),
    }

    return cleaned, metrics


def build_daily_series(
    dataframe: pd.DataFrame,
    rules: AnomalyRules,
) -> pd.DataFrame:
    """Aggregate cleaned rows into daily analysis series."""

    group_columns = [*rules.group_columns, rules.date_column]

    return (
        dataframe.groupby(
            group_columns,
            dropna=False,
            as_index=False,
        )
        .agg(
            actual_cost=(rules.cost_column, "sum"),
            source_rows=("record_id", "count"),
        )
        .sort_values([*rules.group_columns, rules.date_column])
        .reset_index(drop=True)
    )


def score_daily_series(
    daily: pd.DataFrame,
    rules: AnomalyRules,
) -> pd.DataFrame:
    """Calculate trailing baselines and anomaly flags."""

    if daily.empty:
        return daily.copy()

    groupers = list(rules.group_columns)
    scored_groups: list[pd.DataFrame] = []

    for _, group in daily.groupby(groupers, dropna=False, sort=False):
        group = group.sort_values(rules.date_column).copy()
        prior_cost = group["actual_cost"].shift(1)

        group["history_days"] = prior_cost.rolling(
            window=rules.baseline_window_days,
            min_periods=1,
        ).count()

        group["baseline_cost"] = prior_cost.rolling(
            window=rules.baseline_window_days,
            min_periods=rules.minimum_history_days,
        ).median()

        group["absolute_variance"] = (
            group["actual_cost"] - group["baseline_cost"]
        )

        denominator = group["baseline_cost"].abs()
        group["relative_variance"] = (
            group["absolute_variance"] / denominator
        )
        group.loc[denominator.eq(0), "relative_variance"] = float("nan")

        group["direction"] = "increase"
        group.loc[group["absolute_variance"].lt(0), "direction"] = "decrease"

        threshold_mask = (
            group["absolute_variance"].abs()
            .ge(rules.absolute_threshold)
            & group["relative_variance"].abs()
            .ge(rules.relative_threshold)
        )

        if not rules.detect_decreases:
            threshold_mask &= group["absolute_variance"].gt(0)

        group["is_anomaly"] = (
            group["baseline_cost"].notna()
            & threshold_mask
        )

        critical_mask = (
            group["is_anomaly"]
            & group["absolute_variance"].abs()
            .ge(rules.critical_absolute_threshold)
            & group["relative_variance"].abs()
            .ge(rules.critical_relative_threshold)
        )

        group["severity"] = ""
        group.loc[group["is_anomaly"], "severity"] = "WARNING"
        group.loc[critical_mask, "severity"] = "CRITICAL"

        scored_groups.append(group)

    return pd.concat(scored_groups, ignore_index=True)


def detect_anomalies(
    dataframe: pd.DataFrame,
    rules: AnomalyRules,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """Prepare, aggregate, score, and return anomaly results."""

    cleaned, metrics = prepare_anomaly_input(dataframe, rules)
    daily = build_daily_series(cleaned, rules)
    scored = score_daily_series(daily, rules)

    if scored.empty:
        anomalies = scored.copy()
    else:
        anomalies = scored.loc[scored["is_anomaly"]].copy()

    report_columns = [
        rules.date_column,
        *rules.group_columns,
        "severity",
        "direction",
        "actual_cost",
        "baseline_cost",
        "absolute_variance",
        "relative_variance",
        "history_days",
        "source_rows",
    ]

    if anomalies.empty:
        anomalies = pd.DataFrame(columns=report_columns)
    else:
        anomalies = (
            anomalies[report_columns]
            .sort_values(
                ["severity", "absolute_variance"],
                ascending=[True, False],
            )
            .reset_index(drop=True)
        )

    metrics["daily_points"] = len(scored)
    metrics["anomalies_detected"] = len(anomalies)

    return anomalies, scored, metrics


def run_anomaly_detection(
    input_path: Path | str = INPUT_PATH,
    rules_path: Path | str = "config/anomaly_rules.json",
    report_path: Path | str = REPORT_PATH,
    daily_series_path: Path | str = DAILY_SERIES_PATH,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run anomaly detection and write report files."""

    source = pd.read_csv(
        input_path,
        dtype=str,
        keep_default_na=False,
    )
    rules = load_anomaly_rules(rules_path)

    anomalies, scored, metrics = detect_anomalies(source, rules)

    report_output = Path(report_path)
    daily_output = Path(daily_series_path)
    report_output.parent.mkdir(parents=True, exist_ok=True)
    daily_output.parent.mkdir(parents=True, exist_ok=True)

    anomalies.to_csv(
        report_output,
        index=False,
        float_format="%.4f",
    )
    scored.to_csv(
        daily_output,
        index=False,
        float_format="%.4f",
    )

    print(f"Input rows: {metrics['input_rows']:,}")
    print(
        "Duplicate rows removed: "
        f"{metrics['duplicate_rows_removed']:,}"
    )
    print(
        "Invalid negative Usage rows removed: "
        f"{metrics['invalid_negative_rows_removed']:,}"
    )
    print(
        "Rows excluded by charge category: "
        f"{metrics['excluded_category_rows']:,}"
    )
    print(f"Daily points analyzed: {metrics['daily_points']:,}")
    print(f"Anomalies detected: {metrics['anomalies_detected']:,}")

    if anomalies.empty:
        print("\nNo anomalies met both configured thresholds.")
    else:
        print(
            "\nAnomalies by severity:\n"
            + anomalies["severity"].value_counts().to_string()
        )

        preview_columns = [
            rules.date_column,
            "provider_name",
            "service_name",
            "application",
            "actual_cost",
            "baseline_cost",
            "absolute_variance",
            "relative_variance",
            "severity",
        ]
        available_preview = [
            column for column in preview_columns
            if column in anomalies.columns
        ]
        print(
            "\nTop anomalies:\n"
            + anomalies[available_preview]
            .head(10)
            .to_string(index=False)
        )

    print(f"\nReport: {report_output.as_posix()}")
    print(f"Daily series: {daily_output.as_posix()}")

    return anomalies, scored


if __name__ == "__main__":
    run_anomaly_detection()
