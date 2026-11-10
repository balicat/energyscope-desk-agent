"""Deterministic calculations and the grounding check.

The model chooses series and writes the sentences; code does the sums.
`ungrounded()` is shared by the agent's output validator (forces a retry)
and by the eval (measures the final answer), so both apply one rule.
"""

from __future__ import annotations

import datetime as dt
import math
import re

from .models import Change, DeskAnswer, Observation, SeriesHit


def latest_obs(hit: SeriesHit, history: list[tuple[dt.date, float]]) -> Observation | None:
    if not history:
        return None
    d, v = history[-1]
    return Observation(series_id=hit.series_id, name=hit.name, units=hit.units, period=d, value=v)


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
    )


def close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=1e-3, abs_tol=0.01)


_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_NUM = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?")


def untraceable_numbers(answer: DeskAnswer) -> list[str]:
    """Numbers in the summary that match no number in the facts (after rounding)."""
    allowed: list[float] = []
    in_names: set[str] = set()  # "No. 2 Heating Oil", "PADD 3": numbers that are part of a name
    for f in answer.facts:
        allowed += [x for x in (f.latest_value, f.base_value, f.change_abs, f.change_pct, f.lookback_days) if x is not None]
        in_names |= set(_NUM.findall(f"{f.name} {f.series_id}"))
    bad = []
    for m in _NUM.finditer(_ISO.sub(" ", answer.summary)):
        if m.group() in in_names:
            continue
        raw = m.group().replace(",", "")
        n = float(raw)
        if "." not in raw and 1900 <= n <= 2100:  # a year
            continue
        dp = len(raw.split(".")[1]) if "." in raw else 0
        if not any(abs(round(abs(v), dp) - abs(n)) < 1e-9 or close(abs(v), abs(n)) for v in allowed):
            bad.append(m.group())
    return bad
