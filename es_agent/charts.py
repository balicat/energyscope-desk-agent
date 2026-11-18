"""Chart data for an answer: the history behind the numbers, drawn by the page.

Built by code from the data source after the answer is written. The model never sees or
supplies a chart: it cannot plot a number it could not quote.
"""

from __future__ import annotations

import datetime as dt

from . import clock, readings
from .models import DeskAnswer
from .sources import DataSource

MAX_CHARTS = 3
MAX_POINTS = 180


def _thin(hist: list[tuple[dt.date, float]]) -> list[list]:
    """At most MAX_POINTS points, always keeping the latest."""
    step = max(1, -(-len(hist) // MAX_POINTS))
    kept = hist[::-1][::step][::-1]
    return [[d.isoformat(), round(v, 4)] for d, v in kept]


def _line(title: str, units: str, hist, lines: dict[str, float] | None = None) -> dict | None:
    if len(hist) < 5:
        return None
    return {"kind": "line", "title": title, "units": units, "points": _thin(hist),
            "lines": [{"label": k, "value": round(v, 4)} for k, v in (lines or {}).items()]}


def _bands(values: dict[str, float], prefix: str = "") -> dict[str, float]:
    return {"90th percentile": values[f"{prefix}p90"], "10th percentile": values[f"{prefix}p10"]}


def charts_for(answer: DeskAnswer, source: DataSource) -> list[dict]:
    out: list[dict | None] = []
    days = 366 * readings.HISTORY_YEARS
    for r in answer.readings:
        kind, _, rest = r.key.partition(":")
        if kind == "curve":
            months = [k for k in r.values if k[1:].isdigit()]
            out.append({"kind": "curve", "title": f"{r.title}, {r.period}", "units": r.units,
                        "points": [[m, r.values[m]] for m in months], "lines": []})
        elif kind == "arb" and rest == "us_crude_to_europe":
            d = r.period
            spread = [(dd, v) for dd, v in readings.spread_history(source, readings.BRENT_SPOT, readings.CRUDE) if dd <= d]
            freight = [(dd, v) for dd, v in source.history(readings.FREIGHT, start=clock.today() - dt.timedelta(days=days)) if dd <= d]
            out.append(_line("Brent minus WTI, spot", "Dollars per Barrel", spread, _bands(r.values, "spread_")))
            out.append(_line("Tanker freight proxy (Breakwave tanker ETF)", "index points", freight, _bands(r.values, "freight_")))
        elif kind == "arb":
            hist = [(dd, round(v[0] / readings.GALLONS_PER_TONNE_GASOIL - v[1], 6))
                    for dd, v in readings.aligned(source, [readings.GASOIL, readings.NYH_DIESEL], days)]
            out.append(_line("ICE gasoil minus New York Harbor diesel", "Dollars per Gallon", hist, _bands(r.values, "difference_")))
        elif kind == "fspread":
            parts = readings.futures_spread_parts(source)
            if parts:
                out.append(_line(r.title, r.units, parts[1], _bands(r.values, "spread_")))
        elif kind == "fcrack":
            parts = readings.futures_crack_parts(source, rest)
            if parts:
                hist = [(dd, round(readings.crack_value(rest, *v), 6)) for dd, v in parts[1]]
                out.append(_line(r.title, r.units, hist, _bands(r.values, "crack_")))
        elif kind == "crack":
            out.append(_line(f"{rest} crack spread", "Dollars per Barrel", readings.crack_history(source, rest), _bands(r.values, "crack_")))
        elif kind == "percentile":
            sid = r.series_ids[0]
            hist = source.history(sid, start=clock.today() - dt.timedelta(days=366 * int(r.values["years"])))
            out.append(_line(r.title, r.units, hist, _bands(r.values)))
        elif kind == "positioning":
            hist = source.history(r.series_ids[0], start=clock.today() - dt.timedelta(days=7 * readings.PERCENTILE_WEEKS + 30))
            out.append(_line(f"{r.title}: net position", "contracts", hist[-readings.PERCENTILE_WEEKS:], _bands(r.values, "net_")))
        elif kind == "seasonal":
            sid = r.series_ids[0]
            hist = source.history(sid, start=clock.today() - dt.timedelta(days=366 * 2))
            out.append(_line(f"{source.meta(sid).name}, last two years", r.units, hist,
                             {"average, same time of year": r.values["prior_average"]}))
    for s in answer.spreads:
        out.append(_line(f"{s.name_a} minus {s.name_b}", s.units, readings.spread_history(source, s.series_a, s.series_b, 366)))
    for f in answer.facts:
        out.append(_line(f.name, f.units, source.history(f.series_id, start=clock.today() - dt.timedelta(days=366))))
    return [c for c in out if c][:MAX_CHARTS]
