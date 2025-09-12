import unittest

from kindling.timestamps import ParserRegistry, parse_timestamp, strptime_parser
from kindling.timestamps import record_timestamp

class TimestampParserTests(unittest.TestCase):
    def test_custom_strptime_parser(self):
        parsed = parse_timestamp(
            "2025-01-01 08:00:00",
            formats=["%Y-%m-%d %H:%M:%S"],
        )
        self.assertEqual(parsed.isoformat(), "2025-01-01T08:00:00+00:00")
    def test_registry_parser_can_be_registered(self):
        registry = ParserRegistry()
        registry.register("custom", strptime_parser(["%Y/%m/%d"]))
        parsed = registry.parse("2025/01/01", "custom")
        self.assertEqual(parsed.isoformat(), "2025-01-01T00:00:00+00:00")
    def test_nested_timestamp_field(self):
        record = {"event": {"timestamp": 1_735_689_600_000}}
        parsed = record_timestamp(record, "event.timestamp")
        self.assertEqual(parsed.isoformat(), "2025-01-01T00:00:00+00:00")

if __name__ == "__main__":
    unittest.main()
