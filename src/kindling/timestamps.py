"""Timestamp parsing with a small pluggable parser registry."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple

DEFAULT_TIME_FIELDS: Tuple[str, ...] = (
    "timestamp",
    "time",
    "ts",
    "@timestamp",
)

TimestampParser = Callable[[Any], Optional[datetime]]

class TimestampParseError(ValueError):
    """Raised when a configured timestamp parser cannot handle a value."""

class ParserRegistry:
    """A mutable registry of named timestamp parsers.
    The registry is intentionally small so applications can register a domain
    specific parser without changing the command-line layer. Parsers receive
    the original JSON value and return ``None`` when the value is not a
    timestamp they recognize.
    """
    def __init__(self) -> None:
        self._parsers: Dict[str, TimestampParser] = {}
    def register(
        self,
        name: str,
        parser: TimestampParser,
        *,
        replace: bool = False,
    ) -> None:
        normalized = _normalize_parser_name(name)
        if normalized in self._parsers and not replace:
            raise ValueError(f"timestamp parser already registered: {name}")
        self._parsers[normalized] = parser
    def unregister(self, name: str) -> None:
        self._parsers.pop(_normalize_parser_name(name), None)
    def get(self, name: str) -> TimestampParser:
        try:
            return self._parsers[_normalize_parser_name(name)]
        except KeyError as exc:
            choices = ", ".join(sorted(self._parsers))
            raise TimestampParseError(
                f"unknown timestamp parser {name!r}; choose from {choices}"
            ) from exc
    def names(self) -> Tuple[str, ...]:
        return tuple(sorted(self._parsers))
    def parse(self, value: Any, parser: str = "auto") -> Optional[datetime]:
        if parser == "auto":
            return self.parse_auto(value)
        return self.get(parser)(value)
    def parse_auto(self, value: Any) -> Optional[datetime]:
        for parser in self._parsers.values():
            try:
                parsed = parser(value)
            except (OverflowError, OSError, ValueError, TypeError):
                continue
            if parsed is not None:
                return parsed
        return None

def _normalize_parser_name(name: str) -> str:
    return name.strip().casefold().replace("_", "-")

def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

def parse_iso8601(value: Any) -> Optional[datetime]:
    """Parse an ISO 8601 string and normalize it to UTC."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return _utc(parsed)

def _parse_unix_number(value: float, unit: str) -> datetime:
    try:
        if unit == "seconds":
            return datetime.fromtimestamp(value, tz=timezone.utc)
        if unit == "milliseconds":
            return datetime.fromtimestamp(value / 1_000, tz=timezone.utc)
        if unit == "microseconds":
            return datetime.fromtimestamp(value / 1_000_000, tz=timezone.utc)
        if unit == "nanoseconds":
            return datetime.fromtimestamp(value / 1_000_000_000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise TimestampParseError(f"invalid unix timestamp: {value!r}") from exc
    raise TimestampParseError(f"unsupported unix timestamp unit: {unit}")


_INTEGER_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(
    r"^[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?$"
)

def _coerce_numeric_text(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if not _INTEGER_RE.match(text) and not _FLOAT_RE.match(text):
        return None
    try:
        return float(text)
    except ValueError:
        return None

def _infer_unix_unit(value: float) -> str:
    """Infer a unix unit from the magnitude of a value."""
    magnitude = abs(value)
    if magnitude >= 100_000_000_000_000_000:
        return "nanoseconds"
    if magnitude >= 100_000_000_000_000:
        return "microseconds"
    if magnitude >= 10_000_000_000:
        return "milliseconds"
    return "seconds"

def parse_unix(value: Any) -> Optional[datetime]:
    """Parse a Unix timestamp, inferring seconds through nanoseconds."""
    number = _coerce_numeric_text(value)
    if number is None:
        return None
    return _parse_unix_number(number, _infer_unix_unit(number))

def parse_unix_seconds(value: Any) -> Optional[datetime]:
    number = _coerce_numeric_text(value)
    if number is None:
        return None
    return _parse_unix_number(number, "seconds")

def parse_unix_milliseconds(value: Any) -> Optional[datetime]:
    number = _coerce_numeric_text(value)
    if number is None:
        return None
    return _parse_unix_number(number, "milliseconds")

def parse_unix_microseconds(value: Any) -> Optional[datetime]:
    number = _coerce_numeric_text(value)
    if number is None:
        return None
    return _parse_unix_number(number, "microseconds")

def parse_unix_nanoseconds(value: Any) -> Optional[datetime]:
    number = _coerce_numeric_text(value)
    if number is None:
        return None
    return _parse_unix_number(number, "nanoseconds")

def strptime_parser(formats: Iterable[str]) -> TimestampParser:
    """Build a parser that tries a sequence of ``datetime.strptime`` formats."""
    compiled = tuple(formats)
    def parse(value: Any) -> Optional[datetime]:
        if not isinstance(value, str):
            return None
        text = value.strip()
        if not text:
            return None
        for fmt in compiled:
            try:
                return _utc(datetime.strptime(text, fmt))
            except ValueError:
                continue
        return None
    return parse

def register_builtin_parsers(
    registry: Optional[ParserRegistry] = None,
) -> ParserRegistry:
    """Create or populate a registry with the common parsers."""
    registry = registry or ParserRegistry()
    registry.register("iso8601", parse_iso8601)
    registry.register("unix", parse_unix)
    registry.register("unix-seconds", parse_unix_seconds)
    registry.register("unix-milliseconds", parse_unix_milliseconds)
    registry.register("unix-microseconds", parse_unix_microseconds)
    registry.register("unix-nanoseconds", parse_unix_nanoseconds)
    return registry


BUILTIN_PARSERS = register_builtin_parsers()

def resolve_parser(
    parser: str = "auto",
    *,
    formats: Iterable[str] = (),
    registry: Optional[ParserRegistry] = None,
) -> TimestampParser:
    """Resolve a name or build a parser from user-supplied formats."""
    active_registry = registry or BUILTIN_PARSERS
    format_list = tuple(formats)
    if format_list:
        return strptime_parser(format_list)
    if parser != "auto":
        return active_registry.get(parser)
    def parse_auto(value: Any) -> Optional[datetime]:
        return active_registry.parse_auto(value)
    return parse_auto

def parse_timestamp(
    value: Any,
    parser: str = "auto",
    *,
    formats: Iterable[str] = (),
    registry: Optional[ParserRegistry] = None,
) -> Optional[datetime]:
    """Parse one timestamp with a built-in or configured parser."""
    resolved = resolve_parser(parser, formats=formats, registry=registry)
    return resolved(value)

def get_path(record: Mapping[str, Any], field: str) -> Any:
    """Read a dotted field path from nested mappings.
    A literal top-level key wins over traversal, which keeps fields that
    contain dots addressable when they are present in the source record.
    """
    if field in record:
        return record[field]
    current: Any = record
    for part in field.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current

def record_timestamp(
    record: Mapping[str, Any],
    time_field: Optional[str] = None,
    *,
    parser: str = "auto",
    formats: Iterable[str] = (),
    registry: Optional[ParserRegistry] = None,
) -> Optional[datetime]:
    """Return the first parseable timestamp found in a record."""
    fields = (time_field,) if time_field else DEFAULT_TIME_FIELDS
    resolved = resolve_parser(parser, formats=formats, registry=registry)
    for field in fields:
        if field not in record and "." not in field:
            continue
        parsed = resolved(get_path(record, field))
        if parsed is not None:
            return parsed
    return None
