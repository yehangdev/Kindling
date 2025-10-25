import io
import json
import tempfile
import unittest
from pathlib import Path

from kindling.benchmark import benchmark_json_parsing, format_result
from kindling.cli import main
from kindling.config import ConfigError, load_config

class ConfigAndBenchmarkTests(unittest.TestCase):
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
    def test_json_config_is_applied_and_cli_appends_override_it(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "trace.json"
            config_path.write_text(
                json.dumps(
                    {
                        "format": "jsonl",
                        "service": ["api"],
                        "fields": ["service", "message"],
                    }
                ),
                encoding="utf-8",
            )
            input_text = "\n".join(
                [
                    json.dumps({"service": "api", "message": "a"}),
                    json.dumps({"service": "worker", "message": "b"}),
                ]
            )
            code, stdout, stderr = self.run_cli(
                ["--config", str(config_path), "--service", "worker"],
                input_text,
            )
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            json.loads(stdout),
            {"service": "worker", "message": "b"},
        )
    def test_ini_config_and_invalid_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.ini"
            path.write_text(
                "[kindling]\nlevel=ERROR\nfollow=false\npercentiles=50,95\n",
                encoding="utf-8",
            )
            config = load_config(str(path))
            with self.assertRaises(ConfigError):
                load_config(str(Path(directory) / "trace.toml"))
        self.assertEqual(config["level"], ["ERROR"])
        self.assertEqual(config["percentiles"], ["50", "95"])
        self.assertFalse(config["follow"])
    def test_benchmark_reports_parser_counts(self):
        lines = ['{"message": "a"}', "bad json", '{"message": "b"}']
        result = benchmark_json_parsing(lines, iterations=2, parse_timestamps=False)
        rendered = format_result(result)
        self.assertEqual(result.lines, 6)
        self.assertEqual(result.records, 4)
        self.assertIn("records_per_second", rendered)

if __name__ == "__main__":
    unittest.main()
