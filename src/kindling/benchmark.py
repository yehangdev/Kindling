"""Repeatable parser benchmarks using only the standard library."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence, TextIO

from kindling.reader import expand_paths, open_text
from kindling.timestamps import record_timestamp

@dataclass(frozen=True)
class BenchmarkResult:
    lines: int
    records: int
    iterations: int
    elapsed_seconds: float
    @property
    def lines_per_second(self) -> float:
        if self.elapsed_seconds <= 0:
            return float("inf")
        return self.lines / self.elapsed_seconds
    @property
    def records_per_second(self) -> float:
        if self.elapsed_seconds <= 0:
            return float("inf")
        return self.records / self.elapsed_seconds
    def as_dict(self) -> dict:
        return {
            "lines": self.lines,
            "records": self.records,
            "iterations": self.iterations,
            "elapsed_seconds": self.elapsed_seconds,
            "lines_per_second": self.lines_per_second,
            "records_per_second": self.records_per_second,
        }

def _iter_file_lines(paths: Sequence[str]) -> Iterable[str]:
    for path in expand_paths(paths):
        if path == "-":
            yield from sys.stdin
            continue
        with open_text(path) as handle:
            yield from handle

def benchmark_json_parsing(
    lines: Iterable[str],
    *,
    iterations: int = 1,
    parse_timestamps: bool = True,
) -> BenchmarkResult:
    """Benchmark JSON decoding and optional timestamp extraction."""
    if iterations < 1:
        raise ValueError("iterations must be at least one")
    materialized = list(lines)
    started = time.perf_counter()
    line_count = 0
    record_count = 0
    for _ in range(iterations):
        for raw_line in materialized:
            line_count += 1
            if not raw_line.strip():
                continue
            try:
                value = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if not isinstance(value, Mapping):
                continue
            record_count += 1
            if parse_timestamps:
                record_timestamp(value)
    elapsed = time.perf_counter() - started
    return BenchmarkResult(
        lines=line_count,
        records=record_count,
        iterations=iterations,
        elapsed_seconds=elapsed,
    )

def benchmark_files(
    paths: Sequence[str],
    *,
    iterations: int = 1,
    parse_timestamps: bool = True,
) -> BenchmarkResult:
    return benchmark_json_parsing(
        _iter_file_lines(paths),
        iterations=iterations,
        parse_timestamps=parse_timestamps,
    )

def format_result(result: BenchmarkResult) -> str:
    lines = [
        f"iterations: {result.iterations}",
        f"lines: {result.lines}",
        f"records: {result.records}",
        f"elapsed_seconds: {result.elapsed_seconds:.6f}",
        f"lines_per_second: {result.lines_per_second:.2f}",
        f"records_per_second: {result.records_per_second:.2f}",
    ]
    return "\n".join(lines)

def build_benchmark_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m kindling.benchmark",
        description="Benchmark JSONL and timestamp parser hot paths.",
    )
    parser.add_argument("files", nargs="+", help="JSONL files or glob patterns")
    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="number of complete passes over the input",
    )
    parser.add_argument(
        "--no-timestamps",
        action="store_true",
        help="benchmark JSON decoding only",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable benchmark output",
    )
    return parser

def main(argv: Optional[Sequence[str]] = None, stdout: Optional[TextIO] = None) -> int:
    args = build_benchmark_parser().parse_args(argv)
    if args.iterations < 1:
        raise SystemExit("--iterations must be at least one")
    try:
        result = benchmark_files(
            args.files,
            iterations=args.iterations,
            parse_timestamps=not args.no_timestamps,
        )
    except OSError as exc:
        raise SystemExit(str(exc)) from exc
    output = stdout or sys.stdout
    if args.json:
        json.dump(result.as_dict(), output, ensure_ascii=False, indent=2)
        output.write("\n")
    else:
        output.write(format_result(result))
        output.write("\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
