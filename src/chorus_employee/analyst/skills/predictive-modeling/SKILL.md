---
name: predictive-modeling
description: How to build and report a predictive model honestly — leakage-safe pipelines, a held-out test the model never sees, cross-validation done right, a naive baseline, and truthful reporting of the gap between validation and held-out performance. Use for any predict / forecast / classify / score task.
when_to_use: Use whenever the task is to predict, forecast, classify, rank, or score — anything where a model's output will be judged against unseen data. Especially when a metric threshold gates the result.
---

# Predictive modeling

A model's only honest score is on data it never touched. The single most common failure is reporting
a tuned cross-validation number as if it were generalization performance — it isn't, and it is
gameable. This skill is the discipline that keeps a predictive claim truthful.

## When NOT to use this
- The task is descriptive/explanatory, not predictive (use `analytics-diagnostic-method`).
- There isn't enough data to hold out a meaningful test set — say so; don't fake a score.

## Method

### 1. Split first, before you look
Hold out a test set **before any exploration or fitting**, and do not touch it until the very end.
Time-series → split by time (train on the past, test on the future); never shuffle time. i.i.d. rows
→ a random split (stratified if classes are imbalanced). Keep the test set's labels out of every
transform you fit.

### 2. Establish a baseline
Always compute the naive baseline first: majority class for classification, last value / seasonal
mean for forecasting, target mean for regression. A model that can't clearly beat the baseline is not
a result — report that honestly (the degenerate-model trap: "80% accuracy" that is just the base rate).

### 3. Prevent leakage
Leakage = the model sees, at train time, information it won't have at prediction time. Guard against:
- fitting scalers/encoders/imputers on the full data (fit on train only, apply to test);
- features derived from the target or from the future;
- IDs, timestamps, or post-outcome fields that proxy the label;
- duplicates or grouped rows split across train and test.
If a result looks too good, suspect leakage first.

### 4. Cross-validate for model selection only
Use CV *within the training set* to choose the model/hyperparameters. The CV score is a selection
signal, not the reported result. Report the reported result on the untouched held-out test.

### 5. Score on the held-out set once, and report honestly
Pick the metric that matches the decision (accuracy is misleading under imbalance — prefer AUC / F1 /
precision-recall, or calibrated probabilities). Report **both** the CV score and the held-out score,
and explain the gap: a large CV↔test gap means overfitting or leakage, and must be disclosed, not
hidden. Never tune on the test set — that turns it into a training set and the number becomes a lie.

### 6. Make the result reproducible and checkable
When a threshold gates the task, write predictions to a file (e.g. `predictions.csv`) and a small
`score.py` that loads the held-out labels, computes the metric, prints it, and exits non-zero below
the bar — so the score is an independent, machine-checkable fact rather than a self-report.

## Common failure modes
- Reporting the CV number as generalization performance.
- Tuning until the test score clears the bar (test-set leakage by iteration).
- No baseline, so a base-rate-only model looks like a win.
- Fitting preprocessing on all the data before splitting.
- Accuracy on an imbalanced problem with no precision/recall.

## Cross-references
- `statistical-rigor` — baselines, base rates, and interval reporting.
- `exploratory-data-analysis` — profile and clean before modeling.
- `findings-communication` — report the number, the baseline, and the honest caveat first.
