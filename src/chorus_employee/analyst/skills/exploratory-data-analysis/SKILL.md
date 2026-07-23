---
name: exploratory-data-analysis
description: A disciplined first pass on any new dataset before answering questions about it.
when_to_use: Use at the start of any analysis when you have a dataset (CSV, table, or warehouse) and have not yet profiled it — to understand shape, types, ranges, and data-quality issues before computing answers.
---

# Exploratory Data Analysis (EDA)

Before answering any quantitative question, understand the data you have. Skipping this is how
wrong-but-confident findings happen.

## Steps

1. **Locate and load.** Find the data (`repo_search` for files, or `SELECT name FROM sqlite_master
   WHERE type='table'` for a warehouse). Load it in `notebook_run` with pandas.
2. **Profile shape and types.** Print `df.shape`, `df.dtypes`, and `df.head()`. Confirm the columns
   are the types you expect (numbers parsed as numbers, dates as dates).
3. **Check data quality.** Print `df.isna().sum()` (missing values) and `df.describe(include='all')`
   (ranges, uniques). Look for impossible values (negative counts, zero denominators) and duplicates
   (`df.duplicated().sum()`).
4. **Understand cardinality.** For categorical columns, print `df['col'].value_counts()` to see the
   groups you can split by.
5. **State assumptions.** Note any cleaning you applied (dropped rows, filled values, parsed dates)
   in your findings — a reviewer must see what you did to the data.

## Rules

- Never compute a rate with a zero or missing denominator without handling it explicitly.
- Report `n` (the number of rows) alongside any aggregate — an average over 3 rows is not the same
  claim as an average over 30,000.
- If the data contradicts the question's premise, say so rather than forcing an answer.
