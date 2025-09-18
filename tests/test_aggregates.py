import unittest
from datetime import datetime, timezone

from kindling.aggregates import (
    FieldAggregator,
    GroupMetadata,
    GroupedAggregator,
    ordered_group_keys,
    percentile,
    sort_group,
)

class AggregateTests(unittest.TestCase):
    def test_percentile_uses_linear_interpolation(self):
        values = [10.0, 20.0, 30.0, 40.0]
        self.assertEqual(percentile(values, 0), 10.0)
        self.assertEqual(percentile(values, 50), 25.0)
        self.assertEqual(percentile(values, 100), 40.0)
        with self.assertRaises(ValueError):
            percentile(values, 101)
    def test_field_aggregator_counts_missing_and_non_numeric(self):
        aggregator = FieldAggregator(["latency_ms"], (50, 95))
        aggregator.add({"latency_ms": 10})
        aggregator.add({"latency_ms": "slow"})
        aggregator.add({})
        summary = aggregator.summary()["latency_ms"]
        self.assertEqual(summary["count"], 1)
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["missing"], 1)
        self.assertEqual(summary["non_numeric"], 1)
        self.assertEqual(summary["p95"], 10.0)
    def test_grouped_aggregator_uses_stable_group_keys(self):
        aggregator = GroupedAggregator(["service"], ["latency_ms"], (50,))
        aggregator.add({"service": "api", "latency_ms": 10})
        aggregator.add({"service": "worker", "latency_ms": 30})
        aggregator.add({"service": "api", "latency_ms": 20})
        summary = aggregator.summary()
        self.assertEqual(summary["api"]["count"], 2)
        self.assertEqual(summary["api"]["metrics"]["latency_ms"]["mean"], 15.0)
        self.assertEqual(summary["worker"]["metrics"]["latency_ms"]["p50"], 30.0)
    def test_group_and_within_group_ordering(self):
        metadata = {
            "second": GroupMetadata(2, 3, 2),
            "first": GroupMetadata(1, 4, 3),
        }
        groups = {"second": [], "first": []}
        self.assertEqual(
            ordered_group_keys(groups, metadata, "first-seen"),
            ["first", "second"],
        )
        self.assertEqual(
            ordered_group_keys(groups, metadata, "count"),
            ["first", "second"],
        )
        later = datetime(2025, 1, 1, 0, 0, 1, tzinfo=timezone.utc)
        earlier = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        ordered = sort_group(
            [("later", later, 2), ("earlier", earlier, 1)],
            "timestamp",
        )
        self.assertEqual(ordered, ["earlier", "later"])

if __name__ == "__main__":
    unittest.main()
