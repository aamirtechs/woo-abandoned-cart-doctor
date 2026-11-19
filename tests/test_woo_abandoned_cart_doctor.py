"""Tests for woo-abandoned-cart-doctor."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import woo_abandoned_cart_doctor as wacd

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "examples")

AS_OF = datetime(2026, 11, 18, tzinfo=timezone.utc)

HEADER = ("cart_id,customer_email,customer_name,cart_total,items,"
          "status,abandoned_at,checkout_started_at\n")


def write_csv(content):
    """Write content to a temp CSV file and return its path."""
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".csv", delete=False, encoding="utf-8")
    handle.write(content)
    handle.close()
    return handle.name


def row(cart_id="C-1", email="ana@example.com", name="Ana",
        total="50.00", items="1", status="abandoned",
        abandoned="2026-11-17 09:00", checkout=""):
    """Build one CSV row with the standard columns."""
    return ",".join([cart_id, email, name, total, items, status,
                     abandoned, checkout]) + "\n"


def parse(content, as_of=AS_OF):
    """Parse CSV content and return (carts, findings)."""
    return wacd.parse_csv(write_csv(content), as_of)


def audit(content, as_of=AS_OF, **kwargs):
    """Parse CSV content and audit it, returning all findings."""
    carts, findings = parse(content, as_of)
    findings.extend(wacd.audit(carts, as_of, **kwargs))
    return carts, findings


def rules(findings):
    """Return the sorted rule names of a findings list."""
    return sorted(item.rule for item in findings)


def by_rule(findings, rule):
    """Return the findings with one rule name."""
    return [item for item in findings if item.rule == rule]


def run_cli(args):
    """Run the CLI with args, capturing stdout, returning (code, out)."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = wacd.main(args)
    return code, buffer.getvalue()


class TestParseTimestamp(unittest.TestCase):
    def test_iso_with_time(self):
        parsed = wacd.parse_timestamp("2026-11-17 09:00")
        self.assertEqual((parsed.year, parsed.month, parsed.day,
                          parsed.hour), (2026, 11, 17, 9))

    def test_iso_with_z(self):
        parsed = wacd.parse_timestamp("2026-11-17T09:00:00Z")
        self.assertEqual(parsed.tzinfo, timezone.utc)

    def test_date_only(self):
        parsed = wacd.parse_timestamp("2026-11-17")
        self.assertEqual((parsed.year, parsed.month, parsed.day),
                         (2026, 11, 17))

    def test_day_month_year(self):
        parsed = wacd.parse_timestamp("17/11/2026 09:00")
        self.assertEqual((parsed.day, parsed.month), (17, 11))

    def test_unreadable_returns_none(self):
        self.assertIsNone(wacd.parse_timestamp("not-a-date"))

    def test_empty_returns_none(self):
        self.assertIsNone(wacd.parse_timestamp(""))
        self.assertIsNone(wacd.parse_timestamp(None))


class TestParseAmount(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(wacd.parse_amount("249.99"),
                         Decimal("249.99"))

    def test_currency_symbol_and_commas(self):
        self.assertEqual(wacd.parse_amount("$1,249.99"),
                         Decimal("1249.99"))

    def test_unreadable_returns_none(self):
        self.assertIsNone(wacd.parse_amount("not-a-number"))

    def test_empty_returns_none(self):
        self.assertIsNone(wacd.parse_amount(""))
        self.assertIsNone(wacd.parse_amount(None))


class TestIsValidEmail(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(wacd.is_valid_email("ana@example.com"))

    def test_no_at(self):
        self.assertFalse(wacd.is_valid_email("not-an-email"))

    def test_no_domain_dot(self):
        self.assertFalse(wacd.is_valid_email("ana@example"))

    def test_empty(self):
        self.assertFalse(wacd.is_valid_email(""))

    def test_two_at_signs(self):
        self.assertFalse(wacd.is_valid_email("a@b@example.com"))


class TestParseCsv(unittest.TestCase):
    def test_header_aliases(self):
        content = ("id,email,total,abandoned\n"
                   "C-1,ana@example.com,50.00,2026-11-17 09:00\n")
        carts, findings = parse(content)
        self.assertEqual(len(carts), 1)
        self.assertEqual(carts[0]["id"], "C-1")
        self.assertEqual(carts[0]["email"], "ana@example.com")
        self.assertEqual(carts[0]["total"], Decimal("50.00"))

    def test_bom_header(self):
        content = "\ufeff" + HEADER + row()
        carts, findings = parse(content)
        self.assertEqual(len(carts), 1)

    def test_extra_columns_ignored(self):
        content = (HEADER.rstrip("\n") + ",coupon\n"
                   + row().rstrip("\n") + ",SAVE10\n")
        carts, findings = parse(content)
        self.assertEqual(len(carts), 1)
        self.assertEqual(findings, [])

    def test_missing_id_column(self):
        content = "email,total\nana@example.com,50.00\n"
        with self.assertRaises(ValueError):
            parse(content)

    def test_missing_total_column(self):
        content = "cart_id,email\nC-1,ana@example.com\n"
        with self.assertRaises(ValueError):
            parse(content)

    def test_missing_abandoned_column(self):
        content = "cart_id,email,total\nC-1,ana@example.com,50.00\n"
        with self.assertRaises(ValueError):
            parse(content)

    def test_empty_file(self):
        with self.assertRaises(ValueError):
            parse("")

    def test_unreadable_file(self):
        with self.assertRaises(ValueError):
            wacd.parse_csv("/nonexistent/carts.csv", AS_OF)

    def test_blank_lines_skipped(self):
        content = HEADER + "\n" + row() + "\n"
        carts, findings = parse(content)
        self.assertEqual(len(carts), 1)

    def test_malformed_row(self):
        content = HEADER + row() + row("C-2")[:-1] + ",extra\n"
        carts, findings = parse(content)
        self.assertEqual(len(carts), 1)
        self.assertEqual(rules(findings), ["malformed-row"])

    def test_duplicate_cart_id(self):
        content = HEADER + row("C-1") + row("C-1")
        carts, findings = parse(content)
        self.assertEqual(rules(findings), ["duplicate-cart-id"])

    def test_missing_cart_id(self):
        content = HEADER + row(cart_id="")
        carts, findings = parse(content)
        self.assertEqual(rules(findings), ["missing-cart-id"])

    def test_invalid_amount(self):
        content = HEADER + row(total="not-a-number")
        carts, findings = parse(content)
        self.assertEqual(rules(findings), ["invalid-amount"])
        self.assertIsNone(carts[0]["total"])

    def test_invalid_abandoned_date(self):
        content = HEADER + row(abandoned="not-a-date")
        carts, findings = parse(content)
        self.assertEqual(rules(findings), ["invalid-timestamp"])

    def test_invalid_checkout_date(self):
        content = HEADER + row(checkout="not-a-date")
        carts, findings = parse(content)
        self.assertEqual(rules(findings), ["invalid-timestamp"])

    def test_future_abandoned_date(self):
        content = HEADER + row(abandoned="2026-12-01 09:00")
        carts, findings = parse(content)
        self.assertEqual(rules(findings), ["future-timestamp"])


class TestAuditRules(unittest.TestCase):
    def test_high_value_recoverable(self):
        carts, findings = audit(HEADER + row(total="250.00"))
        self.assertEqual(rules(findings), ["high-value-recoverable"])

    def test_below_min_value_is_clean(self):
        carts, findings = audit(HEADER + row(total="99.99"))
        self.assertEqual(findings, [])

    def test_min_value_boundary(self):
        carts, findings = audit(HEADER + row(total="100.00"))
        self.assertIn("high-value-recoverable", rules(findings))

    def test_min_value_flag(self):
        carts, findings = audit(HEADER + row(total="250.00"),
                                min_value=Decimal("300.00"))
        self.assertEqual(findings, [])

    def test_no_email_error(self):
        carts, findings = audit(HEADER + row(email=""))
        self.assertEqual(rules(findings), ["no-email"])

    def test_invalid_email_error(self):
        carts, findings = audit(HEADER + row(email="not-an-email",
                                             total="120.00"))
        self.assertEqual(rules(findings), ["invalid-email"])

    def test_no_email_not_flagged_when_recovered(self):
        carts, findings = audit(HEADER + row(email="",
                                             status="recovered"))
        self.assertEqual(findings, [])

    def test_checkout_started(self):
        carts, findings = audit(
            HEADER + row(total="50.00", checkout="2026-11-17 08:30"))
        self.assertEqual(rules(findings), ["checkout-started"])

    def test_checkout_after_abandoned(self):
        carts, findings = audit(
            HEADER + row(checkout="2026-11-17 10:00"))
        self.assertEqual(rules(findings),
                         ["checkout-after-abandoned"])

    def test_stale_cart(self):
        carts, findings = audit(
            HEADER + row(total="40.00", abandoned="2026-10-01 09:00"))
        self.assertEqual(rules(findings), ["stale-cart"])

    def test_stale_days_flag(self):
        carts, findings = audit(
            HEADER + row(total="40.00", abandoned="2026-10-01 09:00"),
            stale_days=60)
        self.assertEqual(findings, [])

    def test_duplicate_customer_cart(self):
        content = HEADER + row("C-1", total="50.00") \
            + row("C-2", total="60.00")
        carts, findings = audit(content)
        self.assertEqual(rules(findings),
                         ["duplicate-customer-cart",
                          "duplicate-customer-cart"])

    def test_repeat_abandoner(self):
        content = HEADER + row("C-1", total="50.00") \
            + row("C-2", total="60.00") + row("C-3", total="70.00")
        carts, findings = audit(content)
        self.assertEqual(rules(findings),
                         ["duplicate-customer-cart"] * 3
                         + ["repeat-abandoner"] * 3)

    def test_two_carts_is_not_repeat_abandoner(self):
        content = HEADER + row("C-1", total="50.00") \
            + row("C-2", total="60.00")
        carts, findings = audit(content)
        self.assertNotIn("repeat-abandoner", rules(findings))

    def test_invalid_status(self):
        carts, findings = audit(HEADER + row(status="weird"))
        self.assertEqual(rules(findings), ["invalid-status"])

    def test_recovered_cart_is_clean(self):
        carts, findings = audit(
            HEADER + row(total="250.00", status="recovered"))
        self.assertEqual(findings, [])

    def test_purchased_cart_is_clean(self):
        carts, findings = audit(
            HEADER + row(total="250.00", status="purchased"))
        self.assertEqual(findings, [])

    def test_case_insensitive_email_grouping(self):
        content = HEADER + row("C-1", email="Ana@example.com") \
            + row("C-2", email="ana@example.com")
        carts, findings = audit(content)
        self.assertIn("duplicate-customer-cart", rules(findings))


class TestSummarize(unittest.TestCase):
    def test_sample_summary(self):
        path = os.path.join(EXAMPLES, "carts.csv")
        carts, findings = wacd.parse_csv(path, AS_OF)
        findings.extend(wacd.audit(carts, AS_OF))
        summary = wacd.summarize(carts, findings, AS_OF)
        self.assertEqual(summary["carts"], 21)
        self.assertEqual(summary["findings"], 34)
        self.assertEqual(summary["errors"], 11)
        self.assertEqual(summary["warnings"], 23)
        self.assertEqual(summary["abandoned"], 18)
        self.assertEqual(summary["recoverable_value"], "2244.46")
        self.assertEqual(summary["unrecoverable_value"], "369.00")
        self.assertEqual(summary["high_value_recoverable"], 7)
        self.assertEqual(summary["repeat_abandoners"], 1)

    def test_clean_summary(self):
        path = os.path.join(EXAMPLES, "clean.csv")
        carts, findings = wacd.parse_csv(path, AS_OF)
        findings.extend(wacd.audit(carts, AS_OF))
        summary = wacd.summarize(carts, findings, AS_OF)
        self.assertEqual(summary["findings"], 0)
        self.assertEqual(summary["recoverable_value"], "45.00")

    def test_per_status(self):
        path = os.path.join(EXAMPLES, "carts.csv")
        carts, findings = wacd.parse_csv(path, AS_OF)
        findings.extend(wacd.audit(carts, AS_OF))
        summary = wacd.summarize(carts, findings, AS_OF)
        statuses = {item["status"]: item["carts"]
                    for item in summary["per_status"]}
        self.assertEqual(statuses["abandoned"], 18)
        self.assertEqual(statuses["recovered"], 1)
        self.assertEqual(statuses["purchased"], 1)
        self.assertEqual(statuses["weird"], 1)


class TestCli(unittest.TestCase):
    def test_sample_text_output(self):
        path = os.path.join(EXAMPLES, "carts.csv")
        code, out = run_cli([path, "--as-of", "2026-11-18"])
        self.assertEqual(code, 0)
        self.assertIn("Carts: 21, findings: 34, errors: 11, "
                      "warnings: 23", out)
        self.assertIn("recoverable value: $2244.46", out)
        self.assertIn("unrecoverable value: $369.00", out)

    def test_check_exits_1_on_sample(self):
        path = os.path.join(EXAMPLES, "carts.csv")
        code, out = run_cli([path, "--as-of", "2026-11-18",
                             "--check"])
        self.assertEqual(code, 1)

    def test_clean_check_exits_0(self):
        path = os.path.join(EXAMPLES, "clean.csv")
        code, out = run_cli([path, "--as-of", "2026-11-18",
                             "--check"])
        self.assertEqual(code, 0)
        self.assertIn("All carts clean.", out)

    def test_warnings_only_check_exits_0(self):
        path = os.path.join(EXAMPLES, "warnings-only.csv")
        code, out = run_cli([path, "--as-of", "2026-11-18",
                             "--check"])
        self.assertEqual(code, 0)

    def test_warnings_only_strict_exits_1(self):
        path = os.path.join(EXAMPLES, "warnings-only.csv")
        code, out = run_cli([path, "--as-of", "2026-11-18",
                             "--check", "--strict"])
        self.assertEqual(code, 1)

    def test_json_output(self):
        path = os.path.join(EXAMPLES, "clean.csv")
        code, out = run_cli([path, "--as-of", "2026-11-18",
                             "--json"])
        self.assertEqual(code, 0)
        report = json.loads(out)
        self.assertEqual(report["carts"], 3)
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["recoverable_value"], "45.00")

    def test_json_findings_shape(self):
        path = os.path.join(EXAMPLES, "carts.csv")
        code, out = run_cli([path, "--as-of", "2026-11-18",
                             "--json"])
        report = json.loads(out)
        self.assertEqual(len(report["findings"]), 34)
        first = report["findings"][0]
        self.assertEqual(set(first), {"cart", "rule", "severity",
                                     "message"})

    def test_out_writes_file(self):
        path = os.path.join(EXAMPLES, "clean.csv")
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8")
        handle.close()
        code, out = run_cli([path, "--as-of", "2026-11-18",
                             "--out", handle.name])
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        with open(handle.name, encoding="utf-8") as reader:
            self.assertIn("All carts clean.", reader.read())
        os.unlink(handle.name)

    def test_missing_file_exits_2(self):
        code, out = run_cli(["/nonexistent/carts.csv"])
        self.assertEqual(code, 2)

    def test_bad_as_of_exits_2(self):
        path = os.path.join(EXAMPLES, "clean.csv")
        code, out = run_cli([path, "--as-of", "not-a-date"])
        self.assertEqual(code, 2)

    def test_bad_min_value_exits_2(self):
        path = os.path.join(EXAMPLES, "clean.csv")
        code, out = run_cli([path, "--min-value", "abc"])
        self.assertEqual(code, 2)

    def test_negative_stale_days_exits_2(self):
        path = os.path.join(EXAMPLES, "clean.csv")
        code, out = run_cli([path, "--stale-days", "-1"])
        self.assertEqual(code, 2)

    def test_min_value_flag_changes_output(self):
        path = os.path.join(EXAMPLES, "warnings-only.csv")
        code, out = run_cli([path, "--as-of", "2026-11-18",
                             "--min-value", "300.00"])
        self.assertIn("findings: 2, errors: 0, warnings: 2", out)


if __name__ == "__main__":
    unittest.main()
