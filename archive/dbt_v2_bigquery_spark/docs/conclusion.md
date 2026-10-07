# Moving from BigQuery to Spark: what we found

*For the person deciding whether to make the move. The construct-by-construct evidence is in
`bigquery-to-spark.md`; every number here comes from runs on real data, 6–7 October 2026.*

## How much ported unchanged

All of it ran, and almost none of it had to be rewritten. The project has 29 data models. All
29 were built and run on both BigQuery and Spark, on the same real e-commerce dataset (about
3.3 million rows across seven tables), and every one of the 167 data-quality tests gave the
same result on both. 28 of the 29 models (97%) kept their logic exactly as written for
BigQuery. One model, the calendar table, needed a single line rewritten, because Spark has no
direct equivalent of how BigQuery turns a list into rows.

That figure comes with an important condition. The project was already written so that the
small pieces that differ between databases (type names, date functions, and so on) sit in one
shared layer instead of being scattered through the models. Most of the port went into adding a
Spark version of that layer. A BigQuery project without that layer would take noticeably more
work, since each model that uses BigQuery-specific features would need editing.

The results are not all identical. 8 of the 29 models produce exactly the same numbers on
both. The other 21 differ only in money amounts, for a known reason explained below. No model
differs in its columns or their types, and no difference was found in dates, counts, customer
or product identifiers, or keys.

## What it costs from now on

Running on two databases has an ongoing cost, but a small and predictable one.

- **New models must go through the shared layer.** Anything involving type names, money,
  dates and times, safe division, turning a list into rows, or formatting dates as text has to
  use the project's shared building blocks rather than either database's own spelling. A
  developer who writes BigQuery-only or Spark-only SQL directly will be stopped by an automatic
  check.
- **Some BigQuery features have no Spark version at all.** Examples are the shorthand for
  "every column, but replace this one", BigQuery's zero-based array positions, and numbers
  with more than 38 digits. Code that uses them has to be written another way, usually longer,
  and in one case with a lost capability.
- **The automatic check before each change** confirms that both databases can run every model
  and that every model has the same columns and types on both. It does not compare the money
  values on every change, because that comparison takes about an hour, costs money on
  BigQuery, and currently always shows the known money difference. Comparing values is a
  separate step, run on purpose.
- **Spark has to be kept running.** The tooling has no built-in local mode for Spark, so
  someone has to keep a Spark server running, and the dbt support for Spark is still labelled
  experimental and must be switched on explicitly.

## What to watch out for

These are the risks that do not show up as errors. Each one gives a wrong answer without
anything failing.

- **Money is rounded differently.** In this setup Spark stores money to the cent, while
  BigQuery keeps nine decimal places. Row by row the gap is at most half a cent, but it adds
  up: daily margins differed by up to 41 cents, and one warehouse's stock value by $8.90. It
  also affects anything calculated from money, such as margin percentages. This is a choice to
  make, not a bug: decide which rule is correct for your reporting before you move, and apply
  it on both databases.
- **Very large or very precise numbers have a hard limit on Spark.** Spark can hold at most
  38 digits; BigQuery can hold about 76. The project refuses to quietly convert such a value
  into a less precise one, so this would show up as a failure, not as wrong numbers. Nothing
  in the project needs more than 38 digits today.
- **List positions start at a different number.** BigQuery can count list positions from 0;
  Spark's equivalent counts from 1. A hand-translated query picks the neighbouring item and
  gives no error. The project does not use list positions today.
- **Week numbers disagree.** For the same date, BigQuery said week 10 and Spark said week 11.
  The project never uses week numbers, but any report that does would need one agreed rule.
- **Time zones decide which day an event belongs to.** Spark files every timestamp under a
  day and month using its own time-zone setting. Ours is set to UTC, matching BigQuery, and
  that is checked automatically. If that setting were ever changed to local time, orders
  placed late in the evening would move to the next day, or the next month, and every daily
  and monthly figure would change without any error.

## What was measured, and what was not

Everything above was measured on real infrastructure: Spark 4.2.0 running locally, BigQuery
through Google's service, both reading the same seven tables, which were confirmed to be
identical row for row before the comparison. No model was only checked on paper; every one
ran on both. Not tested here: performance and cost at production scale (Spark ran on a single
machine, so its timings say nothing about a cluster), Spark versions other than 4.2.0, and a
small number of BigQuery features the project does not use (some ways of aggregating lists,
reading a list position that does not exist, and an ISO-standard week number). Those are
marked "unverified" in the catalogue rather than assumed to work.
