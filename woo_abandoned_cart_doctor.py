"""WooCommerce abandoned cart audit CLI.

Reads a WooCommerce abandoned carts CSV export (from a cart
abandonment plugin or an orders export filtered to abandoned
carts) and audits every cart for recoverable value: high-value
carts with a reachable email, repeat abandoners, carts
abandoned after checkout started, carts with no email at all
(unrecoverable), stale carts past the recovery window,
duplicate carts for one customer, and bad data such as
duplicate cart ids, malformed rows, and invalid amounts or
dates.

Baymard puts the average documented cart abandonment rate at
70.22% across 50 studies, and estimates $260 billion in
recoverable orders in the US and EU. Recovery plugins recover
carts inside WordPress, but nobody audits the exported carts
file first to say which carts are actually worth chasing.
This tool is that audit: it ranks the recoverable value in
the export alone, and never touches your store.

Each problem is a finding with a cart id, a rule name, a
severity (error or warning), and a message. Errors are carts
that cannot be recovered or data that cannot be trusted;
warnings are recoverable value and patterns worth chasing.
--check exits 1 when any error is found, and --strict also
fails on warnings.

Money is handled with Decimal, so totals add up exactly.
Dates are parsed defensively. A bad date or amount is
reported as a finding and the row is still audited on the
fields that did parse, so one bad row never crashes the run.

Zero dependencies, Python 3.10 or newer, standard library only.

Usage:
    python3 woo_abandoned_cart_doctor.py examples/carts.csv
    python3 woo_abandoned_cart_doctor.py carts.csv --json --check
    python3 woo_abandoned_cart_doctor.py carts.csv --as-of 2026-11-18
"""

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

__version__ = "1.0.0"

DEFAULT_MIN_VALUE = Decimal("100.00")
DEFAULT_STALE_DAYS = 30
DEFAULT_REPEAT_COUNT = 3

KNOWN_STATUSES = {"abandoned", "recovered", "purchased", "active"}

TIMESTAMP_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M",
    "%m/%d/%Y %H:%M",
    "%d/%m/%Y",
    "%m/%d/%Y",
)


class Finding:
    """One audit finding for one cart, or for the cart set."""

    def __init__(self, cart, rule, severity, message):
        self.cart = cart
        self.rule = rule
        self.severity = severity
        self.message = message

    def as_dict(self):
        """Return the finding as a plain dict."""
        return {"cart": self.cart, "rule": self.rule,
                "severity": self.severity, "message": self.message}

    def __str__(self):
        return "%s [%s] %s: %s" % (self.severity.upper(), self.rule,
                                   self.cart, self.message)


def parse_timestamp(text):
    """Parse a timestamp string into an aware datetime, or None.

    Accepts ISO 8601 with or without a timezone (a trailing Z is
    handled), plus a few common export formats. A naive timestamp
    is read as UTC. Returns None for an empty string or a value
    that matches no known format, so callers can report it
    instead of crashing.
    """
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    candidate = text
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        parsed = None
    if parsed is None:
        for fmt in TIMESTAMP_FORMATS:
            try:
                parsed = datetime.strptime(candidate, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def parse_amount(text):
    """Parse a money string into a Decimal, or None.

    Accepts plain numbers with an optional currency symbol or
    thousands separators (for example "$1,249.99"). Returns None
    for an empty string or a value that is not a number.
    """
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    cleaned = text.replace("$", "").replace(",", "").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def is_valid_email(email):
    """Return True when an email looks reachable.

    A reachable email has one @, a non-empty local part, and a
    domain with at least one dot. This is a deliverability
    smell check, not a full RFC validation.
    """
    if not email:
        return False
    if email.count("@") != 1:
        return False
    local, domain = email.split("@")
    if not local or not domain:
        return False
    if "." not in domain:
        return False
    if domain.startswith(".") or domain.endswith("."):
        return False
    if " " in email:
        return False
    return True


def find_column(header, names):
    """Return the first of names present in header, or None."""
    for name in names:
        if name in header:
            return name
    return None


def parse_csv(path, as_of):
    """Parse a WooCommerce abandoned carts CSV export.

    Returns (carts, findings). Each cart is a dict with the id,
    email, name, total, item count, status, and the parsed
    dates. Rows with the wrong number of fields are reported as
    malformed-row errors and skipped, never a crash. A UTF-8
    BOM header is handled. Extra columns are ignored.
    """
    findings = []
    carts = []
    try:
        handle = open(path, newline="", encoding="utf-8-sig")
    except OSError as exc:
        raise ValueError("cannot read %s: %s" % (path, exc))
    with handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError("%s is empty, no header row found" % path)
        except csv.Error as exc:
            raise ValueError("%s is not a readable CSV file: %s"
                             % (path, exc))
        header = [name.strip() for name in header]
        id_column = find_column(header, ("cart_id", "id", "order_id"))
        if id_column is None:
            raise ValueError(
                "%s has no cart_id or id column (header is: %s)"
                % (path, ", ".join(header)))
        email_column = find_column(
            header, ("customer_email", "email", "billing_email"))
        total_column = find_column(
            header, ("cart_total", "total", "amount", "order_total"))
        if total_column is None:
            raise ValueError(
                "%s has no cart_total or total column "
                "(header is: %s)" % (path, ", ".join(header)))
        name_column = find_column(
            header, ("customer_name", "name", "billing_name"))
        items_column = find_column(
            header, ("items", "items_count", "item_count", "line_items"))
        status_column = find_column(header, ("status", "cart_status"))
        abandoned_column = find_column(
            header, ("abandoned_at", "date_abandoned", "abandoned",
                     "created_at"))
        if abandoned_column is None:
            raise ValueError(
                "%s has no abandoned_at column "
                "(header is: %s)" % (path, ", ".join(header)))
        checkout_column = find_column(
            header, ("checkout_started_at", "checkout_started",
                     "checkout_at"))
        seen_ids = set()
        for line_number, row in enumerate(reader, start=2):
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) != len(header):
                findings.append(Finding(
                    "row %d" % line_number, "malformed-row", "error",
                    "row has %d fields but the header has %d, "
                    "so the row was skipped" % (len(row), len(header))))
                continue
            cells = dict(zip(header, (cell.strip() for cell in row)))
            cart_id = cells[id_column]
            if not cart_id:
                findings.append(Finding(
                    "row %d" % line_number, "missing-cart-id", "error",
                    "row has no cart id, so the cart cannot be "
                    "matched to a recovery email"))
                cart_id = "row %d" % line_number
            if cart_id in seen_ids:
                findings.append(Finding(
                    cart_id, "duplicate-cart-id", "error",
                    "cart id appears more than once in the export"))
            else:
                seen_ids.add(cart_id)
            email = cells[email_column] if email_column else ""
            total_raw = cells[total_column]
            total = parse_amount(total_raw)
            if total_raw and total is None:
                findings.append(Finding(
                    cart_id, "invalid-amount", "error",
                    "cart_total %r is not a readable amount"
                    % total_raw))
            abandoned_raw = cells[abandoned_column]
            abandoned_at = None
            if abandoned_raw:
                abandoned_at = parse_timestamp(abandoned_raw)
                if abandoned_at is None:
                    findings.append(Finding(
                        cart_id, "invalid-timestamp", "error",
                        "abandoned_at %r is not a readable date"
                        % abandoned_raw))
            checkout_at = None
            if checkout_column:
                checkout_raw = cells[checkout_column]
                if checkout_raw:
                    checkout_at = parse_timestamp(checkout_raw)
                    if checkout_at is None:
                        findings.append(Finding(
                            cart_id, "invalid-timestamp", "error",
                            "checkout_started_at %r is not a "
                            "readable date" % checkout_raw))
            if abandoned_at is not None and abandoned_at > as_of:
                findings.append(Finding(
                    cart_id, "future-timestamp", "error",
                    "abandoned_at %s is after the as-of date %s"
                    % (abandoned_at.strftime("%Y-%m-%d %H:%M"),
                       as_of.strftime("%Y-%m-%d %H:%M"))))
            carts.append({
                "id": cart_id,
                "email": email,
                "name": (cells[name_column] if name_column else ""),
                "total": total,
                "total_raw": total_raw,
                "items": (cells[items_column]
                          if items_column else ""),
                "status": (cells[status_column].lower()
                           if status_column else ""),
                "abandoned_at": abandoned_at,
                "abandoned_raw": abandoned_raw,
                "checkout_at": checkout_at,
                "line": line_number})
    return carts, findings


def audit(carts, as_of, min_value=DEFAULT_MIN_VALUE,
          stale_days=DEFAULT_STALE_DAYS,
          repeat_count=DEFAULT_REPEAT_COUNT):
    """Audit a parsed cart list and return a list of findings."""
    findings = []
    abandoned_by_email = {}
    for cart in carts:
        if cart["status"] == "abandoned" and cart["email"]:
            key = cart["email"].lower()
            abandoned_by_email[key] = \
                abandoned_by_email.get(key, 0) + 1
    for cart in carts:
        cart_id = cart["id"]
        status = cart["status"]
        email = cart["email"]
        total = cart["total"]
        abandoned_at = cart["abandoned_at"]
        checkout_at = cart["checkout_at"]

        if status and status not in KNOWN_STATUSES:
            findings.append(Finding(
                cart_id, "invalid-status", "error",
                "status %r is not a known cart status"
                % status))
        if status == "abandoned":
            if not email:
                findings.append(Finding(
                    cart_id, "no-email", "error",
                    "cart has no customer email, so it cannot be "
                    "recovered by email"))
            elif not is_valid_email(email):
                findings.append(Finding(
                    cart_id, "invalid-email", "error",
                    "customer email %r is not a reachable email "
                    "address" % email))
            if abandoned_at is not None:
                age_days = (as_of - abandoned_at).total_seconds() \
                    / 86400.0
                if age_days > stale_days:
                    findings.append(Finding(
                        cart_id, "stale-cart", "warning",
                        "cart was abandoned %.1f days ago, past "
                        "the %d day recovery window, so recovery "
                        "emails are unlikely to convert"
                        % (age_days, stale_days)))
            if checkout_at is not None:
                if abandoned_at is not None \
                        and checkout_at > abandoned_at:
                    findings.append(Finding(
                        cart_id, "checkout-after-abandoned", "error",
                        "checkout_started_at %s is after "
                        "abandoned_at %s, so the dates cannot both "
                        "be right"
                        % (checkout_at.strftime("%Y-%m-%d %H:%M"),
                           abandoned_at.strftime("%Y-%m-%d %H:%M"))))
                else:
                    findings.append(Finding(
                        cart_id, "checkout-started", "warning",
                        "cart was abandoned after checkout "
                        "started, so the customer was close to "
                        "buying"))
            if email and is_valid_email(email) \
                    and total is not None and total >= min_value:
                findings.append(Finding(
                    cart_id, "high-value-recoverable", "warning",
                    "cart is worth $%s with a reachable email, "
                    "so it is worth a recovery email"
                    % format(total, ".2f")))
            if email:
                count = abandoned_by_email.get(email.lower(), 0)
                if count >= 2:
                    findings.append(Finding(
                        cart_id, "duplicate-customer-cart", "warning",
                        "customer %s has %d abandoned carts in "
                        "this export, so an older cart may already "
                        "have been superseded" % (email, count)))
                if count >= repeat_count:
                    findings.append(Finding(
                        cart_id, "repeat-abandoner", "warning",
                        "customer %s has abandoned %d carts, so "
                        "they are a repeat abandoner, not a "
                        "one-off" % (email, count)))
    return findings


def summarize(carts, findings, as_of,
              min_value=DEFAULT_MIN_VALUE,
              stale_days=DEFAULT_STALE_DAYS):
    """Return the summary counts for a cart list and findings."""
    errors = sum(1 for item in findings if item.severity == "error")
    warnings = sum(1 for item in findings
                   if item.severity == "warning")
    abandoned = [cart for cart in carts
                 if cart["status"] == "abandoned"]
    recoverable = Decimal("0.00")
    unrecoverable = Decimal("0.00")
    high_value = 0
    for cart in abandoned:
        if cart["total"] is None:
            continue
        if cart["email"] and is_valid_email(cart["email"]):
            recoverable += cart["total"]
            if cart["total"] >= min_value:
                high_value += 1
        else:
            unrecoverable += cart["total"]
    emails = {}
    for cart in abandoned:
        if cart["email"]:
            emails[cart["email"].lower()] = \
                emails.get(cart["email"].lower(), 0) + 1
    repeat_abandoners = sum(1 for count in emails.values()
                            if count >= DEFAULT_REPEAT_COUNT)
    per_status = {}
    for cart in carts:
        status = cart["status"] or "(no status)"
        per_status[status] = per_status.get(status, 0) + 1
    statuses = sorted(per_status.items())
    return {"carts": len(carts),
            "findings": len(findings),
            "errors": errors,
            "warnings": warnings,
            "abandoned": len(abandoned),
            "recoverable_value": str(recoverable),
            "unrecoverable_value": str(unrecoverable),
            "high_value_recoverable": high_value,
            "repeat_abandoners": repeat_abandoners,
            "per_status": [{"status": status, "carts": count}
                           for status, count in statuses]}


def render_text(carts, findings, summary):
    """Render the text report."""
    lines = [str(item) for item in findings]
    lines.append("")
    lines.append("Carts: %(carts)d, findings: %(findings)d, "
                 "errors: %(errors)d, warnings: %(warnings)d"
                 % summary)
    lines.append("Abandoned carts: %(abandoned)d, recoverable "
                 "value: $%(recoverable_value)s, unrecoverable "
                 "value: $%(unrecoverable_value)s" % summary)
    lines.append("High-value recoverable carts: "
                 "%(high_value_recoverable)d, repeat abandoners: "
                 "%(repeat_abandoners)d" % summary)
    lines.append("")
    lines.append("Per-status summary:")
    for row in summary["per_status"]:
        lines.append("%s: %d carts" % (row["status"], row["carts"]))
    if summary["findings"] == 0:
        lines.append("")
        lines.append("All carts clean.")
    return "\n".join(lines) + "\n"


def render_json(carts, findings, summary):
    """Render the JSON report."""
    report = dict(summary)
    report["findings"] = [item.as_dict() for item in findings]
    return json.dumps(report, indent=2) + "\n"


def build_parser():
    """Build the command line parser."""
    parser = argparse.ArgumentParser(
        prog="woo-abandoned-cart-doctor",
        description="Audit a WooCommerce abandoned carts CSV "
                    "export for recoverable value and cart "
                    "problems.")
    parser.add_argument("csv_file", help="abandoned carts CSV "
                        "export to audit")
    parser.add_argument("--min-value", type=str,
                        default=str(DEFAULT_MIN_VALUE),
                        help="a cart worth at least this much with "
                        "a reachable email is high value "
                        "(default: %(default)s)")
    parser.add_argument("--stale-days", type=int,
                        default=DEFAULT_STALE_DAYS,
                        help="a cart abandoned more than this many "
                        "days ago is stale "
                        "(default: %d)" % DEFAULT_STALE_DAYS)
    parser.add_argument("--as-of", default=None,
                        help="date to compare timestamps against, "
                        "for example 2026-11-18 (default: now)")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON instead of text")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if any error is found")
    parser.add_argument("--strict", action="store_true",
                        help="with --check, also exit 1 on warnings")
    parser.add_argument("--out", default=None,
                        help="write the report to a file")
    return parser


def main(argv=None):
    """Run the CLI and return the exit code."""
    args = build_parser().parse_args(argv)
    try:
        min_value = Decimal(args.min_value)
    except InvalidOperation:
        print("error: --min-value %r is not a readable amount"
              % args.min_value, file=sys.stderr)
        return 2
    if min_value < 0:
        print("error: --min-value must be at least 0",
              file=sys.stderr)
        return 2
    if args.stale_days < 0:
        print("error: --stale-days must be at least 0",
              file=sys.stderr)
        return 2
    if args.as_of is None:
        as_of = datetime.now(timezone.utc)
    else:
        as_of = parse_timestamp(args.as_of)
        if as_of is None:
            print("error: --as-of %r is not a readable date"
                  % args.as_of, file=sys.stderr)
            return 2
    try:
        carts, findings = parse_csv(args.csv_file, as_of)
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    findings.extend(audit(carts, as_of,
                          min_value=min_value,
                          stale_days=args.stale_days))
    summary = summarize(carts, findings, as_of,
                        min_value=min_value,
                        stale_days=args.stale_days)
    if args.json:
        report = render_json(carts, findings, summary)
    else:
        report = render_text(carts, findings, summary)
    if args.out is not None:
        try:
            with open(args.out, "w", encoding="utf-8") as handle:
                handle.write(report)
        except OSError as exc:
            print("error: cannot write %s: %s" % (args.out, exc),
                  file=sys.stderr)
            return 2
    else:
        sys.stdout.write(report)
    if args.check:
        if summary["errors"] > 0:
            return 1
        if args.strict and summary["warnings"] > 0:
            return 1
    return 0


def main_entry():
    """Console script entry point."""
    sys.exit(main())


if __name__ == "__main__":
    main_entry()
