"""Readings the EnergyScope server computes.

Every tool here sends one request to one of the server's own actions (the computations the Excel add-in's
ES.Percentile, ES.Seasonal, ES.Stats, ES.Brief ... and the MCP server call) and turns the answer into a
Reading. Nothing is computed here: the server's numbers are copied in, renamed only where a name says what a
number is. So a question gets the same number from The Librarian, from Excel and from an MCP client.

The request is kept on the reading (`Reading.request`: the tool, the action and the body sent). Two things
use it: `rebuild` sends it again, which is how the independent check recomputes a server reading, and the
Excel sheet calls the add-in function that sends the same request.

What the check proves for these readings: the numbers shown are the server's answer to that request, copied
unchanged, and the server gives the same answer when asked again. It does not recompute the statistics a
second way; for percentile and the window statistics the Excel sheet does that, from the series' values.
"""

from __future__ import annotations

import datetime as dt
import math
import re

from . import clock, readings
from .models import Reading
from .sources import DataSource, ServerError, parse_period

MAX_VALUES = 90          # a correlation matrix or a report panel can carry hundreds; the model needs the top
MAX_CONTEXT = 2400       # characters of code-written text per reading
MAX_LINES = 12           # list items (breakpoints, outliers, events, signals) written into the context


def _iso(text: str) -> str:
    """Server periods arrive as 20261117; the answer writes dates as 2026-11-17 (the prose rules require it)."""
    return re.sub(r"\b(19|20)(\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\b", r"\1\2-\3-\4", str(text))


def _num(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


def flatten(doc: dict, skip: tuple[str, ...] = (), depth: int = 2, prefix: str = "") -> dict[str, float]:
    """Every finite number in the answer, nested names joined with '.', in the server's order."""
    out: dict[str, float] = {}
    for k, v in doc.items():
        if k in skip or k in ("rows", "server_version", "matrix"):
            continue
        name = f"{prefix}{k}"
        n = _num(v)
        if n is not None:
            out[name] = n
        elif isinstance(v, dict) and depth > 0:
            out.update(flatten(v, skip, depth - 1, name + "."))
    return out


def list_values(doc: dict, *names: str, most: int = MAX_LINES) -> dict[str, float]:
    """The numbers of list items (breaks, segments, outliers, episodes) as values named list.n.field, counted from
    1. In the context alone a number can be quoted only exactly as written; as a value it may be rounded."""
    out: dict[str, float] = {}
    for name in names:
        for i, item in enumerate((doc.get(name) or [])[:most], 1):
            if isinstance(item, dict):
                for k, v in item.items():
                    n = _num(v)
                    if n is not None and k != "index":
                        out[f"{name}.{i}.{k}"] = n
    return out


def _period(doc: dict, *fields: str) -> dt.date:
    for f in fields:
        v = doc.get(f)
        if v:
            try:
                return parse_period(str(v))
            except ValueError:
                continue
    return clock.today()


_DATEISH = re.compile(r"period|date|start|end|first|last|peak|trough", re.I)


def _item(x) -> str:
    """One list item as a line: its scalar fields; a field named as a date (period, start, trough ...) written
    YYYY-MM-DD. Only those: any eight-digit number with a valid month and day would otherwise become a date
    ("generation 20111225.0 MWh", the adversary, 21 Nov 2026)."""
    if isinstance(x, dict):
        parts = []
        for k, v in x.items():
            if isinstance(v, (dict, list)) or v is None or k in ("date_short", "index"):
                continue
            shown = _iso(v) if isinstance(v, str) and _DATEISH.search(k) else (round(v, 6) if isinstance(v, float) else v)
            parts.append(f"{k} {shown}")
        return ", ".join(parts)
    return str(x)


def _lines(label: str, items, most: int = MAX_LINES) -> str:
    if not items:
        return ""
    shown = [_item(x) for x in items[:most]]
    more = f" (and {len(items) - most} more)" if len(items) > most else ""
    return f"{label}: " + "; ".join(shown) + more + "."


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_CONTEXT else text[:MAX_CONTEXT].rsplit(" ", 1)[0] + " ..."


def _window(years: int) -> tuple[str, str]:
    """A window of `years` ending today, both ends fixed in the request so it can be sent again (and so the
    Excel sheet fixes the same dates)."""
    today = clock.today()
    return (today - dt.timedelta(days=round(365.25 * years))).isoformat(), today.isoformat()


def _name(source: DataSource, sid: str) -> tuple[str, str]:
    hit = source.meta(sid)
    if hit is None:
        raise ServerError(f"Unknown series_id {sid!r}. Use search_series to find a valid ID.")
    return hit.name, hit.units


def _reading(tool: str, action: str, body: dict, key: str, title: str, period: dt.date, units: str,
             series_ids: list[str], values: dict[str, float], context: str = "", note: str = "",
             counter: str = "", hypothetical: bool = False) -> Reading:
    if len(values) > MAX_VALUES:
        values = dict(list(values.items())[:MAX_VALUES])
    return Reading(key=key, title=title, period=period, units=units, series_ids=series_ids, values=values,
                   context=_clip(context), note=note, counter=counter, hypothetical=hypothetical,
                   request={"tool": tool, "action": action, "body": body})


def _flatten_last_row(doc):
    rows = doc.get("rows") or []
    return {f"latest.{k}": float(v) for k, v in (rows[-1].items() if rows and isinstance(rows[-1], dict) else [])
            if _num(v) is not None}


# ---- one series, one window -------------------------------------------------------------------------------

def percentile(source: DataSource, series_id: str, years: int = 3) -> Reading:
    """ES.Percentile: where the latest value ranks in its own window."""
    if not 1 <= years <= 10:
        raise ServerError("years must be 1 to 10")
    start, end = _window(years)
    body = {"series": series_id, "start": start, "end": end}
    return _percentile(source, body, years)


def _percentile(source, body, years):
    name, units = _name(source, body["series"])
    doc = source.action("percentile", body)
    values = flatten(doc, skip=("series_id",))
    values["years"] = float(years)
    first = _iso(doc.get("first_period", ""))
    ctx = (f"Ranked against {int(values.get('observations', 0))} values from {first} to {_iso(doc.get('last_period', ''))}. "
           "percentile 0 = lowest of the window, 100 = highest; zscore = standard deviations from the window's mean.")
    # How long the level has been unusual and when it was last so: not a statistic the server has. Written here
    # over the same window, as the Librarian's own percentile wrote it before 21 Nov 2026 ("is tanker freight
    # unusually high, and when was it last this high?" lost its second half when the server's reading replaced it).
    end = min(dt.date.fromisoformat(body["end"]), _period(doc, "target_period", "last_period"))
    hist = [(d, v) for d, v in source.history(body["series"], start=dt.date.fromisoformat(body["start"])) if d <= end]
    if len(hist) >= 20:
        extra, sentence = readings.spell(hist)
        values.update(extra)
        ctx += " " + sentence
    short = ""
    try:
        if parse_period(first) > dt.date.fromisoformat(body["start"]) + dt.timedelta(days=45):
            short = (f"Shorter history: {body['series']} begins on {first}, so its percentile and statistics are taken "
                     f"since then, not over {years} years.")
    except ValueError:
        pass
    return _reading("percentile", "percentile", body, f"percentile:{body['series']}:{years}",
                    f"{name}: latest against its last {years} years", _period(doc, "target_period", "last_period"),
                    units, [body["series"]], values, ctx, "percentile 0 = lowest of the window, 100 = highest", short)


def seasonal(source: DataSource, series_id: str, years: int = 5) -> Reading:
    """ES.Seasonal: the latest value against the same week (weekly) or month (monthly) of earlier years."""
    if not 2 <= years <= 10:
        raise ServerError("years must be 2 to 10")
    # `end` pins the comparison to a day, so it can be asked again (the server reads `end`; it ignores `as_of`).
    # ES.Seasonal has no end argument: its Excel tab follows the latest value (the tab says so).
    return _seasonal(source, {"series": series_id, "lookback_years": years, "end": clock.today().isoformat()})


def _seasonal(source, body):
    name, units = _name(source, body["series"])
    doc = source.action("seasonal", body)
    values = flatten(doc, skip=("series_id", "history_by_year"))
    hist = doc.get("history_by_year") or {}
    for year, v in hist.items():
        if _num(v) is not None:
            values[f"value_in_{year}"] = float(v)
    cur, lo, hi = values.get("current_value"), values.get("seasonal_min"), values.get("seasonal_max")
    note = ("above the range" if cur is not None and hi is not None and cur > hi else
            "below the range" if cur is not None and lo is not None and cur < lo else "inside the range")
    ctx = (f"Same {doc.get('seasonal_key', '').split('=')[0] or 'time of year'} ({doc.get('seasonal_key', '')}) in each of "
           f"{int(values.get('years_of_history', 0))} earlier years: "
           + ", ".join(f"{y} {v:,.6g}" for y, v in hist.items() if _num(v) is not None)
           + f". The latest value is {note} of those years. delta_vs_avg = latest minus the average; "
           "pct_vs_avg = that difference in percent of the average.")
    years = int(body["lookback_years"])
    return _reading("seasonal", "seasonal", body, f"seasonal:{body['series']}:{years}",
                    f"{name}: latest against the same time of year, previous {years} years",
                    _period(doc, "current_period"), units, [body["series"]], values, ctx, note)


def _series_window(tool: str, action: str, title: str, extra: dict | None = None, skip=("series_id",), units=None,
                   context=None, period=("last_date", "last_period", "current_period"), last_row: bool = False,
                   lists: tuple[str, ...] = (), percent_of: tuple[str, ...] = ()):
    """A builder for an action that takes one series and a window: stats, volatility, returns, ..."""

    def build(source: DataSource, series_id: str, years: int = 3, **params) -> Reading:
        if not 1 <= years <= 20:
            raise ServerError("years must be 1 to 20")
        start, end = _window(years)
        body = {"series": series_id, "start": start, "end": end, **(extra or {}), **params}
        return build.rebuild(source, body, years)

    def rebuild_series(source: DataSource, body: dict, years: int) -> Reading:
        name, u = _name(source, body["series"])
        doc = source.action(action, body)
        values = flatten(doc, skip=skip)
        if last_row:   # the numbers of these actions are in the last row of a table
            values.update(_flatten_last_row(doc))
        values.update(list_values(doc, *lists))
        for k in [k for k in values if k.endswith(percent_of)] if percent_of else []:
            values[k + "_pct"] = round(values[k] * 100, 6)   # the model may not convert: code gives the percent
        values["years"] = float(years)
        ctx = context(doc) if context else ""
        ctx = (f"Window {body['start']} to {body['end']}. " + ctx).strip()
        params = ":".join(str(body[k]) for k in sorted(body) if k not in ("series", "start", "end"))
        key = f"{tool}:{body['series']}:{years}" + (f":{params}" if params else "")
        p = _period(doc, *period) if any(doc.get(f) for f in period) else _last_row_period(doc, body)
        return _reading(tool, action, body, key, f"{name}: {title}, last {years} years", p,
                        units(u) if callable(units) else (units or u), [body["series"]], values, ctx)

    build.rebuild = rebuild_series
    return build


def _last_row_period(doc: dict, body: dict) -> dt.date:
    """The date of the last row the server used, or the window's end when the answer has no rows."""
    rows = doc.get("rows") or []
    if rows and isinstance(rows[-1], dict) and rows[-1].get("period"):
        try:
            return parse_period(str(rows[-1]["period"]))
        except ValueError:
            pass
    return min(clock.today(), dt.date.fromisoformat(body["end"]))


def _ctx_returns(doc):
    s = doc.get("summary") or {}
    return (f"Largest fall from a peak: from {_iso(s.get('max_drawdown_peak', ''))} to {_iso(s.get('max_drawdown_trough', ''))}. "
            "total_return_pct is the change over the window in percent; volatility is of the period-to-period returns.")


def _ctx_breakpoints(doc):
    return (_lines("Breaks at", doc.get("breakpoints") or []) + " "
            + _lines("Segments", doc.get("segments") or []))


def _ctx_outliers(doc):
    return _lines("Outliers", doc.get("outliers") or [])


def _ctx_unit_root(doc):
    return f"Consensus of the tests: {doc.get('consensus', '')}. Each test's p_value is under its name."


def _ctx_acf(doc):
    rows = doc.get("rows") or []
    return _lines("Autocorrelation by lag", rows, 11) + f" Values outside plus or minus {doc.get('confidence_band', '')} are significant."


def _ctx_bubble(doc):
    return (f"Explosive episode found: {'yes' if doc.get('bubble_detected') else 'no'} (gsadf against cv_95). "
            + _lines("Episodes", doc.get("episodes") or []))


def _ctx_latest_row(doc):
    rows = doc.get("rows") or []
    return ("Latest row: " + _item(rows[-1]) + ".") if rows else ""


stats = _series_window("stats", "stats", "descriptive statistics", period=("last_date",))
volatility = _series_window("volatility", "volatility", "volatility (annualised, rolling and GARCH(1,1))",
                            units=lambda u: "annualised, as a fraction (the _pct values: the same in percent)",
                            context=_ctx_latest_row, last_row=True, percent_of=("rolling_vol", "garch_vol"))
returns = _series_window("returns", "returns", "returns and drawdown", units=lambda u: "percent", context=_ctx_returns)
breakpoints = _series_window("breakpoints", "breakpoints", "structural breaks", context=_ctx_breakpoints,
                             lists=("breakpoints", "segments"))
outliers = _series_window("outliers", "outliers", "outliers", context=_ctx_outliers, lists=("outliers",))
unit_root = _series_window("unit_root", "unit_root", "unit-root tests", extra={"test": "all"},
                           units=lambda u: "test statistics", context=_ctx_unit_root)
acf = _series_window("acf", "acf", "autocorrelation", units=lambda u: "correlation coefficient", context=_ctx_acf)
bubble_test = _series_window("bubble_test", "bubble_test", "test for explosive (bubble) behaviour",
                             units=lambda u: "test statistics", context=_ctx_bubble, lists=("episodes",))
seasonality = _series_window("seasonality", "seasonality", "seasonal decomposition (trend, seasonal, residual)",
                             context=_ctx_latest_row, last_row=True)
hp_filter = _series_window("hp_filter", "hp_filter", "trend and cycle (Hodrick-Prescott filter)", context=_ctx_latest_row,
                           last_row=True)


# ---- two or more series -----------------------------------------------------------------------------------

def _like_for_like(source: DataSource, a: str, b: str) -> str:
    """get_spread's rule, for any tool that subtracts one series from another: refuse unlike units, unlike kinds
    (readings.pairing_note) and unlike rhythms (readings.frequency_note); otherwise the note to carry, if any.
    Until 21 Nov 2026 get_spread_stats asked none of it and gave WTI M1 minus RBOB M1 as "81.59 USD/bbl" (dollars
    a barrel minus dollars a gallon) with a percentile (the adversary)."""
    from .prose import unit_key
    ua, ub = source.meta(a), source.meta(b)
    if ua is None or ub is None:
        raise ServerError(f"Unknown series_id {a if ua is None else b!r}. Use search_series to find a valid ID.")
    if unit_key(ua.units) != unit_key(ub.units):
        raise ServerError(f"Units differ ({ua.units!r} vs {ub.units!r}): no spread. Report the two series separately.")
    why, usable = readings.pairing_note(a, b)
    if not usable:
        raise ServerError(why)
    freq = readings.frequency_note(source, a, b)
    if freq:
        raise ServerError(freq)
    return why


def _pair(tool: str, action: str, title: str, units: str | None = None, context=None, like_for_like: bool = False):
    def build(source: DataSource, series_a: str, series_b: str, years: int = 3, **params) -> Reading:
        if not 1 <= years <= 20:
            raise ServerError("years must be 1 to 20")
        start, end = _window(years)
        return rebuild_pair(source, {"series_a": series_a, "series_b": series_b, "start": start, "end": end, **params}, years)

    def rebuild_pair(source, body, years):
        (na, ua), (nb, _) = _name(source, body["series_a"]), _name(source, body["series_b"])
        note = _like_for_like(source, body["series_a"], body["series_b"]) if like_for_like else ""
        doc = source.action(action, body)
        values = flatten(doc, skip=("series_a", "series_b"))
        values["years"] = float(years)
        params = ":".join(str(body[k]) for k in sorted(body) if k not in ("series_a", "series_b", "start", "end"))
        key = f"{tool}:{body['series_a']},{body['series_b']}:{years}" + (f":{params}" if params else "")
        ctx = f"Window {body['start']} to {body['end']}. " + (context(doc) if context else "")
        return _reading(tool, action, body, key, f"{na} and {nb}: {title}, last {years} years",
                        _last_row_period(doc, body), units or ua,
                        [body["series_a"], body["series_b"]], values, ctx, counter=note)

    build.rebuild = rebuild_pair
    return build


spread_stats = _pair("spread_stats", "spread", "the spread (first minus second) against its own history", like_for_like=True,
                     context=lambda d: "current_spread = first minus second on the latest common date; half_life is in "
                                       "observations: how fast the spread has returned toward its mean.")
rolling_correlation = _pair("rolling_correlation", "rolling_correlation", "rolling correlation",
                            units="correlation coefficient", context=_ctx_latest_row)


def _many(tool: str, action: str, title: str, units: str, flatten_doc=None, context=None, extra: dict | None = None):
    def build(source: DataSource, series_ids: list[str], years: int = 3, **params) -> Reading:
        if not 2 <= len(series_ids) <= 8:
            raise ServerError("give 2 to 8 series")
        if not 1 <= years <= 20:
            raise ServerError("years must be 1 to 20")
        start, end = _window(years)
        return rebuild_many(source, {"series": list(series_ids), "start": start, "end": end, **(extra or {}), **params}, years)

    def rebuild_many(source, body, years):
        names = [_name(source, s)[0] for s in body["series"]]
        doc = source.action(action, body)
        values = flatten_doc(doc) if flatten_doc else flatten(doc, skip=("labels",))
        values["years"] = float(years)
        params = ":".join(str(body[k]) for k in sorted(body) if k not in ("series", "start", "end"))
        key = f"{tool}:{','.join(body['series'])}:{years}" + (f":{params}" if params else "")
        ctx = f"Window {body['start']} to {body['end']}. " + (context(doc) if context else "")
        return _reading(tool, action, body, key, f"{', '.join(names)}: {title}, last {years} years",
                        min(clock.today(), dt.date.fromisoformat(body["end"])), units, list(body["series"]), values, ctx)

    build.rebuild = rebuild_many
    return build


def _corr_values(doc):
    labels, matrix = doc.get("labels") or [], doc.get("matrix") or []
    out = {"observations": float(doc.get("observations", 0))}
    for i, a in enumerate(labels):
        for j, b in enumerate(labels):
            if j > i and i < len(matrix) and j < len(matrix[i]) and _num(matrix[i][j]) is not None:
                out[f"{a} with {b}"] = float(matrix[i][j])
    return out


correlation = _many("correlation", "correlation", "correlation of daily values", "correlation coefficient",
                    flatten_doc=_corr_values, context=lambda d: "1 = move together, 0 = unrelated, -1 = opposite.")
cointegration = _many("cointegration", "cointegration", "cointegration test", "test statistics",
                      extra={"method": "engle-granger"},
                      context=lambda d: f"Cointegrated at 5 percent: {'yes' if d.get('cointegrated') else 'no'}.")


def _granger(doc):
    out = flatten(doc, skip=("labels", "irf"))
    return out


var = _many("var", "var", "vector autoregression and Granger causality", "test statistics", flatten_doc=_granger,
            context=lambda d: "A p_value under 0.05 for 'A -> B' means past values of A help predict B (Granger causality).")


def changes(source: DataSource, series_ids: list[str], lookback_days: int = 7) -> Reading:
    """Which of several series moved most, ranked by how unusual the move is for each."""
    if not 2 <= len(series_ids) <= 20:
        raise ServerError("give 2 to 20 series of one frequency")
    return _changes(source, {"series": list(series_ids), "lookback_days": int(lookback_days)})


def _changes(source, body):
    for s in body["series"]:
        _name(source, s)
    doc = source.action("changes", body)
    rows = doc.get("changes") or doc.get("rows") or []
    values = {}
    for r in rows[:20]:
        sid = r.get("series_id", "")
        for k in ("latest", "previous", "change", "pct_change", "move_zscore"):
            if _num(r.get(k)) is not None:
                values[f"{sid}.{k}"] = float(r[k])
    return _reading("changes", "changes", body, f"changes:{','.join(body['series'])}:{body['lookback_days']}",
                    f"The largest moves over {body['lookback_days']} days, ranked by how unusual each is",
                    clock.today(), "as each series", list(body["series"]), values,
                    _lines("Ranked", rows, 20) + " move_zscore = the move against that series' own moves.")


# ---- the server's narrative layer --------------------------------------------------------------------------

PRESETS = {
    "eia_weekly": "US weekly petroleum: stocks, supply, retail and spot prices (the table that went with This Week in Petroleum)",
    "gas_weekly": "US natural gas weekly: storage, prices, rigs (the Natural Gas Weekly Update)",
    "cot_weekly": "Commitments of traders: fund positioning and open interest, CFTC and ICE",
    "rig_count": "Baker Hughes rig counts: US, basins, Canada",
}


def report(source: DataSource, preset: str, as_of: str | None = None) -> Reading:
    """ES.Brief / ES.Report: a standing weekly report, its written brief and the signals it fires."""
    if preset not in PRESETS:
        raise ServerError(f"Unknown report {preset!r}. Choose from: {', '.join(PRESETS)}.")
    body = {"preset": preset}
    if as_of:
        body["as_of"] = as_of
    return _report(source, body)


def _report(source, body):
    doc = source.action("report", body)
    rows = doc.get("rows") or []
    values = {}
    for r in rows:
        label = r.get("label") or r.get("series_id", "")
        for k in ("value", "wow", "yoy", "move_z", "seasonal_pctl", "level_z"):
            if _num(r.get(k)) is not None:
                values[f"{label}.{'seasonal_percentile' if k == 'seasonal_pctl' else k}"] = float(r[k])
        # the brief writes stocks in the unit it shows them in (215.9 Million Barrels): those figures are values
        # too, so its sentences can be quoted and traced with their unit
        if r.get("display_units") and r.get("display_units") != r.get("units"):
            for k in ("display_value", "display_wow", "display_yoy"):
                if _num(r.get(k)) is not None:
                    values[f"{label}.{k.replace('display_', '')}_in_{r['display_units'].lower().replace(' ', '_')}"] = float(r[k])
    n = doc.get("narrative") or {}
    sig = n.get("signals") or {}
    for k, v in (sig.get("metrics") or {}).items():
        if _num(v) is not None:
            values[f"metric.{k}"] = float(v)
    units = sorted({u for r in rows for u in (r.get("units"), r.get("display_units")) if u})
    parts = [f"Headline: {n.get('headline', '')}", f"Lede: {n.get('lede', '')}"]
    parts += [f"Also: {s}" for s in (n.get("supporting") or [])]
    parts += [f"Extreme: {s}" for s in (n.get("extremes") or [])]
    parts += [f"Signal firing: {a.get('id')} ({a.get('severity')}): {a.get('trigger')}." for a in (sig.get("active") or [])]
    parts += [f"Contradiction: {c.get('id')}: {(c.get('explanation') or {}).get('narrative', '')}" for c in (sig.get("contradictions") or [])]
    if n.get("quiet_week"):
        parts.append(f"Quiet week: {n.get('quiet_note', '')}")
    parts.append("Rows: value is the latest; wow and yoy are the change on the week and on the year in the row's unit; "
                 "move_z is how unusual this week's move is; seasonal_percentile ranks the level against the same week of earlier years.")
    period = _period(doc, "latest_period")
    return _reading("report", "report", body, f"report:{body['preset']}" + (f":{body['as_of']}" if body.get("as_of") else ""),
                    f"{PRESETS[body['preset']].split(':')[0]}, standing report as of {period}", period,
                    "; ".join(units) or "as each row", sorted({r.get('series_id') for r in rows if r.get('series_id')}),
                    values, " ".join(parts), "written by the server's rules, the same text on every run")


def signals(source: DataSource) -> Reading:
    """The server's whole signal catalogue over its live metric snapshot: what fires and which contradictions."""
    snap = source.snapshot()
    return _signals(source, {"metrics": {k: v for k, v in snap["metrics"].items() if _num(v) is not None}},
                    snap.get("fetched_at", ""))


def _signals(source, body, fetched_at=""):
    doc = source.action("derived_signals", body)
    # the series behind each metric, from the server's own catalogue (its source hints), so the answer names the
    # data the signals were computed from and the staleness check can look at it
    try:
        schema = source.action("derived_signals", {"schema": True}).get("schema") or {}
    except ServerError:
        schema = {}
    behind = sorted({sid for spec in schema.values() if spec.get("key") in body["metrics"]
                     for sid in ((spec.get("source_hint") or {}).get("series_ids") or [])})
    values = {f"metric.{k}": float(v) for k, v in body["metrics"].items()}
    for k in ("signals_evaluated", "active_count", "contradiction_count", "contradiction_total"):
        if _num(doc.get(k)) is not None:
            values[k] = float(doc[k])
    allsig = doc.get("signals") or {}
    parts = []
    for sid in doc.get("active") or []:
        s = allsig.get(sid) or {}
        parts.append(f"Signal firing: {sid} ({s.get('severity', '')}, theme {s.get('theme', '')}): "
                     f"{(s.get('explanation') or {}).get('trigger', '')}.")
    for c in doc.get("contradictions") or []:
        if c.get("active"):
            parts.append(f"Contradiction firing: {c.get('id')} ({c.get('severity')}): "
                         f"{(c.get('explanation') or {}).get('narrative', '')} {(c.get('explanation') or {}).get('trigger', '')}")
    dom = (doc.get("meta_signals") or {}).get("dominant_lens") or {}
    if dom.get("value"):
        parts.append(f"Dominant contradiction: {dom.get('value')}.")
    skipped = doc.get("contradictions_skipped") or []
    if skipped:
        parts.append(f"Not evaluated: {len(skipped)} contradictions lack an input metric.")
    parts.append("A signal is a fixed rule over one metric (a z-score, a seasonal percentile, a spread); a contradiction "
                 "is two or more signals firing together. They describe the data and are not forecasts.")
    return _reading("signals", "derived_signals", body, "signals:live", "The server's signals and contradictions, live",
                    clock.today(), "as each metric", behind, values, " ".join(parts),
                    f"metric snapshot of {_iso(fetched_at)[:10]}" if fetched_at else "")


def describe(source: DataSource, series_id: str) -> Reading:
    """ES.Describe: one card per series: what it is, coverage, latest, statistics, freshness, pipeline, usage."""
    return _describe(source, {"series_id": series_id})


def _describe(source, body):
    name, units = _name(source, body["series_id"])
    doc = source.action("describe", body)
    values = {}
    for part in ("latest", "coverage", "stats", "freshness"):
        values.update(flatten(doc.get(part) or {}, prefix=f"{part}.", depth=1))
    ident = doc.get("identity") or {}
    cov = doc.get("coverage") or {}
    health = doc.get("health") or {}
    prov = doc.get("provenance") or {}
    usage = doc.get("usage") or {}
    ctx = (f"{ident.get('description', '')} Source: {ident.get('source', '')}; publisher {prov.get('publisher', '')}. "
           f"Coverage {_iso(cov.get('first', ''))} to {_iso(cov.get('last', ''))}. "
           f"Health: {health.get('verdict', '')}{': ' + '; '.join(health.get('issues') or []) if health.get('issues') else ''}. "
           f"Used by: {', '.join(r.get('preset', '') for r in usage.get('reports') or []) or 'no standing report'}; "
           f"contradictions {', '.join(usage.get('contradictions') or []) or 'none'}.")
    return _reading("describe", "describe", body, f"describe:{body['series_id']}", f"{name}: the series card",
                    _period(doc.get("latest") or {}, "period"), units, [body["series_id"]], values, ctx)


def events(source: DataSource, days: int = 14) -> Reading:
    """Scheduled releases and expiries in the next `days` days (EIA weekly report, CFTC, OPEC, IEA, ...)."""
    return _events(source, {"days": max(1, min(int(days), 60))})


def _events(source, body):
    doc = source.action("upcoming_events", body)
    ev = doc.get("events") or []
    return _reading("events", "upcoming_events", body, f"events:{body['days']}", f"Scheduled events, next {body['days']} days",
                    clock.today(), "", [], {"count": float(doc.get("count", len(ev)))}, _lines("Events", ev, 20))


def maintenance(source: DataSource, series_id: str = "PET.WPULEUS3.W") -> Reading:
    """Refinery maintenance: weeks where utilisation ran unusually low against its trend."""
    return _maintenance(source, {"series": series_id})


def _maintenance(source, body):
    name, units = _name(source, body["series"])
    doc = source.action("maintenance_signal", body)
    values = flatten(doc, skip=("series_id", "mode", "frequency"))
    values.update(list_values(doc, "events"))
    ctx = _lines("Maintenance events", doc.get("events") or []) + " " + _lines("Flagged weeks", doc.get("flagged_weeks") or [])
    return _reading("maintenance", "maintenance_signal", body, f"maintenance:{body['series']}",
                    f"{name}: weeks of unusually low runs (maintenance)", clock.today(), units, [body["series"]], values, ctx)


# ---- the series itself ---------------------------------------------------------------------------------------

def history(source: DataSource, series_id: str, years: int = 5) -> Reading:
    """The series over a window: its first and last values and the window's range. The page draws it and the
    Excel workbook fills the whole window with ES.Table, so every value can be read and downloaded."""
    if not 1 <= years <= 40:
        raise ServerError("years must be 1 to 40")
    start, end = _window(years)
    return _history(source, {"series": series_id, "start": start, "end": end})


def _history(source, body):
    name, units = _name(source, body["series"])
    start, end = dt.date.fromisoformat(body["start"]), dt.date.fromisoformat(body["end"])
    hist = [(d, v) for d, v in source.history(body["series"], start=start) if d <= end]
    if len(hist) < 2:
        raise ServerError(f"{body['series']} has fewer than two values from {start} to {end}")
    vals = [v for _, v in hist]
    lo, hi = min(hist, key=lambda o: o[1]), max(hist, key=lambda o: o[1])
    values = {"first": hist[0][1], "latest": hist[-1][1], "low": lo[1], "high": hi[1],
              "average": round(sum(vals) / len(vals), 6), "observations": float(len(vals)),
              "change": round(hist[-1][1] - hist[0][1], 6),
              "change_pct": round((hist[-1][1] - hist[0][1]) / hist[0][1] * 100, 6) if hist[0][1] else 0.0}
    years = _years(body, 5)
    ctx = (f"From {hist[0][0]} to {hist[-1][0]}: {len(vals)} values. The low was on {lo[0]}, the high on {hi[0]}. "
           "Every value is in the chart on the page and in the Excel workbook's table.")
    return _reading("history", "", body, f"history:{body['series']}:{years}", f"{name}, last {years} years",
                    hist[-1][0], units, [body["series"]], values, ctx, note=f"first value {hist[0][0]}")


# ---- rebuilding from the request -------------------------------------------------------------------------

def _years(body: dict, default: int = 3) -> int:
    try:
        return max(1, round((dt.date.fromisoformat(body["end"]) - dt.date.fromisoformat(body["start"])).days / 365.25))
    except (KeyError, ValueError):
        return default


REBUILD = {
    "percentile": lambda s, b: _percentile(s, b, _years(b)),
    # The snapshot is read AGAIN: re-sending the body would re-run the rules over the very metric values being
    # checked (a planted crack_321_z of 0.5697 rebuilt as 0.5697 and matched: the adversary, 21 Nov 2026).
    "signals": lambda s, b: signals(s),
    "seasonal": _seasonal,
    "report": _report,
    "describe": _describe,
    "events": _events,
    "maintenance": _maintenance,
    "changes": _changes,
    "history": _history,
}
for _tool, _fn in {"stats": stats, "volatility": volatility, "returns": returns, "breakpoints": breakpoints,
                   "outliers": outliers, "unit_root": unit_root, "acf": acf, "bubble_test": bubble_test,
                   "seasonality": seasonality, "hp_filter": hp_filter, "spread_stats": spread_stats,
                   "rolling_correlation": rolling_correlation, "correlation": correlation,
                   "cointegration": cointegration, "var": var}.items():
    REBUILD[_tool] = (lambda fn: lambda s, b: fn.rebuild(s, b, _years(b)))(_fn)


def rebuild(source: DataSource, reading: Reading) -> Reading | None:
    """The reading again, from the same request sent again. None when the server now refuses it."""
    req = reading.request or {}
    fn = REBUILD.get(req.get("tool"))
    if fn is None:
        return None
    try:
        return fn(source, req["body"])
    except ServerError:
        return None
