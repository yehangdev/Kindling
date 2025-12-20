import unittest

from kindling.filters import FilterSyntaxError, get_path, parse_filter, select_fields

class FilterParserTests(unittest.TestCase):
    def matches(self, expression, record):
        return parse_filter(expression).matches(record)
    def test_boolean_precedence_and_parentheses(self):
        record = {"level": "ERROR", "latency_ms": 20, "path": "/v2/items"}
        self.assertTrue(
            self.matches(
                'level == ERROR or latency_ms > 100 and path ~= "/v2"',
                record,
            )
        )
        self.assertFalse(
            self.matches(
                '(level == ERROR or latency_ms > 100) and path ~= "/v1"',
                record,
            )
        )
    def test_not_and_nested_field_comparison(self):
        record = {"request": {"path": "/health", "status": 204}}
        self.assertTrue(
            self.matches(
                'not request.path == "/health" or request.status >= 200',
                record,
            )
        )
        self.assertFalse(
            self.matches('request.path == "/health" and request.status < 200', record)
        )
    def test_in_list_and_boolean_literals(self):
        self.assertTrue(self.matches("level in [INFO, WARN]", {"level": "WARN"}))
        self.assertTrue(self.matches("enabled == true", {"enabled": True}))
        self.assertTrue(self.matches("deleted == null", {"deleted": None}))
    def test_regex_operators_are_case_insensitive(self):
        record = {"message": "Connection refused"}
        self.assertTrue(self.matches('message ~= "refused"', record))
        self.assertFalse(self.matches('message !~ "timeout"', record) is False)
    def test_missing_field_does_not_match_numeric_comparison(self):
        self.assertFalse(self.matches("latency_ms >= 10", {}))
        self.assertTrue(self.matches("latency_ms != 10", {}))
    def test_invalid_expression_reports_position(self):
        with self.assertRaises(FilterSyntaxError) as context:
            parse_filter("level ==")
        self.assertIn("position", str(context.exception))
    def test_select_fields_supports_dotted_paths(self):
        selected = select_fields(
            {"request": {"path": "/v1", "status": 200}},
            ["request.path", "missing"],
        )
        self.assertEqual(
            selected,
            {"request.path": "/v1", "missing": None},
        )
        self.assertEqual(get_path({"a": {"b": 2}}, "a.b"), 2)

if __name__ == "__main__":
    unittest.main()
