"""Unit tests for the web access helper utilities."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from modules.tools.web_access import _capture_numeric_tokens


class CaptureNumericTokensTests(unittest.TestCase):
    """Exercise the numeric token extraction helper to guard against regressions."""

    def test_digits_are_preserved_in_order(self) -> None:
        tokens = _capture_numeric_tokens("rtx 4090 vs 7900 xtx")
        self.assertEqual(tokens, ["4090", "7900"])

    def test_mixed_alphanumeric_tokens_are_kept(self) -> None:
        tokens = _capture_numeric_tokens("should i buy s24 ultra")
        self.assertEqual(tokens, ["s24"])

    def test_query_with_numbers_only_returns_numbers(self) -> None:
        tokens = _capture_numeric_tokens("iphone 15 pro price")
        self.assertEqual(tokens, ["15"])

    def test_query_without_digits_returns_empty_list(self) -> None:
        tokens = _capture_numeric_tokens("best budget gpu")
        self.assertEqual(tokens, [])


if __name__ == "__main__":
    unittest.main()
