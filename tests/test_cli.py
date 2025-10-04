import io
import json
import tempfile
import unittest
from pathlib import Path

from kindling.cli import main, parse_timestamp

class ParseTimestampTests(unittest.TestCase):
    def test_iso_timestamp_is_normalized_to_utc(self):
        parsed = parse_timestamp("2025-01-01T08:00:00+08:00")
        self.assertEqual(parsed.isoformat(), "2025-01-01T00:00:00+00:00")
    def test_unix_milliseconds_are_supported(self):
        parsed = parse_timestamp(1_735_689_600_000)
        self.assertEqual(parsed.isoformat(), "2025-01-01T00:00:00+00:00")

class CliTests(unittest.TestCase):
    def run_cli(self, args, input_text=""):
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = main(
            args,
            stdin=io.StringIO(input_text),
            stdout=stdout,
            stderr=stderr,
        )
        return code, stdout.getvalue(), stderr.getvalue()
    def test_filters_by_time_service_level_and_fields(self):
        input_text = "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2025-01-01T10:00:00Z",
                        "service": "api",
                        "level": "INFO",
                        "message": "started",
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2025-01-01T10:00:01Z",
                        "service": "worker",
                        "level": "ERROR",
                        "message": "failed",
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2025-01-01T10:00:02Z",
                        "service": "api",
                        "level": "ERROR",
                        "message": "request failed",
                    }
                ),
            ]
        )
        code, stdout, stderr = self.run_cli(
            [
                "--start",
                "2025-01-01T10:00:01Z",
                "--service",
                "API",
                "--level",
                "error",
                "--fields",
                "timestamp,message",
            ],
            input_text,
        )
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            json.loads(stdout),
            {
                "timestamp": "2025-01-01T10:00:02Z",
                "message": "request failed",
            },
        )
    def test_counts_a_field(self):
        input_text = "\n".join(
            [
                json.dumps({"service": "api", "level": "INFO"}),
                json.dumps({"service": "api", "level": "ERROR"}),
                json.dumps({"service": "worker", "level": "INFO"}),
            ]
        )
        code, stdout, stderr = self.run_cli(["--count", "service"], input_text)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(json.loads(stdout), {"api": 2, "worker": 1})
    def test_groups_by_request_id_with_selected_fields(self):
        input_text = "\n".join(
            [
                json.dumps({"request_id": "abc", "message": "one"}),
                json.dumps({"request_id": "abc", "message": "two"}),
                json.dumps({"request_id": "def", "message": "three"}),
            ]
        )
        code, stdout, stderr = self.run_cli(
            ["--group-by-request-id", "--fields", "message"], input_text
        )
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            json.loads(stdout),
            {
                "abc": [{"message": "one"}, {"message": "two"}],
                "def": [{"message": "three"}],
            },
        )
    def test_reads_a_jsonl_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.jsonl"
            path.write_text(
                json.dumps({"level": "INFO", "message": "ok"}) + "\n",
                encoding="utf-8",
            )
            code, stdout, stderr = self.run_cli([str(path)])
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(json.loads(stdout), {"level": "INFO", "message": "ok"})
    def test_reports_invalid_lines_and_continues(self):
        input_text = "not-json\n" + json.dumps({"message": "ok"}) + "\n"
        code, stdout, stderr = self.run_cli([], input_text)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout), {"message": "ok"})
        self.assertIn("<stdin>:1: invalid JSON", stderr)
    def test_where_expression_and_dotted_fields(self):
        input_text = "\n".join(
            [
                json.dumps(
                    {
                        "request": {"path": "/v1/items", "status": 200},
                        "latency_ms": 12,
                    }
                ),
                json.dumps(
                    {
                        "request": {"path": "/v1/items", "status": 503},
                        "latency_ms": 120,
                    }
                ),
            ]
        )
        code, stdout, stderr = self.run_cli(
            [
                "--where",
                'request.path ~= "/items" and request.status >= 500',
                "--fields",
                "request.path,latency_ms",
            ],
            input_text,
        )
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            json.loads(stdout),
            {"request.path": "/v1/items", "latency_ms": 120},
        )
    def test_json_table_and_csv_formats(self):
        input_text = json.dumps({"level": "INFO", "message": "ok"}) + "\n"
        _, json_output, _ = self.run_cli(["--format", "json"], input_text)
        _, table_output, _ = self.run_cli(["--format", "table"], input_text)
        _, csv_output, _ = self.run_cli(["--format", "csv"], input_text)
        self.assertIsInstance(json.loads(json_output), list)
        self.assertIn("message", table_output)
        self.assertTrue(csv_output.startswith("level,message"))
    def test_group_order_and_within_group_timestamp_order(self):
        input_text = "\n".join(
            [
                json.dumps(
                    {
                        "request_id": "b",
                        "timestamp": "2025-01-01T00:00:02Z",
                        "message": "b2",
                    }
                ),
                json.dumps(
                    {
                        "request_id": "a",
                        "timestamp": "2025-01-01T00:00:03Z",
                        "message": "a2",
                    }
                ),
                json.dumps(
                    {
                        "request_id": "a",
                        "timestamp": "2025-01-01T00:00:01Z",
                        "message": "a1",
                    }
                ),
            ]
        )
        code, stdout, stderr = self.run_cli(
            [
                "--group-by-request-id",
                "--group-order",
                "request-id",
                "--within-group-order",
                "timestamp",
                "--fields",
                "message",
            ],
            input_text,
        )
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            list(json.loads(stdout)),
            ["a", "b"],
        )
        self.assertEqual(
            json.loads(stdout)["a"],
            [{"message": "a1"}, {"message": "a2"}],
        )
    def test_stats_percentile_summary(self):
        input_text = "\n".join(
            [
                json.dumps({"latency_ms": 10}),
                json.dumps({"latency_ms": 20}),
                json.dumps({"latency_ms": 30}),
                json.dumps({"latency_ms": 40}),
            ]
        )
        code, stdout, stderr = self.run_cli(
            ["--stats", "latency_ms", "--percentiles", "50,95"],
            input_text,
        )
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        summary = json.loads(stdout)["latency_ms"]
        self.assertEqual(summary["count"], 4)
        self.assertEqual(summary["p50"], 25.0)
        self.assertEqual(summary["p95"], 38.5)

if __name__ == "__main__":
    unittest.main()
