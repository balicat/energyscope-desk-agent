"""Deterministic calculations and the grounding check.

The model chooses series and writes the sentences; code does the sums.
`ungrounded()` is shared by the agent's output validator (forces a retry)
and by the eval (measures the final answer), so both apply one rule.
"""

from __future__ import annotations

import datetime as dt
import math
import re

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


_UP = {"up", "rose", "risen", "rise", "rising", "higher", "increase", "increased", "gain", "gained", "climbed",
       "above", "more", "build", "built", "grew", "added"}
_DOWN = {"down", "fell", "fallen", "fall", "falling", "lower", "decrease", "decreased", "decline", "declined",
         "dropped", "drop", "below", "less", "fewer", "draw", "drew", "shrank", "lost"}


def direction_problems(answer: DeskAnswer) -> list[str]:
    """Direction words in the summary that contradict the data.

    Two rules, both narrow on purpose. A curve called contango when every cited curve is in
    backwardation (or the reverse). A change described only with falling words when every change
    in the facts is a rise (or the reverse). A summary that uses the right word anywhere passes,
    so "not contango but backwardation" and mixed moves are never flagged.
    """
    text = answer.summary.lower()
    words = set(re.findall(r"[a-z]+", text))
    problems = []
    shapes = {r.note.split(" ")[0] for r in answer.readings if r.key.startswith("curve:")} & {"backwardation", "contango"}
    if len(shapes) == 1:
        right = shapes.pop()
        wrong = "contango" if right == "backwardation" else "backwardation"
        if wrong[:9] in text and right[:9] not in text:
            problems.append(f"the summary says {wrong}; the curve is in {right}")
    signs = {c > 0 for f in answer.facts if (c := f.change_abs) is not None and c != 0}
    if len(signs) == 1:
        rose = signs.pop()
        right, wrong = (_UP, _DOWN) if rose else (_DOWN, _UP)
        if words & wrong and not words & right:
            problems.append(f"the summary uses {sorted(words & wrong)} but every change in the facts is "
                            f"{'a rise' if rose else 'a fall'}; say so in plain words")
    return problems


_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_NUM = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?")


def untraceable_numbers(answer: DeskAnswer) -> list[str]:
    """Numbers in the summary that match no number in the facts, spreads or readings (after rounding)."""
    allowed: list[float] = []
    in_names: set[str] = set()  # "No. 2 Heating Oil", "PADD 3": numbers that are part of a name
    for f in answer.facts:
        allowed += [x for x in (f.latest_value, f.base_value, f.change_abs, f.change_pct, f.lookback_days) if x is not None]
        in_names |= set(_NUM.findall(f"{f.name} {f.series_id}"))
    for s in answer.spreads:
        allowed += [s.value_a, s.value_b, s.spread]
        in_names |= set(_NUM.findall(f"{s.name_a} {s.series_a} {s.name_b} {s.series_b}"))
    for r in answer.readings:
        allowed += list(r.values.values())
        in_names |= set(_NUM.findall(f"{r.title} {r.note} {r.context} {r.key} {' '.join(r.series_ids)} {' '.join(r.values)}"))
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
