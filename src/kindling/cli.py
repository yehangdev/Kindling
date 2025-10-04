"""Command-line interface for filtering and summarizing JSONL logs."""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, OrderedDict
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, TextIO

from kindling import __version__
from kindling.aggregates import (
    MISSING_VALUE, FieldAggregator, GroupMetadata, GroupedAggregator,
    ordered_group_keys, sort_group,
)
from kindling.config import ConfigError, load_config
from kindling.filters import (
    FilterExpression, FilterSyntaxError, parse_filter, record_matches, select_fields,
)
from kindling.formatters import OUTPUT_FORMATS, write_object, write_records
from kindling.reader import LogRecord, iter_follow_jsonl, iter_jsonl
from kindling.timestamps import (
    BUILTIN_PARSERS, DEFAULT_TIME_FIELDS, parse_timestamp, record_timestamp,
)

TIME_FIELDS = DEFAULT_TIME_FIELDS

def _parse_csv(value: str, option: str, parser: argparse.ArgumentParser) -> List[str]:
    fields = [part.strip() for part in value.split(",") if part.strip()]
    if not fields:
        parser.error(f"{option} requires at least one value")
    return fields

def _parse_percentiles(
    value: Any,
    parser: argparse.ArgumentParser,
) -> List[float]:
    if isinstance(value, (list, tuple)):
        parts = [str(item) for item in value]
    else:
        parts = str(value).split(",")
    result: List[float] = []
    for part in parts:
        try:
            number = float(part.strip())
        except ValueError:
            parser.error(f"invalid percentile: {part!r}")
        if number < 0 or number > 100:
            parser.error("percentiles must be between 0 and 100")
        if number not in result:
            result.append(number)
    if not result:
        parser.error("--percentiles requires at least one value")
    return sorted(result)

def _compile_filters(
    expressions: Sequence[str],
    parser: argparse.ArgumentParser,
) -> List[FilterExpression]:
    compiled = []
    for source in expressions:
        try:
            compiled.append(parse_filter(source))
        except FilterSyntaxError as exc:
            parser.error(f"invalid filter {source!r}: {exc}")
    return compiled

def _build_config_defaults(
    config: Mapping[str, Any],
    parser: argparse.ArgumentParser,
) -> Dict[str, Any]:
    valid_destinations = {action.dest for action in parser._actions}
    defaults: Dict[str, Any] = {}
    aliases = {
        "filter": "filters",
        "where": "filters",
        "aggregate": "stats",
        "summary": "stats",
    }
    for raw_key, value in config.items():
        key = aliases.get(raw_key, raw_key)
        if key == "config":
            continue
        if key not in valid_destinations:
            parser.error(f"unknown config option: {raw_key}")
        if key == "fields" and isinstance(value, list):
            value = ",".join(str(item) for item in value)
        if key == "percentiles" and isinstance(value, list):
            value = ",".join(str(item) for item in value)
        defaults[key] = value
    return defaults

def _option_is_present(
    argv: Sequence[str],
    parser: argparse.ArgumentParser,
    destination: str,
) -> bool:
    option_strings = {
        option
        for action in parser._actions
        if action.dest == destination
        for option in action.option_strings
    }
    return any(
        token == option or token.startswith(option + "=")
        for token in argv
        for option in option_strings
    )

def build_parser() -> argparse.ArgumentParser:
    """Build the complete argument parser."""
    parser = argparse.ArgumentParser(
        prog="kindling",
        description="Filter, group, aggregate, and format JSONL application logs.",
    )
    add = parser.add_argument
    add("files", nargs="*", help="JSONL files, directories, or glob patterns; omit for stdin")
    add("--config", help="JSON or INI config file; CLI options override config values")
    add("--start", help="inclusive ISO 8601 or Unix start time")
    add("--end", help="exclusive ISO 8601 or Unix end time")
    add("--time-field", help="timestamp field name")
    add("--timestamp-parser", default="auto", choices=BUILTIN_PARSERS.names(),
        help="timestamp parser to use (default: auto)")
    add("--timestamp-format", action="append", default=[],
        help="strptime format; may be repeated and takes precedence")
    add("--service", action="append", default=[],
        help="service name to include; may be repeated")
    add("--level", action="append", default=[],
        help="log level to include; may be repeated")
    add("--filter", "--where", dest="filters", action="append", default=[],
        help="boolean field expression; repeat to combine with AND")
    add("--fields", help="comma-separated top-level or dotted fields to emit")
    add("--format", choices=OUTPUT_FORMATS, default="jsonl",
        help="record output format (default: jsonl)")
    add("-o", "--output", help="write output to this file instead of standard output")
    add("--indent", type=int, default=2,
        help="indent used by JSON summary output (default: 2)")
    add("--limit", type=int, help="stop after this many matching records")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--count", metavar="FIELD", help="count values of a field")
    mode.add_argument("--group-by-request-id", action="store_true",
                      help="group matching records by request ID")
    mode.add_argument("--stats", "--aggregate", "--summary", dest="stats",
                      action="append", default=[], metavar="FIELD",
                      help="numeric summary and percentile fields; may be repeated")
    add("--percentiles", default="50,90,95,99",
        help="comma-separated percentiles for --stats (default: 50,90,95,99)")
    add("--group-by", action="append", default=[], metavar="FIELD",
        help="group --stats or --count by a field; may be repeated")
    add("--request-id-field", default="request_id",
        help="request ID field (default: request_id)")
    add("--group-order", choices=("first-seen", "request-id", "count"),
        default="first-seen", help="request-id group ordering (default: first-seen)")
    add("--within-group-order", choices=("input", "timestamp"), default="input",
        help="record ordering inside request-id groups (default: input)")
    add("--follow", action="store_true",
        help="follow files and emit appended records until interrupted")
    add("--follow-from-start", action="store_true",
        help="with --follow, emit existing file contents first")
    add("--follow-interval", type=float, default=0.2,
        help="follow polling interval in seconds (default: 0.2)")
    add("--fail-on-error", action="store_true",
        help="return a nonzero status after malformed or unreadable input")
    add("--version", action="version", version=f"%(prog)s {__version__}")
    return parser

def _resolve_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = build_parser()
    config_preparser = argparse.ArgumentParser(add_help=False)
    config_preparser.add_argument("--config")
    preliminary, _ = config_preparser.parse_known_args(argv)
    config_path = preliminary.config or os.environ.get("KINDLING_CONFIG")
    if config_path:
        try:
            config = load_config(config_path)
        except ConfigError as exc:
            parser.error(str(exc))
        defaults = _build_config_defaults(config, parser)
        cli_argv = list(argv if argv is not None else sys.argv[1:])
        defaults = {
            key: value
            for key, value in defaults.items()
            if not _option_is_present(cli_argv, parser, key)
        }
        defaults["config"] = config_path
        parser.set_defaults(**defaults)
    return parser.parse_args(argv)

def _field_value(record: Mapping[str, Any], field: str) -> Any:
    if field in record:
        return record[field]
    if "." not in field:
        return None
    current: Any = record
    for part in field.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current

def _iter_matching_records(
    args: argparse.Namespace,
    *,
    stdin: TextIO,
    on_error: Any,
    expressions: Sequence[FilterExpression],
) -> Iterator[LogRecord]:
    if args.follow:
        source = iter_follow_jsonl(
            args.files,
            poll_interval=args.follow_interval,
            from_start=args.follow_from_start,
            on_error=on_error,
        )
    else:
        source = iter_jsonl(args.files, stdin, on_error=on_error)
    services = {value.casefold() for value in args.service}
    levels = {value.casefold() for value in args.level}
    for log_record in source:
        if record_matches(
            log_record.data,
            services=services,
            levels=levels,
            start=args.start_value,
            end=args.end_value,
            time_field=args.time_field,
            expressions=expressions,
            timestamp_parser=args.timestamp_parser,
            timestamp_formats=args.timestamp_format,
        ):
            yield log_record

def _selected_record(
    record: Mapping[str, Any],
    fields: Optional[Sequence[str]],
) -> Dict[str, Any]:
    return select_fields(record, fields) if fields else dict(record)





def _emit_records(
    records: Iterator[LogRecord],
    *,
    output: TextIO,
    output_format: str,
    fields: Optional[Sequence[str]],
    limit: Optional[int],
    flush: bool = False,
) -> int:
    matched = 0
    if output_format == "jsonl":
        for log_record in records:
            if limit is not None and matched >= limit:
                break
            matched += 1
            write_records(
                [_selected_record(log_record.data, fields)],
                output,
                "jsonl",
                fields=fields,
            )
            if flush: output.flush()
        return matched
    buffered: List[Dict[str, Any]] = []
    for log_record in records:
        if limit is not None and matched >= limit:
            break
        matched += 1
        buffered.append(_selected_record(log_record.data, fields))
    write_records(
        buffered,
        output,
        output_format,
        fields=fields,
    )
    return matched

def main(
    argv: Optional[Sequence[str]] = None,
    *,
    stdin: Optional[TextIO] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    """Run the CLI and return an exit status."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    args = _resolve_args(argv)
    if args.limit is not None and args.limit < 0:
        raise SystemExit("--limit must be zero or greater")
    if args.indent < 0:
        raise SystemExit("--indent must be zero or greater")
    if args.follow_interval <= 0:
        raise SystemExit("--follow-interval must be greater than zero")
    if args.follow and not args.files:
        raise SystemExit("--follow requires at least one file path")
    if args.follow and (args.count or args.stats or args.group_by_request_id):
        raise SystemExit("--follow cannot be combined with a summary mode")
    if args.follow and args.format != "jsonl":
        raise SystemExit("--follow requires --format jsonl")
    if args.follow and "-" in args.files:
        raise SystemExit("--follow does not support standard input")
    try:
        args.start_value = (
            parse_timestamp(
                args.start,
                args.timestamp_parser,
                formats=args.timestamp_format,
            )
            if args.start
            else None
        )
        args.end_value = (
            parse_timestamp(
                args.end,
                args.timestamp_parser,
                formats=args.timestamp_format,
            )
            if args.end
            else None
        )
    except (OverflowError, OSError, ValueError) as exc:
        raise SystemExit(f"invalid timestamp: {exc}") from exc
    if args.start and args.start_value is None:
        raise SystemExit(f"invalid --start value: {args.start}")
    if args.end and args.end_value is None:
        raise SystemExit(f"invalid --end value: {args.end}")
    if (
        args.start_value is not None
        and args.end_value is not None
        and args.start_value >= args.end_value
    ):
        raise SystemExit("--start must be earlier than --end")
    validation_parser = build_parser()
    fields = (
        _parse_csv(args.fields, "--fields", validation_parser)
        if args.fields is not None
        else None
    )
    percentiles = _parse_percentiles(args.percentiles, validation_parser)
    expressions = _compile_filters(args.filters, validation_parser)
    error_count = 0
    def on_error(source: str, line_number: int, message: str) -> None:
        nonlocal error_count
        error_count += 1
        location = f"{source}:{line_number}" if line_number else source
        stderr.write(f"{location}: {message}\n")
    records = _iter_matching_records(
        args,
        stdin=stdin,
        on_error=on_error,
        expressions=expressions,
    )
    try:
        output_context = (
            Path(args.output).open("w", encoding="utf-8", newline="")
            if args.output
            else nullcontext(stdout)
        )
        with output_context as output:
            if args.count:
                result = _count_records(
                    records,
                    count_field=args.count,
                    group_fields=args.group_by,
                    limit=args.limit,
                )
                write_object(result, output, args.format, indent=args.indent)
            elif args.group_by_request_id:
                result = _request_groups(
                    records,
                    args=args,
                    fields=fields,
                    limit=args.limit,
                )
                write_object(result, output, args.format, indent=args.indent)
            elif args.stats:
                result = _stats_records(
                    records,
                    fields=args.stats,
                    group_fields=args.group_by,
                    percentiles=percentiles,
                    limit=args.limit,
                )
                write_object(result, output, args.format, indent=args.indent)
            else:
                _emit_records(
                    records,
                    output=output,
                    output_format=args.format,
                    fields=fields,
                    limit=args.limit,
                    flush=args.follow,
                )
    except KeyboardInterrupt:
        return 130 if args.fail_on_error else 0
    except OSError as exc:
        stderr.write(f"{exc}\n")
        return 2
    if args.fail_on_error and error_count:
        return 2
    return 0
