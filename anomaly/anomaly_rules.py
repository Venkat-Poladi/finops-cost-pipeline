"""Configuration model for anomaly-detection rules."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_RULES_PATH = Path("config/anomaly_rules.json")


@dataclass(frozen=True, slots=True)
class AnomalyRules:
    """Validated anomaly-detection configuration."""

    cost_column: str
    date_column: str
    group_columns: tuple[str, ...]
    included_charge_categories: tuple[str, ...]
    baseline_window_days: int
    minimum_history_days: int
    relative_threshold: float
    absolute_threshold: float
    critical_relative_threshold: float
    critical_absolute_threshold: float
    detect_decreases: bool

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "AnomalyRules":
        required = {
            "cost_column",
            "date_column",
            "group_columns",
            "included_charge_categories",
            "baseline_window_days",
            "minimum_history_days",
            "relative_threshold",
            "absolute_threshold",
            "critical_relative_threshold",
            "critical_absolute_threshold",
            "detect_decreases",
        }

        missing = required - values.keys()
        if missing:
            raise ValueError(
                "Anomaly rules missing keys: "
                + ", ".join(sorted(missing))
            )

        baseline_window = int(values["baseline_window_days"])
        minimum_history = int(values["minimum_history_days"])

        if baseline_window < 2:
            raise ValueError("baseline_window_days must be at least 2")

        if minimum_history < 1:
            raise ValueError("minimum_history_days must be at least 1")

        if minimum_history > baseline_window:
            raise ValueError(
                "minimum_history_days cannot exceed baseline_window_days"
            )

        relative_threshold = float(values["relative_threshold"])
        absolute_threshold = float(values["absolute_threshold"])

        if relative_threshold < 0 or absolute_threshold < 0:
            raise ValueError("anomaly thresholds cannot be negative")

        return cls(
            cost_column=str(values["cost_column"]),
            date_column=str(values["date_column"]),
            group_columns=tuple(values["group_columns"]),
            included_charge_categories=tuple(
                values["included_charge_categories"]
            ),
            baseline_window_days=baseline_window,
            minimum_history_days=minimum_history,
            relative_threshold=relative_threshold,
            absolute_threshold=absolute_threshold,
            critical_relative_threshold=float(
                values["critical_relative_threshold"]
            ),
            critical_absolute_threshold=float(
                values["critical_absolute_threshold"]
            ),
            detect_decreases=bool(values["detect_decreases"]),
        )


def load_anomaly_rules(
    path: Path | str = DEFAULT_RULES_PATH,
) -> AnomalyRules:
    """Load anomaly rules from JSON."""

    config_path = Path(path)

    with config_path.open("r", encoding="utf-8") as handle:
        values = json.load(handle)

    if not isinstance(values, dict):
        raise ValueError("Anomaly rules JSON must contain an object")

    return AnomalyRules.from_dict(values)
