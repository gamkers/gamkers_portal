"""Unit tests for CSV formula-injection neutralisation (CWE-1236)."""
import csv
import io
import unittest

from app.forms.csv_export import export_filename, iter_csv_rows, sanitize_csv_value


class SanitizeCsvValueTestCase(unittest.TestCase):
    def test_formula_triggers_are_prefixed(self):
        cases = {
            "=cmd|'/C calc'!A0": "'=cmd|'/C calc'!A0",
            "@SUM(1+1)": "'@SUM(1+1)",
            "-2+3": "'-2+3",
            "+12345-1": "'+12345-1",
            "\t=1+1": "'\t=1+1",
            "\r=1+1": "'\r=1+1",
            "\t-5": "'\t-5",
            "\r+5": "'\r+5",
            "  =1+1": "'  =1+1",
            "\n@SUM(A1)": "'\n@SUM(A1)",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(sanitize_csv_value(raw), expected)

    def test_safe_values_and_numeric_exemption(self):
        cases = {
            "Alex Hacker": "Alex Hacker",
            "a=b": "a=b",
            "user@example.com": "user@example.com",
            "50%": "50%",
            "%TEMP%": "%TEMP%",
            "": "",
            "   ": "   ",
            # Numeric exemption: plain signed integers and decimals are NOT escaped
            "-5": "-5",
            "+42": "+42",
            "-3.14": "-3.14",
            "+0.5": "+0.5",
            "-0": "-0",
            "+12345": "+12345",
            "  -5": "  -5",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(sanitize_csv_value(raw), expected)

    def test_non_string_values(self):
        self.assertEqual(sanitize_csv_value(None), "")
        self.assertEqual(sanitize_csv_value(42), "42")
        self.assertEqual(sanitize_csv_value(-5), "-5")
        self.assertEqual(sanitize_csv_value(-3.14), "-3.14")

    def test_lists_are_joined_then_sanitised_once(self):
        self.assertEqual(sanitize_csv_value(["-risky", "safe"]), "'-risky, safe")
        self.assertEqual(sanitize_csv_value(["safe", "-risky"]), "safe, -risky")
        self.assertEqual(sanitize_csv_value([]), "")


class IterCsvRowsTestCase(unittest.TestCase):
    def test_bom_then_sanitised_rows(self):
        chunks = list(iter_csv_rows([["Title", "=1+1"], [1, 'He said "hi", then left']]))
        self.assertEqual(chunks[0], "\ufeff")
        self.assertEqual(len(chunks), 3)
        parsed = list(csv.reader(io.StringIO("".join(chunks[1:]))))
        self.assertEqual(parsed, [["Title", "'=1+1"], ["1", 'He said "hi", then left']])


class ExportFilenameTestCase(unittest.TestCase):
    def test_ascii_slug(self):
        self.assertEqual(
            export_filename(7, "Gamkers CTF 2026 Registration"),
            "responses_7_Gamkers_CTF_2026_Registration.csv",
        )

    def test_non_ascii_title_is_header_safe(self):
        name = export_filename(3, 'Café தமிழ் "x"')
        self.assertTrue(name.isascii())
        self.assertNotIn('"', name)
        self.assertEqual(name, "responses_3_Caf_x.csv")

    def test_empty_slug_falls_back(self):
        self.assertEqual(export_filename(9, "தமிழ்"), "responses_9_form.csv")
        self.assertEqual(export_filename(9, ""), "responses_9_form.csv")

    def test_slug_is_truncated_to_30_chars(self):
        name = export_filename(1, "A" * 100)
        self.assertEqual(name, f"responses_1_{'A' * 30}.csv")


if __name__ == "__main__":
    unittest.main()
