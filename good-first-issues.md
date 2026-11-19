# Good first issues

Seeded issues for new contributors. File each one on GitHub with
the `good first issue` and `help wanted` labels.

## 1. Add a top recoverable carts table

Title: Show the five highest-value recoverable carts

Description: After the per-status summary, print a short table
of the five abandoned carts with the highest totals that have
a reachable email (cart id, email, total, days since
abandoned), so a store owner can work the list top-down
without reading every finding. Duplicate cart ids are
counted once, keeping the first occurrence. Ties should
break by the oldest abandoned date first, then by cart id.

Difficulty: Easy

Acceptance criteria: the table appears in text output with the
correct top five for the sample file (C-114 first at $500.00,
then C-103, C-101, C-112, and C-110); JSON output is unchanged;
a test checks the table rows.

## 2. Add a recoverable value by day bucket

Title: Show recoverable value by abandonment age bucket

Description: Add a short table after the per-status summary
grouping abandoned carts with a reachable email into age
buckets (0 to 1 days, 2 to 7 days, 8 to 30 days, over 30
days), each with the cart count and the recoverable value,
so a store owner can see whether the money is fresh or
already cold. Buckets are counted from the abandoned_at
date against the as-of date. Duplicate cart ids are counted
once, and future-dated carts are left out of the buckets.

Difficulty: Easy

Acceptance criteria: the bucket table appears with the correct
counts and totals for the sample file (the 0 to 1 day bucket
holds C-101, C-110, and C-113; the over 30 day bucket holds
C-104 and C-114); JSON output is unchanged; a test checks
the bucket rows.

## 3. Support a custom repeat abandoner threshold

Title: Let the repeat abandoner count be configurable

Description: Add a --repeat-count flag that sets how many
abandoned carts make a customer a repeat abandoner, while
the duplicate-customer-cart warning keeps firing at two
carts. The default stays at three.

Difficulty: Easy

Acceptance criteria: a customer with two abandoned carts is
flagged as a repeat abandoner when --repeat-count 2 is
passed, and is not flagged without the flag; a test covers
both cases; README documents the flag.

## 4. Report the single biggest recoverable cart in the summary

Title: Print the largest recoverable cart

Description: Add one line to the text summary naming the
largest abandoned cart with a reachable email (cart id,
email, total, days since abandoned), so a store owner can
act on the best recovery first without reading every
finding. When no cart is recoverable, the line is omitted.

Difficulty: Easy

Acceptance criteria: the line appears for the sample file
naming C-114, Leo, $500.00, abandoned 58.6 days ago; it is
absent for the clean file; JSON output is unchanged; a test
checks both cases.
