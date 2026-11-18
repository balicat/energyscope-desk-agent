"""Deterministic calculations and the grounding check.

The model chooses series and writes the sentences; code does the sums.
`ungrounded()` is shared by the agent's output validator (forces a retry)
and by the eval (measures the final answer), so both apply one rule.
"""

from __future__ import annotations

import datetime as dt
import math
import re

from . import prose
from .models import Change, DeskAnswer, Observation, SeriesHit, Spread


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


def spread_of(a: SeriesHit, hist_a: list[tuple[dt.date, float]], b: SeriesHit, hist_b: list[tuple[dt.date, float]]) -> Spread | None:
    """a minus b on the latest date present in both histories."""
    vb = dict(hist_b)
    for d, va in reversed(hist_a):
        if d in vb:
            return Spread(series_a=a.series_id, name_a=a.name, series_b=b.series_id, name_b=b.name, units=a.units,
                          period=d, value_a=va, value_b=vb[d], spread=round(va - vb[d], 6))
    return None


_UNIT_WORDS = {"usd": "dollars", "$": "dollars", "us$": "dollars", "/": " per ", "bbl": "barrel", "barrels": "barrel",
               "gal": "gallon", "gallons": "gallon", "mt": "tonne", "tonnes": "tonne", "mmbtu": "million btu"}


def unit_key(units: str) -> str:
    """Publishers label the same unit differently ('USD/bbl', 'Dollars per Barrel'); compare on this."""
    text = units.lower().replace("/", " per ")
    return " ".join(_UNIT_WORDS.get(w, w) for w in text.split())


def close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=1e-3, abs_tol=0.01)


_LONG = re.compile(r"(?<![\w.,])(\d[\d,]*\.\d{3,})(?!\d)")


def tidy(text: str) -> str:
    """Round numbers written with three or more decimals to two, as the page's tables do.
    Numbers below 1 are left alone (a small rate would round to nothing)."""
    def fix(m: re.Match) -> str:
        raw = m.group(1)
        n = float(raw.replace(",", ""))
        return raw if n < 1 else f"{n:,.2f}" if "," in raw else f"{n:.2f}"

    return _LONG.sub(fix, text)


def direction_problems(answer: DeskAnswer) -> list[str]:
    """Direction words in the summary that contradict the data. See `prose.direction_problems`."""
    return prose.direction_problems(answer)


def untraceable_numbers(answer: DeskAnswer) -> list[str]:
    """Numbers and dates, in the summary and in the model's own caveats, that trace to nothing a
    tool returned. See `prose.untraceable`."""
    return prose.untraceable(answer)
