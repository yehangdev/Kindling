import io
import json
import unittest

from kindling.formatters import object_rows, write_object, write_records

class FormatterTests(unittest.TestCase):
    def render_records(self, output_format):
        output = io.StringIO()
        write_records(
            [{"level": "INFO", "message": "started"}],
            output,
            output_format,
            fields=["level", "message"],
        )
        return output.getvalue()
    def test_record_formats(self):
        self.assertEqual(
            json.loads(self.render_records("jsonl")),
            {"level": "INFO", "message": "started"},
        )
        self.assertEqual(
            json.loads(self.render_records("json")),
            [{"level": "INFO", "message": "started"}],
        )
        self.assertIn("level,message", self.render_records("csv"))
        self.assertIn("started", self.render_records("table"))
    def test_object_rows_flatten_nested_summaries(self):
        rows = object_rows(
            {
                "api": {
                    "count": 2,
                    "metrics": {"latency_ms": {"mean": 15.0}},
                }
            }
        )
        self.assertEqual(rows[0]["key"], "api")
        self.assertEqual(rows[0]["count"], 2)
        self.assertEqual(rows[0]["metrics.latency_ms.mean"], 15.0)
    def test_jsonl_object_output_stays_one_object_per_line(self):
        output = io.StringIO()
        write_object({"api": 2, "worker": 1}, output, "jsonl")
        self.assertEqual(json.loads(output.getvalue()), {"api": 2, "worker": 1})
        self.assertEqual(output.getvalue().count("\n"), 1)

if __name__ == "__main__":
    unittest.main()
