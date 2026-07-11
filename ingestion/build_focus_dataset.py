"""Build one combined FOCUS-aligned CSV from AWS and GCP fixtures."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ingestion.aws_synthetic_adapter import adapt_aws_csv
from ingestion.focus_schema import FOCUS_COLUMNS
from ingestion.gcp_synthetic_adapter import adapt_gcp_csv


def build_focus_dataset(
    aws_path: str | Path = "data/sample/aws_billing_sample.csv",
    gcp_path: str | Path = "data/sample/gcp_billing_sample.csv",
    output_path: str | Path = "data/processed/focus_cost_usage.csv",
) -> pd.DataFrame:
    rows = [
        *adapt_aws_csv(aws_path),
        *adapt_gcp_csv(gcp_path),
    ]

    dataframe = pd.DataFrame(
        [row.to_dict() for row in rows],
        columns=FOCUS_COLUMNS,
    )

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_csv(destination, index=False)
    return dataframe


if __name__ == "__main__":
    result = build_focus_dataset()
    print(
        f"Created data/processed/focus_cost_usage.csv "
        f"with {len(result):,} rows."
    )