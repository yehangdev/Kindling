import gzip
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from kindling.reader import expand_paths, iter_follow_jsonl, iter_jsonl

class ReaderTests(unittest.TestCase):
    def test_glob_and_gzip_inputs_are_streamed(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "a.jsonl").write_text(
                json.dumps({"message": "a"}) + "\n",
                encoding="utf-8",
            )
            with gzip.open(base / "b.jsonl.gz", "wt", encoding="utf-8") as handle:
                handle.write(json.dumps({"message": "b"}) + "\n")
            pattern = str(base / "*.jsonl*")
            records = list(iter_jsonl([pattern]))
            expanded = expand_paths([pattern])
        self.assertEqual([record.data["message"] for record in records], ["a", "b"])
        self.assertEqual(len(expanded), 2)
    def test_invalid_and_non_object_lines_are_reported(self):
        errors = []
        lines = ["bad\n", "[1, 2]\n", "\n", '{"ok": true}\n']
        records = list(
            iter_jsonl(
                [],
                iter(lines),
                on_error=lambda source, line, message: errors.append(
                    (source, line, message)
                ),
            )
        )
        self.assertEqual(len(records), 1)
        self.assertEqual([item[1] for item in errors], [1, 2])
        self.assertIn("invalid JSON", errors[0][2])
        self.assertIn("JSON object", errors[1][2])
    def test_missing_file_is_reported_without_stopping_other_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ok.jsonl"
            path.write_text('{"message": "ok"}\n', encoding="utf-8")
            errors = []
            records = list(
                iter_jsonl(
                    [str(Path(directory) / "missing*.jsonl"), str(path)],
                    on_error=lambda source, line, message: errors.append(message),
                )
            )
        self.assertEqual(len(records), 1)
        self.assertEqual(len(errors), 1)
    def test_follow_emits_only_complete_appended_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "live.jsonl"
            path.write_text('{"message": "old"}\n', encoding="utf-8")
            stop = threading.Event()
            records = []
            def consume():
                for record in iter_follow_jsonl(
                    [str(path)],
                    poll_interval=0.01,
                    stop_event=stop,
                ):
                    records.append(record.data)
            thread = threading.Thread(target=consume)
            thread.start()
            time.sleep(0.03)
            with path.open("a", encoding="utf-8") as handle:
                handle.write('{"message": "new"')
                handle.flush()
            time.sleep(0.03)
            with path.open("a", encoding="utf-8") as handle:
                handle.write("}\n")
                handle.flush()
            time.sleep(0.05)
            stop.set()
            thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(records, [{"message": "new"}])

if __name__ == "__main__":
    unittest.main()
