"""Recompute an answer from the data source, independently of the run that produced it.

Used twice: by the `Grounded` evaluator on the test questions, and by
`serve.py` on every live answer, so the same check that scores the suite also
watches real traffic.
"""

from __future__ import annotations

import datetime as dt

from . import clock, metrics, readings
from .models import DeskAnswer
from .sources import DataSource


def verify(answer: DeskAnswer, source: DataSource) -> list[str]:
    """Problems found; an empty list means every number matches a fresh computation."""
    problems = []
    for f in answer.facts:
        hit = source.meta(f.series_id)
        if hit is None:
            problems.append(f"{f.series_id} does not exist")
            continue
        lb = f.lookback_days or 0
        hist = source.history(f.series_id, start=clock.today() - dt.timedelta(days=lb + 400))
        truth = metrics.change_over(hit, hist, lb) if lb else metrics.latest_obs(hit, hist)
        if truth is None:
            problems.append(f"{f.series_id}: source has no value to compare")
            continue
        tv = truth.latest_value if lb else truth.value
        tp = truth.latest_period if lb else truth.period
        if f.latest_period != tp or not metrics.close(f.latest_value, tv):
            problems.append(f"{f.series_id}: source says {tp}={tv}, answer says {f.latest_period}={f.latest_value}")
        elif lb and not (metrics.close(f.change_pct, truth.change_pct) and metrics.close(f.base_value, truth.base_value)):
            problems.append(f"{f.series_id}: change differs from source")
    start = clock.today() - dt.timedelta(days=400)
    for s in answer.spreads:
        a, b = source.meta(s.series_a), source.meta(s.series_b)
        truth = a and b and metrics.spread_of(a, source.history(s.series_a, start=start), b, source.history(s.series_b, start=start))
        if not truth or s.period != truth.period or not metrics.close(s.spread, truth.spread):
            problems.append(f"spread {s.series_a} minus {s.series_b} differs from source")
    for r in answer.readings:
        truth = readings.compute(source, r.key)
        if truth is None or truth.period != r.period or truth.context != r.context or truth.counter != r.counter or set(truth.values) != set(r.values) or not all(
            metrics.close(truth.values[k], r.values[k]) for k in r.values
        ):
            problems.append(f"reading {r.key} differs from source")
    bad = metrics.untraceable_numbers(answer)
    if bad:
        problems.append(f"summary numbers {bad} trace to nothing")
    return problems
