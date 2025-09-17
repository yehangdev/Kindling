"""Streaming JSONL readers, path expansion, and dependency-free tailing."""

from __future__ import annotations

import glob
import gzip
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional
from typing import Sequence, TextIO, Tuple

ERROR_CALLBACK = Callable[[str, int, str], None]

@dataclass
class LogRecord:
    """A parsed JSONL record plus source position metadata."""
    data: Dict[str, Any]
    source: str
    line_number: int
    ordinal: int
    raw: str


@dataclass
class ReaderStats:
    """Counters useful for tests, diagnostics, and benchmarks."""
    lines: int = 0
    records: int = 0
    blank_lines: int = 0
    invalid_lines: int = 0
    files: int = 0
    bytes_read: int = 0

def is_gzip_path(path: str) -> bool:
    lowered = path.casefold()
    return lowered.endswith(".gz") or lowered.endswith(".gzip")

def open_text(path: str, encoding: str = "utf-8") -> TextIO:
    """Open plain text or gzip-compressed JSONL using only the stdlib."""
    if is_gzip_path(path):
        return gzip.open(path, "rt", encoding=encoding, newline="")
    return open(path, "r", encoding=encoding, newline="")

def _looks_like_glob(path: str) -> bool:
    return glob.has_magic(path)

def _directory_files(path: str) -> List[str]:
    directory = Path(path)
    if not directory.is_dir():
        return []
    files = []
    for candidate in sorted(directory.rglob("*")):
        if not candidate.is_file():
            continue
        lowered = candidate.name.casefold()
        if lowered.endswith((".jsonl", ".json", ".gz", ".gzip")):
            files.append(str(candidate))
    return files

def expand_paths(
    paths: Sequence[str],
    *,
    recursive: bool = True,
    deduplicate: bool = True,
) -> List[str]:
    """Expand files, glob patterns, and directories in stable order."""
    if not paths:
        return ["-"]
    expanded: List[str] = []
    for item in paths:
        if item == "-":
            expanded.append(item)
            continue
        if _looks_like_glob(item):
            matches = sorted(glob.glob(item, recursive=recursive))
            if matches:
                expanded.extend(matches)
            else:
                # Keep the original pattern so the reader can report a useful
                # missing-input error instead of silently dropping it.
                expanded.append(item)
            continue
        directory_files = _directory_files(item)
        if directory_files:
            expanded.extend(directory_files)
        else:
            expanded.append(item)
    if not deduplicate:
        return expanded
    result: List[str] = []
    seen = set()
    for item in expanded:
        absolute = item if item == "-" else os.path.abspath(item)
        if absolute in seen:
            continue
        seen.add(absolute)
        result.append(item)
    return result

def report_error(
    callback: Optional[ERROR_CALLBACK],
    source: str,
    line_number: int,
    message: str,
) -> None:
    if callback is not None:
        callback(source, line_number, message)

def parse_json_object(
    raw_line: str,
    *,
    source: str,
    line_number: int,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Parse one line and return either a mapping or a readable error."""
    if not raw_line.strip():
        return None, None
    try:
        value = json.loads(raw_line)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc.msg} at column {exc.colno}"
    if not isinstance(value, dict):
        return None, "expected a JSON object"
    return value, None

def iter_jsonl_handle(
    handle: Iterable[str],
    *,
    source: str,
    start_line: int = 1,
    start_ordinal: int = 0,
    on_error: Optional[ERROR_CALLBACK] = None,
    stats: Optional[ReaderStats] = None,
) -> Iterator[LogRecord]:
    """Yield parsed records from an iterable of text lines."""
    ordinal = start_ordinal
    for line_number, raw_line in enumerate(handle, start=start_line):
        if stats is not None:
            stats.lines += 1
            stats.bytes_read += len(raw_line.encode("utf-8"))
        if not raw_line.strip():
            if stats is not None:
                stats.blank_lines += 1
            continue
        record, error = parse_json_object(
            raw_line,
            source=source,
            line_number=line_number,
        )
        if error is not None:
            if stats is not None:
                stats.invalid_lines += 1
            report_error(on_error, source, line_number, error)
            continue
        if record is None:
            continue
        ordinal += 1
        if stats is not None:
            stats.records += 1
        yield LogRecord(
            data=record,
            source=source,
            line_number=line_number,
            ordinal=ordinal,
            raw=raw_line,
        )

def iter_jsonl(
    paths: Sequence[str],
    stdin: Optional[TextIO] = None,
    *,
    encoding: str = "utf-8",
    on_error: Optional[ERROR_CALLBACK] = None,
    stats: Optional[ReaderStats] = None,
) -> Iterator[LogRecord]:
    """Stream JSON objects from files, glob results, stdin, or gzip JSONL."""
    ordinal = 0
    for path in expand_paths(paths):
        if stats is not None:
            stats.files += 1
        if path == "-":
            if stdin is None:
                raise ValueError("stdin was not supplied for '-' input")
            for record in iter_jsonl_handle(
                stdin,
                source="<stdin>",
                start_ordinal=ordinal,
                on_error=on_error,
                stats=stats,
            ):
                ordinal = record.ordinal
                yield record
            continue
        try:
            handle = open_text(path, encoding=encoding)
        except OSError as exc:
            report_error(on_error, path, 0, str(exc))
            continue
        with handle:
            for record in iter_jsonl_handle(
                handle,
                source=path,
                start_ordinal=ordinal,
                on_error=on_error,
                stats=stats,
            ):
                ordinal = record.ordinal
                yield record

def iter_lines(
    paths: Sequence[str],
    stdin: TextIO,
) -> Iterator[Tuple[str, str, int]]:
    """Backward-compatible raw line iterator used by early callers."""
    for path in expand_paths(paths):
        if path == "-":
            for line_number, line in enumerate(stdin, start=1):
                yield line, "<stdin>", line_number
            continue
        with open_text(path) as handle:
            for line_number, line in enumerate(handle, start=1):
                yield line, path, line_number



