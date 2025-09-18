"""Streaming-friendly counters, numeric summaries, and percentiles."""

from __future__ import annotations

import math
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from kindling.timestamps import get_path

MISSING_VALUE = "(missing)"

def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)

def percentile(values: Sequence[float], percent: float) -> Optional[float]:
    """Return an exact percentile using linear interpolation.
    ``percent`` is in the inclusive range 0 to 100. The implementation uses
    the common ``(n - 1) * p`` rank formula and works for both small and large
    sample sets. Exact percentiles require retaining the numeric values.
    """
    if not values:
        return None
    if percent < 0 or percent > 100:
        raise ValueError("percentile must be between 0 and 100")
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (percent / 100.0)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction

@dataclass
class RunningStats:
    """Accumulate numeric values and counters for one field."""
    values: List[float] = field(default_factory=list)
    total: int = 0
    missing: int = 0
    non_numeric: int = 0
    numeric_sum: float = 0.0
    numeric_sum_squares: float = 0.0
    def add_missing(self) -> None:
        self.total += 1
        self.missing += 1
    def add(self, value: Any) -> None:
        self.total += 1
        if not is_number(value):
            self.non_numeric += 1
            return
        number = float(value)
        self.values.append(number)
        self.numeric_sum += number
        self.numeric_sum_squares += number * number
    @property
    def count(self) -> int:
        return len(self.values)
    @property
    def mean(self) -> Optional[float]:
        if not self.values:
            return None
        return self.numeric_sum / self.count
    @property
    def variance(self) -> Optional[float]:
        if not self.values:
            return None
        mean = self.mean
        if mean is None:
            return None
        # The two-pass form avoids cancellation for values with large offsets.
        return sum((value - mean) ** 2 for value in self.values) / self.count
    @property
    def stddev(self) -> Optional[float]:
        variance = self.variance
        return None if variance is None else math.sqrt(variance)
    def summary(
        self,
        percentiles: Sequence[float] = (50.0, 90.0, 95.0, 99.0),
    ) -> Dict[str, Any]:
        summary: Dict[str, Any] = {
            "count": self.count,
            "total": self.total,
            "missing": self.missing,
            "non_numeric": self.non_numeric,
            "sum": self.numeric_sum if self.values else None,
            "min": min(self.values) if self.values else None,
            "max": max(self.values) if self.values else None,
            "mean": self.mean,
            "stddev": self.stddev,
        }
        for requested in percentiles:
            label = _percentile_label(requested)
            summary[label] = percentile(self.values, requested)
        return summary

def _percentile_label(percent: float) -> str:
    if float(percent).is_integer():
        return f"p{int(percent)}"
    return f"p{str(percent).replace('.', '_')}"

@dataclass
class FieldAggregator:
    """Accumulate stats for several fields as records stream past."""
    fields: Sequence[str]
    percentiles: Sequence[float] = (50.0, 90.0, 95.0, 99.0)
    stats: Dict[str, RunningStats] = field(default_factory=dict)
    def __post_init__(self) -> None:
        self.stats = {field: RunningStats() for field in self.fields}
    def add(self, record: Mapping[str, Any]) -> None:
        for field_name in self.fields:
            if field_name in record:
                value = record[field_name]
            elif "." in field_name:
                value = get_path(record, field_name)
            else:
                value = None
            if value is None:
                self.stats[field_name].add_missing()
            else:
                self.stats[field_name].add(value)
    def summary(self) -> Dict[str, Dict[str, Any]]:
        return {
            field_name: stats.summary(self.percentiles)
            for field_name, stats in self.stats.items()
        }

def summarize_values(
    values: Iterable[Any],
    percentiles: Sequence[float] = (50.0, 90.0, 95.0, 99.0),
) -> Dict[str, Any]:
    stats = RunningStats()
    for value in values:
        if value is None:
            stats.add_missing()
        else:
            stats.add(value)
    return stats.summary(percentiles)

def summarize_records(
    records: Iterable[Mapping[str, Any]],
    fields: Sequence[str],
    percentiles: Sequence[float] = (50.0, 90.0, 95.0, 99.0),
) -> Dict[str, Dict[str, Any]]:
    aggregator = FieldAggregator(fields, percentiles)
    for record in records:
        aggregator.add(record)
    return aggregator.summary()

def group_key(record: Mapping[str, Any], fields: Sequence[str]) -> str:
    """Build a stable display key for one or more grouping fields."""
    values = [get_path(record, field_name) for field_name in fields]
    if len(values) == 1:
        return MISSING_VALUE if values[0] is None else str(values[0])
    labels = [MISSING_VALUE if value is None else str(value) for value in values]
    return " | ".join(labels)




