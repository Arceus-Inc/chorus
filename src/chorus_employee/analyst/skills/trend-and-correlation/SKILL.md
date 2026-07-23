---
name: trend-and-correlation
description: How to quantify a trend and a relationship between variables without over-claiming.
when_to_use: Use when the question asks whether something is rising or falling over time (a trend) or whether two variables move together (a correlation/relationship).
---

# Trend and Correlation

Quantify "is it going up?" and "do these move together?" with real numbers, and state the caveats so
the conclusion is honest.

## Trend (is a series rising or falling?)

1. Order the series by time using an explicit numeric index (e.g. month 0,1,2,...), not a text label.
2. Fit a simple linear trend in `notebook_run`: `slope = numpy.polyfit(t, y, 1)[0]`. The sign of the
   slope is the direction; the magnitude is units of `y` per step.
3. Report the slope **and** the first-vs-last change as a cross-check. If they disagree (non-monotonic
   series), say the trend is not monotonic rather than forcing "up" or "down".

## Correlation (do two variables move together?)

1. Compute Pearson r with `df['a'].corr(df['b'])` (linear association) — report it to a few decimals.
2. State direction (sign) and strength (|r|: ~0.1 weak, ~0.3 moderate, ~0.5+ strong) in words.
3. **Correlation is not causation.** Note confounders when relevant (e.g. revenue correlates with
   units because revenue is partly computed from units).

## Rules

- Always report `n`; a correlation on a handful of points is fragile.
- Prefer a slope in interpretable units (e.g. "+1.7 percentage points per month") over a bare number.
- Never assert a trend or correlation you did not compute.
