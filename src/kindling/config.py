"""Configuration loading for the command-line interface."""

from __future__ import annotations

import configparser
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

class ConfigError(ValueError):
    """Raised for unreadable or invalid configuration files."""


BOOLEAN_KEYS = {
    "follow",
    "follow_from_start",
    "group_by_request_id",
    "fail_on_error",
}
INTEGER_KEYS = {
    "indent",
    "limit",
    "max_line_length",
}
FLOAT_KEYS = {
    "follow_interval",
}
LIST_KEYS = {
    "files",
    "service",
    "level",
    "filter",
    "where",
    "stats",
    "aggregate",
    "group_by",
    "timestamp_format",
    "percentiles",
}
STRING_KEYS = {
    "config",
    "count",
    "start",
    "end",
    "time_field",
    "timestamp_parser",
    "fields",
    "format",
    "output",
    "request_id_field",
    "group_order",
    "within_group_order",
}

def _normalize_key(key: str) -> str:
    return key.strip().replace("-", "_")

def _parse_ini_value(key: str, value: str) -> Any:
    text = value.strip()
    if key in BOOLEAN_KEYS:
        lowered = text.casefold()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        raise ConfigError(f"{key} must be a boolean")
    if key in INTEGER_KEYS:
        try:
            return int(text)
        except ValueError as exc:
            raise ConfigError(f"{key} must be an integer") from exc
    if key in FLOAT_KEYS:
        try:
            return float(text)
        except ValueError as exc:
            raise ConfigError(f"{key} must be a number") from exc
    if key in LIST_KEYS:
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ConfigError(f"{key} is not a valid JSON list") from exc
            if not isinstance(parsed, list):
                raise ConfigError(f"{key} must be a list")
            return parsed
        return [part.strip() for part in text.split(",") if part.strip()]
    return text

def _find_config_section(data: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("kindling", "trace"):
        value = data.get(key)
        if isinstance(value, Mapping):
            return value
    return data

def _normalize_mapping(data: Mapping[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for raw_key, raw_value in _find_config_section(data).items():
        key = _normalize_key(str(raw_key))
        if key in LIST_KEYS and raw_value is None:
            normalized[key] = []
        elif key in LIST_KEYS and isinstance(raw_value, str):
            normalized[key] = [
                part.strip() for part in raw_value.split(",") if part.strip()
            ]
        elif key in LIST_KEYS and not isinstance(raw_value, list):
            raise ConfigError(f"{key} must be a list")
        elif key in BOOLEAN_KEYS and not isinstance(raw_value, bool):
            raise ConfigError(f"{key} must be a boolean")
        elif key in INTEGER_KEYS and not isinstance(raw_value, int):
            raise ConfigError(f"{key} must be an integer")
        elif key in FLOAT_KEYS and not isinstance(raw_value, (int, float)):
            raise ConfigError(f"{key} must be a number")
        else:
            normalized[key] = raw_value
    return normalized

def load_json_config(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"invalid JSON config {path}:{exc.lineno}:{exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(data, Mapping):
        raise ConfigError("config root must be a JSON object")
    return _normalize_mapping(data)

def load_ini_config(path: Path) -> Dict[str, Any]:
    parser = configparser.ConfigParser()
    try:
        with path.open("r", encoding="utf-8") as handle:
            parser.read_file(handle)
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    except configparser.Error as exc:
        raise ConfigError(f"invalid INI config {path}: {exc}") from exc
    if parser.has_section("kindling"):
        section = dict(parser.items("kindling"))
    elif parser.has_section("trace"):
        section = dict(parser.items("trace"))
    elif parser.defaults():
        section = dict(parser.defaults())
    else:
        section = {}
    normalized: Dict[str, Any] = {}
    for raw_key, raw_value in section.items():
        key = _normalize_key(raw_key)
        normalized[key] = _parse_ini_value(key, raw_value)
    return normalized

def load_config(path: str) -> Dict[str, Any]:
    """Load JSON or INI configuration and normalize option names."""
    expanded = os.path.expanduser(path)
    config_path = Path(expanded)
    suffix = config_path.suffix.casefold()
    if suffix == ".json":
        return load_json_config(config_path)
    if suffix in {".ini", ".cfg", ".conf"}:
        return load_ini_config(config_path)
    raise ConfigError(
        f"unsupported config suffix {suffix!r}; use .json, .ini, .cfg, or .conf"
    )

def discover_config(directory: str = ".") -> Optional[str]:
    """Find a conventional config file in a directory."""
    base = Path(directory)
    for name in (".kindling.json", ".kindling.ini", "kindling.json"):
        candidate = base / name
        if candidate.is_file():
            return str(candidate)
    return None

def list_config_options(config: Mapping[str, Any]) -> Iterable[str]:
    return sorted(config)
