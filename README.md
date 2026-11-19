# woo-abandoned-cart-doctor

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/aamirtechs/woo-abandoned-cart-doctor/blob/main/LICENSE) [![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/aamirtechs/woo-abandoned-cart-doctor/issues)

A zero-dependency Python CLI that audits a WooCommerce
abandoned carts CSV export for recoverable value: high-value
carts with a reachable email, repeat abandoners, carts
abandoned after checkout started, carts with no email at all
(unrecoverable), stale carts past the recovery window,
duplicate carts for one customer, and bad data such as
duplicate cart ids, malformed rows, invalid amounts, and
invalid or future dates. It totals the recoverable and
unrecoverable value in the export, so a store owner can see
which carts are worth chasing before sending a single
recovery email.

Baymard puts the average documented cart abandonment rate at
70.22% across 50 studies, and estimates $260 billion in
recoverable orders in the US and EU. Recovery plugins and
SaaS recover carts inside WordPress, but nobody audits the
exported carts file first to say which carts are actually
worth chasing. This tool is that audit: it ranks the
recoverable value in the export alone, and never touches your
store.

## Install

Requires Python 3.10 or newer. No dependencies beyond the
standard library.

```bash
pip install woo-abandoned-cart-doctor
```

Or run it straight from the source checkout:

```bash
python3 woo_abandoned_cart_doctor.py examples/carts.csv
```

## Input format

A CSV export with a header row, from a cart abandonment
plugin or an orders export filtered to abandoned carts.
Columns used: `cart_id` (or `id`), `customer_email` (or
`email`), `customer_name`, `cart_total` (or `total`),
`items`, `status`, `abandoned_at`, and
`checkout_started_at`. Extra columns are ignored, so a full
carts export works as-is. A UTF-8 BOM header is handled.
Only `cart_id`, `cart_total`, and `abandoned_at` are
required; the other columns are optional, and the checks
that need a missing column are skipped.

`abandoned_at` also accepts `date_abandoned`, `abandoned`,
or `created_at` as the column name, `cart_total` also
accepts `amount` or `order_total`, and `customer_email`
also accepts `billing_email`.

Dates accept ISO 8601 with or without a timezone
(`2026-11-17 10:00`, `2026-11-17T10:00:00Z`,
`2026-11-17`), plus day/month/year and month/day/year
forms. A date with no timezone is read as UTC. Amounts
accept a plain number with an optional currency symbol or
thousands separators (`$1,249.99`).

```csv
cart_id,customer_email,customer_name,cart_total,items,status,abandoned_at,checkout_started_at
C-101,ana@example.com,Ana,249.99,3,abandoned,2026-11-17 10:00,2026-11-17 09:45
C-102,ben@example.com,Ben,45.00,1,abandoned,2026-11-16 09:00,
C-103,cara@example.com,Cara,320.50,5,abandoned,2026-11-10 09:00,2026-11-10 08:30
C-104,dan@example.com,Dan,129.00,2,abandoned,2026-10-01 09:00,
C-105,,Eve,189.00,2,abandoned,2026-11-15 09:00,
```

## What it checks

Errors, the ones that mean a cart cannot be recovered or
data that cannot be trusted:

* `no-email`: an abandoned cart with no customer email, so
  it cannot be recovered by email. Recovered and purchased
  carts are exempt.
* `invalid-email`: an abandoned cart whose email has no
  `@`, no domain dot, or another obvious defect, so it is
  not a reachable address.
* `duplicate-cart-id`: the same cart id twice in the
  export.
* `missing-cart-id`: a row with no cart id, so the cart
  cannot be matched to a recovery email.
* `invalid-amount`: a `cart_total` that is not a readable
  number. The row is still audited on the fields that did
  parse.
* `invalid-timestamp`: a date field that matches no known
  format. The row is still audited on the fields that did
  parse.
* `future-timestamp`: an `abandoned_at` after `--as-of`
  (default now).
* `checkout-after-abandoned`: `checkout_started_at` later
  than `abandoned_at`, so the dates cannot both be right.
* `invalid-status`: a status that is not a known cart
  status (abandoned, recovered, purchased, active).
* `malformed-row`: a row with the wrong number of fields.
  The row is skipped and reported, never a crash.

Warnings, recoverable value and patterns worth chasing:

* `high-value-recoverable`: an abandoned cart worth at
  least `--min-value` (default $100.00) with a reachable
  email, so it is worth a recovery email.
* `checkout-started`: a cart abandoned after checkout
  started, so the customer was close to buying.
* `stale-cart`: a cart abandoned more than `--stale-days`
  (default 30) ago, past the recovery window, so recovery
  emails are unlikely to convert.
* `duplicate-customer-cart`: a customer with two or more
  abandoned carts in the export, so an older cart may
  already have been superseded.
* `repeat-abandoner`: a customer with three or more
  abandoned carts, so they are a repeat abandoner, not a
  one-off.

The summary reports the recoverable value (abandoned carts
with a reachable email), the unrecoverable value (abandoned
carts with no email or an invalid email), the high-value
recoverable count, the repeat abandoner count, and a
per-status table. Money is added with Decimal, so totals
add up exactly.

## Usage

```bash
python3 woo_abandoned_cart_doctor.py examples/carts.csv --as-of 2026-11-18
```

Captured output:

```
ERROR [invalid-amount] C-108: cart_total 'not-a-number' is not a readable amount
ERROR [invalid-timestamp] C-109: abandoned_at 'not-a-date' is not a readable date
ERROR [future-timestamp] C-116: abandoned_at 2026-12-01 09:00 is after the as-of date 2026-11-18 00:00
ERROR [duplicate-cart-id] C-101: cart id appears more than once in the export
ERROR [malformed-row] row 20: row has 9 fields but the header has 8, so the row was skipped
ERROR [missing-cart-id] row 21: row has no cart id, so the cart cannot be matched to a recovery email
WARNING [checkout-started] C-101: cart was abandoned after checkout started, so the customer was close to buying
WARNING [high-value-recoverable] C-101: cart is worth $249.99 with a reachable email, so it is worth a recovery email
WARNING [duplicate-customer-cart] C-101: customer ana@example.com has 4 abandoned carts in this export, so an older cart may already have been superseded
WARNING [repeat-abandoner] C-101: customer ana@example.com has abandoned 4 carts, so they are a repeat abandoner, not a one-off
WARNING [checkout-started] C-103: cart was abandoned after checkout started, so the customer was close to buying
WARNING [high-value-recoverable] C-103: cart is worth $320.50 with a reachable email, so it is worth a recovery email
WARNING [stale-cart] C-104: cart was abandoned 47.6 days ago, past the 30 day recovery window, so recovery emails are unlikely to convert
WARNING [high-value-recoverable] C-104: cart is worth $129.00 with a reachable email, so it is worth a recovery email
ERROR [no-email] C-105: cart has no customer email, so it cannot be recovered by email
WARNING [checkout-started] C-106: cart was abandoned after checkout started, so the customer was close to buying
WARNING [duplicate-customer-cart] C-106: customer ana@example.com has 4 abandoned carts in this export, so an older cart may already have been superseded
WARNING [repeat-abandoner] C-106: customer ana@example.com has abandoned 4 carts, so they are a repeat abandoner, not a one-off
WARNING [checkout-started] C-110: cart was abandoned after checkout started, so the customer was close to buying
WARNING [high-value-recoverable] C-110: cart is worth $150.00 with a reachable email, so it is worth a recovery email
WARNING [high-value-recoverable] C-112: cart is worth $210.00 with a reachable email, so it is worth a recovery email
WARNING [duplicate-customer-cart] C-112: customer ana@example.com has 4 abandoned carts in this export, so an older cart may already have been superseded
WARNING [repeat-abandoner] C-112: customer ana@example.com has abandoned 4 carts, so they are a repeat abandoner, not a one-off
WARNING [stale-cart] C-114: cart was abandoned 58.6 days ago, past the 30 day recovery window, so recovery emails are unlikely to convert
WARNING [checkout-started] C-114: cart was abandoned after checkout started, so the customer was close to buying
WARNING [high-value-recoverable] C-114: cart is worth $500.00 with a reachable email, so it is worth a recovery email
ERROR [no-email] C-115: cart has no customer email, so it cannot be recovered by email
ERROR [invalid-status] C-117: status 'weird' is not a known cart status
WARNING [checkout-started] C-101: cart was abandoned after checkout started, so the customer was close to buying
WARNING [high-value-recoverable] C-101: cart is worth $249.99 with a reachable email, so it is worth a recovery email
WARNING [duplicate-customer-cart] C-101: customer ana@example.com has 4 abandoned carts in this export, so an older cart may already have been superseded
WARNING [repeat-abandoner] C-101: customer ana@example.com has abandoned 4 carts, so they are a repeat abandoner, not a one-off
ERROR [invalid-email] C-119: customer email 'not-an-email' is not a reachable email address
ERROR [checkout-after-abandoned] C-120: checkout_started_at 2026-11-14 10:00 is after abandoned_at 2026-11-14 09:00, so the dates cannot both be right

Carts: 21, findings: 34, errors: 11, warnings: 23
Abandoned carts: 18, recoverable value: $2244.46, unrecoverable value: $369.00
High-value recoverable carts: 7, repeat abandoners: 1

Per-status summary:
abandoned: 18 carts
purchased: 1 carts
recovered: 1 carts
weird: 1 carts
```

The sample has 22 rows; the malformed row 20 is skipped, so
21 carts are audited. The headline numbers are $2,244.46
of recoverable value across 18 abandoned carts, $369.00
unrecoverable (two carts with no email and one with an
invalid email), 7 high-value recoverable carts, and 1
repeat abandoner, Ana with 4 abandoned carts. The $500 cart
C-114 is both high value and stale, so it is worth one
last recovery attempt, not a sequence.

Use it as a CI gate: `--check` exits 1 when any error is
found, and 0 otherwise. On the sample above it exits 1:

```bash
python3 woo_abandoned_cart_doctor.py examples/carts.csv --as-of 2026-11-18 --check
```

On `examples/clean.csv`, three clean carts, it exits 0:

```
Carts: 3, findings: 0, errors: 0, warnings: 0
Abandoned carts: 1, recoverable value: $45.00, unrecoverable value: $0.00
High-value recoverable carts: 0, repeat abandoners: 0

Per-status summary:
abandoned: 1 carts
purchased: 1 carts
recovered: 1 carts

All carts clean.
```

With `--strict`, `--check` also fails on warnings.
`examples/warnings-only.csv` has one high-value cart
abandoned after checkout started and one stale cart, so it
passes `--check` (exit 0) and fails `--check --strict`
(exit 1). With a higher value threshold the high-value
warning drops out:

```bash
python3 woo_abandoned_cart_doctor.py examples/warnings-only.csv --as-of 2026-11-18 --min-value 300.00
```

Captured output:

```
WARNING [checkout-started] C-301: cart was abandoned after checkout started, so the customer was close to buying
WARNING [stale-cart] C-302: cart was abandoned 38.6 days ago, past the 30 day recovery window, so recovery emails are unlikely to convert

Carts: 2, findings: 2, errors: 0, warnings: 2
Abandoned carts: 2, recoverable value: $290.00, unrecoverable value: $0.00
High-value recoverable carts: 0, repeat abandoners: 0

Per-status summary:
abandoned: 2 carts
```

`--json` emits the summary and the findings as JSON, and
`--out` writes the report to a file.

## Options

| Flag | Meaning |
| --- | --- |
| `--min-value` | A cart worth at least this much with a reachable email is high value (default: 100.00) |
| `--stale-days` | A cart abandoned more than this many days ago is stale (default: 30) |
| `--as-of` | Date to compare timestamps against, for example 2026-11-18 (default: now) |
| `--json` | Emit JSON instead of text |
| `--check` | Exit 1 if any error is found |
| `--strict` | With --check, also exit 1 on warnings |
| `--out` | Write the report to a file |

## Edge cases

* A row with too many or too few fields is a malformed-row
  error and is skipped; the rest of the file is still
  audited.
* A bad amount or date is an error, and the row is still
  audited on the fields that did parse, so one bad value
  never hides the other problems on the cart. A cart with
  an unreadable amount is left out of both value totals.
* Email grouping is case-insensitive, so Ana@example.com
  and ana@example.com count as one customer.
* A cart with no email is an error only when its status is
  abandoned; recovered and purchased carts do not need a
  recovery email.
* A cart abandoned in the future (after `--as-of`) is a
  future-timestamp error, and its age is negative, so it
  never also fires the stale-cart warning.
* A blank line in the file is skipped silently. A cart with
  no status is grouped under `(no status)` in the
  per-status table.
* `--as-of` makes runs reproducible: without it, the
  future-timestamp check compares against the current time.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

65 tests, all passing: timestamp and amount parsing, email
validation, header aliases and BOM handling, malformed rows,
duplicate and missing cart ids, invalid amounts and
timestamps, future timestamps, no-email and invalid-email
rules, high-value and min-value thresholds, checkout-started
and checkout-after-abandoned rules, stale-cart windows,
duplicate-customer and repeat-abandoner grouping, invalid
statuses, summary totals and per-status tables, text and
JSON output, `--out` file output, and `--check` and
`--strict` exit codes. The same 65 tests pass under pytest.

## License

MIT. See [LICENSE](LICENSE).
