"""Boolean field expressions and record-level filtering."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Mapping, Optional, Sequence, Set, Tuple

from kindling.timestamps import get_path, record_timestamp

class FilterSyntaxError(ValueError):
    """Raised when a boolean filter expression is malformed."""

@dataclass(frozen=True)
class Token:
    kind: str
    value: Any
    position: int


_NUMBER_RE = re.compile(
    r"[+-]?(?:(?:\d+\.\d*)|(?:\.\d+)|(?:\d+))(?:[eE][+-]?\d+)?"
)
_IDENT_START = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_@$")
_IDENT_BODY = _IDENT_START | set("0123456789.-/:")
_TWO_CHAR_OPERATORS = {"==", "!=", ">=", "<=", "~=", "=~", "!~", "&&", "||"}
_ONE_CHAR_OPERATORS = {">", "<", "~", "=", "!"}
_KEYWORDS = {"and", "or", "not", "in", "true", "false", "null", "none"}

def _syntax_error(source: str, position: int, message: str) -> FilterSyntaxError:
    pointer = " " * max(0, position) + "^"
    return FilterSyntaxError(
        f"{message} at position {position}\n{source}\n{pointer}"
    )

def tokenize_filter(source: str) -> List[Token]:
    """Turn a filter expression into a compact token stream."""
    tokens: List[Token] = []
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        if char.isspace():
            index += 1
            continue
        if char in "()[]":
            tokens.append(Token(char, char, index))
            index += 1
            continue
        if char == ",":
            tokens.append(Token(",", ",", index))
            index += 1
            continue
        if char in ("'", '"'):
            quote = char
            start = index
            index += 1
            value: List[str] = []
            while index < length:
                current = source[index]
                if current == "\\":
                    index += 1
                    if index >= length:
                        raise _syntax_error(
                            source, start, "unterminated string literal"
                        )
                    escaped = source[index]
                    translations = {
                        "n": "\n",
                        "r": "\r",
                        "t": "\t",
                        "\\": "\\",
                        "'": "'",
                        '"': '"',
                    }
                    value.append(translations.get(escaped, escaped))
                    index += 1
                    continue
                if current == quote:
                    index += 1
                    tokens.append(Token("STRING", "".join(value), start))
                    break
                value.append(current)
                index += 1
            else:
                raise _syntax_error(source, start, "unterminated string literal")
            continue
        two = source[index : index + 2]
        if two in _TWO_CHAR_OPERATORS:
            tokens.append(Token("OP", two, index))
            index += 2
            continue
        if char in _ONE_CHAR_OPERATORS:
            tokens.append(Token("OP", char, index))
            index += 1
            continue
        if char.isdigit() or (
            char in "+-"
            and index + 1 < length
            and source[index + 1].isdigit()
        ):
            match = _NUMBER_RE.match(source, index)
            if match is None:
                raise _syntax_error(source, index, "invalid number")
            text = match.group(0)
            value = float(text) if any(mark in text for mark in ".eE") else int(text)
            tokens.append(Token("NUMBER", value, index))
            index = match.end()
            continue
        if char in _IDENT_START:
            start = index
            index += 1
            while index < length and source[index] in _IDENT_BODY:
                index += 1
            text = source[start:index]
            lowered = text.casefold()
            if lowered in _KEYWORDS:
                tokens.append(Token(lowered.upper(), lowered, start))
            else:
                tokens.append(Token("IDENT", text, start))
            continue
        raise _syntax_error(source, index, f"unexpected character {char!r}")
    tokens.append(Token("EOF", None, length))
    return tokens

class Expression:
    """Base class for evaluable expression nodes."""
    def evaluate(self, record: Mapping[str, Any]) -> Any:
        raise NotImplementedError

@dataclass(frozen=True)
class Literal(Expression):
    value: Any
    def evaluate(self, record: Mapping[str, Any]) -> Any:
        return self.value

@dataclass(frozen=True)
class Field(Expression):
    path: str
    def evaluate(self, record: Mapping[str, Any]) -> Any:
        return get_path(record, self.path)

@dataclass(frozen=True)
class ListValue(Expression):
    values: Tuple[Expression, ...]
    def evaluate(self, record: Mapping[str, Any]) -> List[Any]:
        return [value.evaluate(record) for value in self.values]

@dataclass(frozen=True)
class Not(Expression):
    operand: Expression
    def evaluate(self, record: Mapping[str, Any]) -> bool:
        return not bool(self.operand.evaluate(record))

@dataclass(frozen=True)
class BooleanOperation(Expression):
    operator: str
    left: Expression
    right: Expression
    def evaluate(self, record: Mapping[str, Any]) -> bool:
        if self.operator == "and":
            return bool(self.left.evaluate(record)) and bool(
                self.right.evaluate(record)
            )
        if self.operator == "or":
            return bool(self.left.evaluate(record)) or bool(
                self.right.evaluate(record)
            )
        raise ValueError(f"unknown boolean operator: {self.operator}")

def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)

def _number(value: Any) -> Optional[float]:
    if _is_number(value):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None

def _equal(left: Any, right: Any) -> bool:
    if _is_number(left) and _is_number(right):
        return float(left) == float(right)
    if isinstance(left, str) and _is_number(right):
        parsed = _number(left)
        return parsed is not None and parsed == float(right)
    if isinstance(right, str) and _is_number(left):
        parsed = _number(right)
        return parsed is not None and parsed == float(left)
    return left == right

def _compare_numbers(left: Any, right: Any, operator: str) -> bool:
    left_number = _number(left)
    right_number = _number(right)
    if left_number is None or right_number is None:
        return False
    if operator == ">":
        return left_number > right_number
    if operator == ">=":
        return left_number >= right_number
    if operator == "<":
        return left_number < right_number
    if operator == "<=":
        return left_number <= right_number
    return False

def _regex_search(left: Any, right: Any) -> bool:
    if left is None or not isinstance(right, str):
        return False
    try:
        return re.search(right, str(left), re.IGNORECASE) is not None
    except re.error:
        return False

@dataclass(frozen=True)
class Comparison(Expression):
    operator: str
    left: Expression
    right: Expression
    def evaluate(self, record: Mapping[str, Any]) -> bool:
        left = self.left.evaluate(record)
        right = self.right.evaluate(record)
        if self.operator in ("==", "="):
            return _equal(left, right)
        if self.operator == "!=":
            return not _equal(left, right)
        if self.operator in (">", ">=", "<", "<="):
            return _compare_numbers(left, right, self.operator)
        if self.operator in ("~", "~=", "=~"):
            return _regex_search(left, right)
        if self.operator == "!~":
            return not _regex_search(left, right)
        if self.operator == "in":
            if not isinstance(right, list):
                return False
            return any(_equal(left, item) for item in right)
        if self.operator == "not in":
            if not isinstance(right, list):
                return True
            return not any(_equal(left, item) for item in right)
        raise ValueError(f"unknown comparison operator: {self.operator}")

class FilterParser:
    """Recursive-descent parser for filters such as ``level == ERROR``."""
    def __init__(self, source: str) -> None:
        self.source = source
        self.tokens = tokenize_filter(source)
        self.index = 0
    @property
    def current(self) -> Token:
        return self.tokens[self.index]
    def advance(self) -> Token:
        token = self.current
        self.index += 1
        return token
    def accept(self, kind: str, value: Optional[Any] = None) -> Optional[Token]:
        token = self.current
        if token.kind != kind:
            return None
        if value is not None and token.value != value:
            return None
        self.index += 1
        return token
    def expect(self, kind: str, value: Optional[Any] = None) -> Token:
        token = self.accept(kind, value)
        if token is None:
            expected = value if value is not None else kind
            raise _syntax_error(
                self.source,
                self.current.position,
                f"expected {expected!r}, found {self.current.value!r}",
            )
        return token
    def parse(self) -> Expression:
        expression = self.parse_or()
        self.expect("EOF")
        return expression
    def parse_or(self) -> Expression:
        expression = self.parse_and()
        while self.accept("OP", "||") or self.accept("OR"):
            expression = BooleanOperation("or", expression, self.parse_and())
        return expression
    def parse_and(self) -> Expression:
        expression = self.parse_not()
        while self.accept("OP", "&&") or self.accept("AND"):
            expression = BooleanOperation("and", expression, self.parse_not())
        return expression
    def parse_not(self) -> Expression:
        if self.accept("NOT") or self.accept("OP", "!"):
            return Not(self.parse_not())
        return self.parse_comparison()
    def parse_comparison(self) -> Expression:
        left = self.parse_primary()
        token = self.current
        operator: Optional[str] = None
        if token.kind == "OP" and token.value in {
            "==",
            "=",
            "!=",
            ">",
            ">=",
            "<",
            "<=",
            "~",
            "~=",
            "=~",
            "!~",
        }:
            operator = str(self.advance().value)
        elif self.accept("IN"):
            operator = "in"
        elif token.kind == "NOT" and self.tokens[self.index + 1].kind == "IN":
            self.advance()
            self.advance()
            operator = "not in"
        if operator is None:
            return left
        if operator in ("in", "not in"):
            right = self.parse_list()
        else:
            right = self.parse_right_operand()
        return Comparison(operator, left, right)
    def parse_primary(self) -> Expression:
        if self.accept("("):
            expression = self.parse_or()
            self.expect(")")
            return expression
        token = self.current
        if token.kind == "IDENT":
            self.advance()
            return Field(token.value)
        if token.kind == "STRING":
            self.advance()
            return Literal(token.value)
        if token.kind == "NUMBER":
            self.advance()
            return Literal(token.value)
        if token.kind == "TRUE":
            self.advance()
            return Literal(True)
        if token.kind == "FALSE":
            self.advance()
            return Literal(False)
        if token.kind in ("NULL", "NONE"):
            self.advance()
            return Literal(None)
        raise _syntax_error(
            self.source,
            token.position,
            f"expected a field, literal, or parenthesized expression; "
            f"found {token.value!r}",
        )
    def parse_right_operand(self) -> Expression:
        token = self.current
        if token.kind == "IDENT":
            # Bare identifiers on the right side are convenient string
            # literals: ``level == ERROR`` is equivalent to ``level == 'ERROR'``.
            self.advance()
            return Literal(token.value)
        return self.parse_primary()
    def parse_list(self) -> Expression:
        closing = "]" if self.accept("[") else ")"
        if closing == ")":
            self.expect("(")
        values: List[Expression] = []
        if self.accept(closing):
            return ListValue(tuple(values))
        while True:
            values.append(self.parse_right_operand())
            if self.accept(closing):
                break
            self.expect(",")
        return ListValue(tuple(values))

@dataclass(frozen=True)
class FilterExpression:
    source: str
    expression: Expression
    def matches(self, record: Mapping[str, Any]) -> bool:
        return bool(self.expression.evaluate(record))
    __call__ = matches

def parse_filter(source: str) -> FilterExpression:
    """Compile a filter expression once for repeated record evaluation."""
    if not source.strip():
        raise FilterSyntaxError("filter expression cannot be empty")
    return FilterExpression(source, FilterParser(source).parse())

def matches_all(
    record: Mapping[str, Any],
    expressions: Sequence[FilterExpression],
) -> bool:
    return all(expression.matches(record) for expression in expressions)

def _matches_filter(
    record: Mapping[str, Any],
    field: str,
    expected: Set[str],
) -> bool:
    if not expected:
        return True
    value = get_path(record, field)
    return value is not None and str(value).casefold() in expected

def record_matches(
    record: Mapping[str, Any],
    *,
    services: Set[str],
    levels: Set[str],
    start: Optional[datetime],
    end: Optional[datetime],
    time_field: Optional[str],
    expression: Optional[FilterExpression] = None,
    expressions: Sequence[FilterExpression] = (),
    timestamp_parser: str = "auto",
    timestamp_formats: Sequence[str] = (),
) -> bool:
    """Apply legacy service/level/time filters and boolean expressions."""
    if not _matches_filter(record, "service", services):
        return False
    if not _matches_filter(record, "level", levels):
        return False
    if expression is not None and not expression.matches(record):
        return False
    if not matches_all(record, expressions):
        return False
    if start is None and end is None:
        return True
    timestamp = record_timestamp(
        record,
        time_field,
        parser=timestamp_parser,
        formats=timestamp_formats,
    )
    if timestamp is None:
        return False
    if start is not None and timestamp < start:
        return False
    if end is not None and timestamp >= end:
        return False
    return True

def select_fields(
    record: Mapping[str, Any],
    fields: Sequence[str],
) -> dict:
    """Select top-level fields while preserving nested field paths."""
    selected = {}
    for field in fields:
        if field in record:
            selected[field] = record[field]
        elif "." in field:
            selected[field] = get_path(record, field)
        else:
            selected[field] = None
    return selected
