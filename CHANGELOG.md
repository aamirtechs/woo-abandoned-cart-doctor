# Changelog

## 1.0.0 - 2026-11-19

Initial release.

* Recoverable value audit over a WooCommerce abandoned carts
  CSV export: high-value carts with a reachable email,
  carts abandoned after checkout started, repeat abandoners,
  duplicate carts for one customer, and stale carts past the
  recovery window.
* Recoverable and unrecoverable value totals with exact
  Decimal money math, plus the high-value recoverable count
  and the repeat abandoner count.
* Data quality checks: carts with no email or an invalid
  email, duplicate and missing cart ids, malformed rows,
  invalid amounts and timestamps, future timestamps,
  checkout dates after the abandoned date, and unknown
  statuses.
* A per-status summary table.
* Defensive timestamp parsing (ISO 8601 with or without a
  timezone, plus common day/month/year forms) and amount
  parsing (currency symbols and thousands separators); a
  bad row is reported as a finding and never crashes the
  run. UTF-8 BOM headers and extra columns handled.
* Findings carry a cart id, a rule name, a severity (error
  or warning), and a message; errors and warnings are counted
  in the summary.
* Text and --json output, --out file output, --min-value,
  --stale-days, and --as-of thresholds, and a --check CI
  gate that exits 1 on errors (and on warnings with
  --strict).
* Zero dependencies, Python 3.10 or newer.
