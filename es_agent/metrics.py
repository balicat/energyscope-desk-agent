"""Deterministic calculations and the grounding check.

The model chooses series and places slots; code does the sums.
"""

from __future__ import annotations

import datetime as dt
import math

from . import prose
from .models import Change, Observation, SeriesHit, Spread


def also_in(units: str, value: float) -> dict[str, float]:
    """The same value in the unit people ask for. EIA publishes stocks in thousand barrels; a person asks
    for million barrels. The conversion is done here so the model has a figure to quote and never divides."""
    key = unit_key(units)
    if key == "thousand barrel":
        return {"million_barrels": round(value / 1000, 3)}
    if key == "thousand barrel per day":
        return {"million_barrels_per_day": round(value / 1000, 3)}
    return {}


def latest_obs(hit: SeriesHit, history: list[tuple[dt.date, float]]) -> Observation | None:
    if not history:
        return None
    d, v = history[-1]
    return Observation(series_id=hit.series_id, name=hit.name, units=hit.units, period=d, value=v, also=also_in(hit.units, v))


def change_over(hit: SeriesHit, history: list[tuple[dt.date, float]], lookback_days: int) -> Change | None:
    """Latest value vs the last observation on or before (latest date - lookback)."""
    if not history:
        return None
    d1, v1 = history[-1]
    cutoff = d1 - dt.timedelta(days=lookback_days)
    base = [(d, v) for d, v in history if d <= cutoff]
    if not base:
        return None
    d0, v0 = base[-1]
    return Change(
        series_id=hit.series_id, name=hit.name, units=hit.units, lookback_days=lookback_days,
        latest_period=d1, latest_value=v1, base_period=d0, base_value=v0,
        change_abs=round(v1 - v0, 6), change_pct=round((v1 - v0) / v0 * 100, 6) if v0 else math.nan,
        also=also_in(hit.units, v1),
    )


def spread_of(a: SeriesHit, hist_a: list[tuple[dt.date, float]], b: SeriesHit, hist_b: list[tuple[dt.date, float]]) -> Spread | None:
    """a minus b on the latest date present in both histories."""
    vb = dict(hist_b)
    for d, va in reversed(hist_a):
        if d in vb:
            return Spread(series_a=a.series_id, name_a=a.name, series_b=b.series_id, name_b=b.name, units=a.units,
                          period=d, value_a=va, value_b=vb[d], spread=round(va - vb[d], 6))
    return None


unit_key = prose.unit_key  # one normaliser for units, shared with the prose checks


def close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=1e-3, abs_tol=0.01)
