"""Output formatters for JSON, JSONL, CSV, and terminal tables."""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, TextIO

OUTPUT_FORMATS = ("json", "jsonl", "table", "csv")

def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

def scalar_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list, tuple)):
        return compact_json(value)
    return str(value)

def write_json(value: Any, output: TextIO, *, indent: Optional[int] = 2) -> None:
    json.dump(value, output, ensure_ascii=False, indent=indent)
    output.write("\n")

def write_jsonl(records: Iterable[Any], output: TextIO) -> None:
    for record in records:
        output.write(compact_json(record))
        output.write("\n")

def _record_fields(
    records: Sequence[Mapping[str, Any]],
    requested: Optional[Sequence[str]] = None,
) -> List[str]:
    if requested:
        return list(requested)
    fields: List[str] = []
    seen = set()
    for record in records:
        for key in record:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    return fields

def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return compact_json(value)
    return value

def write_csv(
    records: Sequence[Mapping[str, Any]],
    output: TextIO,
    *,
    fields: Optional[Sequence[str]] = None,
) -> None:
    fieldnames = _record_fields(records, fields)
    writer = csv.DictWriter(
        output,
        fieldnames=fieldnames,
        extrasaction="ignore",
        lineterminator="\n",
    )
    if fieldnames:
        writer.writeheader()
    for record in records:
        writer.writerow({field: _csv_value(record.get(field)) for field in fieldnames})

def _truncate(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."

def write_table(
    records: Sequence[Mapping[str, Any]],
    output: TextIO,
    *,
    fields: Optional[Sequence[str]] = None,
    max_column_width: int = 48,
) -> None:
    if not records:
        return
    fieldnames = _record_fields(records, fields)
    if not fieldnames:
        return
    rows = [
        {field: scalar_text(record.get(field)) for field in fieldnames}
        for record in records
    ]
    widths = {}
    for field in fieldnames:
        values = [field] + [row[field] for row in rows]
        widths[field] = min(max(len(value) for value in values), max_column_width)
    def render(row: Mapping[str, str]) -> str:
        cells = []
        for field in fieldnames:
            cells.append(_truncate(row[field], widths[field]).ljust(widths[field]))
        return "  ".join(cells).rstrip()
    output.write(render({field: field for field in fieldnames}))
    output.write("\n")
    output.write("  ".join("-" * widths[field] for field in fieldnames))
    output.write("\n")
    for row in rows:
        output.write(render(row))
        output.write("\n")

def write_records(
    records: Sequence[Mapping[str, Any]],
    output: TextIO,
    output_format: str = "jsonl",
    *,
    fields: Optional[Sequence[str]] = None,
) -> None:
    if output_format == "jsonl":
        write_jsonl(records, output)
    elif output_format == "json":
        write_json(list(records), output)
    elif output_format == "csv":
        write_csv(records, output, fields=fields)
    elif output_format == "table":
        write_table(records, output, fields=fields)
    else:
        raise ValueError(f"unknown output format: {output_format}")

def flatten_mapping(
    value: Any,
    *,
    prefix: str = "",
    separator: str = ".",
) -> Dict[str, Any]:
    """Flatten nested mappings for tabular output."""
    if not isinstance(value, Mapping):
        return {prefix or "value": value}
    flattened: Dict[str, Any] = {}
    for key, child in value.items():
        child_key = f"{prefix}{separator}{key}" if prefix else str(key)
        if isinstance(child, Mapping):
            flattened.update(
                flatten_mapping(child, prefix=child_key, separator=separator)
            )
        else:
            flattened[child_key] = child
    return flattened

def object_rows(data: Any) -> List[Dict[str, Any]]:
    """Convert arbitrary summary objects into rows for CSV/table output."""
    if isinstance(data, list):
        return [
            flatten_mapping(item) if isinstance(item, Mapping) else {"value": item}
            for item in data
        ]
    if not isinstance(data, Mapping):
        return [{"value": data}]
    if not data:
        return []
    mapping_values = list(data.values())
    if all(isinstance(value, Mapping) for value in mapping_values):
        rows = []
        for key, value in data.items():
            row = {"key": key}
            row.update(flatten_mapping(value))
            rows.append(row)
        return rows
    if all(not isinstance(value, (Mapping, list, tuple)) for value in mapping_values):
        return [{"key": key, "value": value} for key, value in data.items()]
    return [flatten_mapping(data)]

def write_object(
    data: Any,
    output: TextIO,
    output_format: str = "json",
    *,
    indent: int = 2,
) -> None:
    """Write a summary object in any supported output format."""
    if output_format == "json":
        write_json(data, output, indent=indent)
    elif output_format == "jsonl":
        # Summary objects remain one JSON value per line so scripts can parse
        # the output consistently with --count in earlier releases.
        write_json(data, output, indent=None)
    elif output_format == "csv":
        write_csv(object_rows(data), output)
    elif output_format == "table":
        write_table(object_rows(data), output)
    else:
        raise ValueError(f"unknown output format: {output_format}")

def render_records(
    records: Sequence[Mapping[str, Any]],
    output_format: str = "jsonl",
    *,
    fields: Optional[Sequence[str]] = None,
) -> str:
    """Render records to a string, useful for tests and embedding."""
    buffer = io.StringIO()
    write_records(records, buffer, output_format, fields=fields)
    return buffer.getvalue()
