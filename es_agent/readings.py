"""Computed readings: a curve, a crack spread, an arbitrage, surprises, a seasonal comparison,
a percentile, positioning, a what-if scenario, a weekly watch, the evidence for a thesis.

Each function reads series through a DataSource and does the arithmetic in code. A reading has
a key ("curve:brent", "crack:3-2-1", ...) that is enough to recompute it, so the output
validator, the eval and the live check can all rebuild the same numbers with
`compute(source, key)`.

Readings that rank a level against its own history also say, in `context`, whether the level
is unusual and when it was last seen: the sentence is written here, from the data, never by
the model.
"""

from __future__ import annotations

import datetime as dt
import re

from . import clock
from .models import Reading
from .sources import DataSource

History = list[tuple[dt.date, float]]

CURVES = {
    "brent": ("Brent futures curve (NYMEX BZ, settles on ICE Brent)", [f"ICE.BRENT.M{i}.D" for i in range(1, 13)]),
    "wti": ("WTI futures curve (NYMEX CL)", [f"NYMEX.WTI.M{i}.D" for i in range(1, 13)]),
    "oman": ("Oman crude futures curve (GME OQD)", [f"GME.OMAN.M{i}.D" for i in range(1, 13)]),
    "rbob": ("RBOB gasoline futures curve (NYMEX RB)", [f"NYMEX.RBOB.M{i}.D" for i in range(1, 13)]),
    "heating_oil": ("Heating oil (ULSD) futures curve (NYMEX HO)", [f"NYMEX.HO.M{i}.D" for i in range(1, 13)]),
}
CRUDE, GASOLINE, DISTILLATE = "PET.RWTC.D", "PET.EER_EPMRU_PF4_RGC_DPG.D", "PET.EER_EPD2F_PF4_Y35NY_DPG.D"
CRACKS = ("3-2-1", "gasoline", "distillate")
GALLONS_PER_BARREL = 42
POSITIONING = {
    "wti": ("WTI crude (NYMEX)", "CFTC.WTI"),
    "brent": ("ICE Brent crude", "ICE_COT.BRENT"),
    "gasoil": ("ICE Low Sulphur Gasoil", "ICE_COT.GASOIL"),
    "natural_gas": ("Natural gas (NYMEX)", "CFTC.NG"),
    "gasoline": ("RBOB gasoline (NYMEX)", "CFTC.RBOB"),
}
PERCENTILE_WEEKS = 156
HISTORY_YEARS = 3
BRENT_SPOT, FREIGHT = "PET.RBRTE.D", "SHIP.BWET.D"
GASOIL, NYH_DIESEL = "ICE.GASOIL.M1.D", "PET.EER_EPD2DXL0_PF4_Y35NY_DPG.D"
GALLONS_PER_TONNE_GASOIL = 312.9  # 7.45 barrels a tonne x 42
ROUTES = ("us_crude_to_europe", "distillate_us_to_europe")


def _since(days: int) -> dt.date:
    return clock.today() - dt.timedelta(days=days)


def _rank(sample: list[float], v: float) -> float:
    """Share of the sample at or below v, in percent."""
    return round(sum(x <= v for x in sample) / len(sample) * 100, 1)


def aligned(source: DataSource, ids: list[str], days: int) -> list[tuple[dt.date, list[float]]]:
    """Rows for the dates every series has, oldest first."""
    hists = [dict(source.history(sid, start=_since(days))) for sid in ids]
    if not hists or not all(hists):
        return []
    common = sorted(set(hists[0]).intersection(*hists[1:]))
    return [(d, [h[d] for h in hists]) for d in common]


def crack_value(kind: str, crude: float, gas: float, dist: float) -> float:
    gas_bbl, dist_bbl = gas * GALLONS_PER_BARREL, dist * GALLONS_PER_BARREL
    return {"3-2-1": (2 * gas_bbl + dist_bbl) / 3, "gasoline": gas_bbl, "distillate": dist_bbl}[kind] - crude


def crack_history(source: DataSource, kind: str, days: int = 366 * HISTORY_YEARS) -> History:
    return [(d, round(crack_value(kind, *v), 6)) for d, v in aligned(source, [CRUDE, GASOLINE, DISTILLATE], days)]


def spread_history(source: DataSource, a: str, b: str, days: int = 366 * HISTORY_YEARS) -> History:
    return [(d, round(v[0] - v[1], 6)) for d, v in aligned(source, [a, b], days)]


# Series that settle on the average price of a month. Their history steps at every month end,
# so a spread against a single-delivery contract or a spot price has no meaningful history.
AVERAGE_PRICE = {"NYMEX.DUBAI.FRONT.D"}
_FUTURE = re.compile(r"\.(M\d+|FRONT|\d{4}-\d{2})\.D$")
_CONTINUOUS = re.compile(r"^(?P<family>.+)\.(?P<leg>M\d+|FRONT)\.D$")
_DATED = re.compile(r"^(?P<family>.+)\.(?P<ym>\d{4}-\d{2})\.D$")
# Which nearby-month series roll together. Brent and Oman fronts both deliver two months after the
# trade month; RBOB and heating oil expire on the same day. WTI and gasoil each have their own calendar.
_CALENDAR = {"ICE.BRENT": "two months ahead", "GME.OMAN": "two months ahead",
             "NYMEX.RBOB": "NYMEX products", "NYMEX.HO": "NYMEX products",
             "NYMEX.WTI": "NYMEX crude", "ICE.GASOIL": "ICE gasoil"}


def pairing_note(a: str, b: str) -> tuple[str, bool]:
    """(a note when the two series are not like for like, whether a spread between them means anything).
    get_spread refuses the pairing when the second is False: the rule lives in the tool, not the prompt."""
    avg = [s for s in (a, b) if s in AVERAGE_PRICE]
    if len(avg) == 1:
        other = b if avg[0] == a else a
        return (f"Not like for like: {avg[0]} is a contract on the average price of its month and {other} is not, so a "
                "spread between them mixes the difference between the two crudes with the shape of the curve. "
                "No spread is given.", False)
    ca, cb, da, db = _CONTINUOUS.match(a), _CONTINUOUS.match(b), _DATED.match(a), _DATED.match(b)
    if da and db:
        if da["ym"] != db["ym"]:
            return (f"Not like for like: {a} and {b} are contracts for different delivery months, so the gap includes "
                    "the shape of the curve. No spread is given. Use two contracts of one delivery month.", False)
        return "", True
    if ca and cb and ca["family"] != cb["family"]:
        front = "FRONT" in (ca["leg"], cb["leg"])
        same_calendar = _CALENDAR.get(ca["family"]) and _CALENDAR.get(ca["family"]) == _CALENDAR.get(cb["family"])
        if not same_calendar or ca["leg"] != cb["leg"] or (front and ca["leg"] != cb["leg"]):
            return (f"Not like for like: {a} and {b} are nearby-month series of two markets whose contracts expire on "
                    "different days, so on most dates they are different delivery months and the history steps at each "
                    "roll. No spread is given. For Brent against WTI use get_futures_spread; otherwise use two dated "
                    "contracts of one delivery month.", False)
        return "", True
    if ca and cb and (ca["leg"] == "FRONT") != (cb["leg"] == "FRONT"):
        return (f"Not like for like: one of {a} and {b} is a continuous series that rolls before expiry and the other "
                "is not. No spread is given.", False)
    if (ca and db) or (da and cb):
        return (f"Not like for like: one of {a} and {b} is a nearby-month series that rolls and the other a single dated "
                "contract, so the history steps at each roll. No spread is given. Use two dated contracts, or two "
                "nearby months of one curve.", False)
    if bool(_FUTURE.search(a)) != bool(_FUTURE.search(b)):
        return ("Not like for like: one series is a future and the other a spot price, so the gap includes the time "
                "structure of the market.", True)
    return "", True


def frequency_note(source: DataSource, a: str, b: str) -> str:
    """A refusal when the two series are published at different rhythms: a daily price minus a monthly
    average is not a spread, and the only dates they share are the firsts of months."""
    freq = [(hit.frequency if (hit := source.meta(s)) else "") or s.rsplit(".", 1)[-1] for s in (a, b)]
    if freq[0] == freq[1]:
        return ""
    return (f"Not like for like: {a} is published at frequency {freq[0]} and {b} at {freq[1]}, so one is a single "
            "observation and the other an average over a longer period. No spread is given.")


def spread_context(source: DataSource, a: str, b: str, period: dt.date) -> tuple[dict[str, float], str, str]:
    """(extras, context, note) for series a minus series b: its percentile and spell over three years
    when the pairing has a usable history, and a note when the two are not like for like."""
    note, usable = pairing_note(a, b)
    hist = spread_history(source, a, b) if usable else []
    if len(hist) < 60 or hist[-1][0] != period:
        return {}, "", note
    extras = {"percentile": _rank([v for _, v in hist], hist[-1][1]), "percentile_years": HISTORY_YEARS}
    more, context = spell(hist, "", "The spread")
    extras.update(more)
    return extras, context, note


SPELL_GAP = 5  # observations back inside the line that do not end a spell


def spell(hist: History, prefix: str = "", what: str = "It") -> tuple[dict[str, float], str]:
    """Is the latest value unusual for this window, how long has it been so, and when was it last so?

    "Unusual" is beyond the window's 10th or 90th percentile line. A spell is a run of observations
    beyond that line; a dip back inside it of up to SPELL_GAP observations does not end the spell.
    Returns the numbers and a sentence built from them.
    """
    ordered = sorted(v for _, v in hist)
    p10, p90 = ordered[int(0.10 * (len(ordered) - 1))], ordered[int(0.90 * (len(ordered) - 1))]
    d, v = hist[-1]
    values = {f"{prefix}p10": p10, f"{prefix}p90": p90}
    # Strictly beyond: the observation that IS the line is not a spell of its own.
    if v > p90:
        side, pct, line = "above", 90, p90
        out = [x > p90 for _, x in hist]
    elif v < p10:
        side, pct, line = "below", 10, p10
        out = [x < p10 for _, x in hist]
    else:
        return values, (f"{what} is inside its usual range, between the 10th and 90th percentile lines "
                        f"({p10:.2f} and {p90:.2f}) of the window.")
    spells, start, last = [], None, None  # (first index, last index) of each spell, oldest first
    for i, flag in enumerate(out):
        if not flag:
            continue
        if start is None:
            start = i
        elif i - last - 1 > SPELL_GAP:
            spells.append((start, last))
            start = i
        last = i
    spells.append((start, last))
    first = hist[spells[-1][0]][0]
    values[f"{prefix}spell_days"] = (d - first).days
    sentence = (f"{what} has been {side} the {pct}th percentile line ({line:.2f}) since {first}, "
                f"{(d - first).days} days, allowing for brief dips back.")
    if len(spells) == 1:
        return values, sentence + " There is no earlier spell beyond that line in the window."
    a, b = spells[-2]
    run = [x for _, x in hist[a:b + 1]]
    extreme = max(run) if side == "above" else min(run)
    values.update({
        f"{prefix}previous_spell_days": (hist[b][0] - hist[a][0]).days,
        f"{prefix}previous_spell_extreme": extreme,
        f"{prefix}days_since_previous_spell": (d - hist[b][0]).days,
    })
    when = (f"on {hist[a][0]} alone" if a == b else
            f"from {hist[a][0]} to {hist[b][0]} ({(hist[b][0] - hist[a][0]).days} days)")
    return values, sentence + f" The previous spell was {when}, reaching {extreme:.2f}."


def curve(source: DataSource, market: str) -> Reading | None:
    if market not in CURVES:
        return None
    title, ids = CURVES[market]
    rows = aligned(source, ids, 60)
    if not rows:
        return None
    d, vals = rows[-1]
    n = len(vals)
    values = {f"M{i + 1}": v for i, v in enumerate(vals)}
    values["M1_minus_M2"] = round(vals[0] - vals[1], 6)
    values[f"M1_minus_M{n}"] = round(vals[0] - vals[-1], 6)
    slope, front = vals[0] - vals[-1], vals[0] - vals[1]

    def shape(x: float) -> str:
        return "backwardation" if x > 0 else "contango" if x < 0 else "flat"

    # Three shapes, not two: the front spread and the whole curve can point opposite ways.
    if slope * front < 0:
        note = (f"mixed: {shape(front)} at the front (M1 {'above' if front > 0 else 'below'} M2) and {shape(slope)} "
                f"across the curve (M1 {'above' if slope > 0 else 'below'} M{n})")
    else:
        note = "backwardation (front above back)" if slope > 0 else "contango (front below back)" if slope < 0 else "flat"
    earlier = [(dd, v) for dd, v in rows if dd <= d - dt.timedelta(days=7)]
    context = ""
    if earlier:
        was = round(earlier[-1][1][0] - earlier[-1][1][-1], 6)
        values[f"M1_minus_M{n}_a_week_earlier"] = was
        if was * slope < 0:
            move = f"changed shape, from {shape(was)} to {shape(slope)},"
        else:
            move = "has steepened" if abs(slope) > abs(was) else "has flattened" if abs(slope) < abs(was) else "has not moved"
        context = f"M1 minus M{n} was {was:.2f} on {earlier[-1][0]} and is {slope:.2f} now: the curve {move} over the week."
    newer = [(dd, v) for dd, v in source.history(ids[0], start=d) if dd > d]
    if newer:  # the front month has a later date than the row with every month
        values["M1_latest"] = newer[-1][1]
        context = (context + f" The latest date with all {n} months is {d}; M1 alone has {newer[-1][0]} at "
                             f"{newer[-1][1]:.2f}.").strip()
    return Reading(key=f"curve:{market}", title=title, period=d, units=source.meta(ids[0]).units,
                   series_ids=ids, values=values, note=note, context=context)


def crack(source: DataSource, kind: str) -> Reading | None:
    if kind not in CRACKS:
        return None
    rows = aligned(source, [CRUDE, GASOLINE, DISTILLATE], 366 * HISTORY_YEARS)
    if len(rows) < 60 or rows[-1][0] < _since(60):
        return None
    d, (crude, gas, dist) = rows[-1]
    hist = [(dd, round(crack_value(kind, *v), 6)) for dd, v in rows]
    values = {
        "crack": hist[-1][1],
        "crude": crude,
        "gasoline_per_gallon": gas,
        "distillate_per_gallon": dist,
        "gasoline_per_barrel": round(gas * GALLONS_PER_BARREL, 6),
        "distillate_per_barrel": round(dist * GALLONS_PER_BARREL, 6),
        "gallons_per_barrel": GALLONS_PER_BARREL,
        "crack_percentile": _rank([v for _, v in hist], hist[-1][1]),
        "percentile_years": HISTORY_YEARS,
    }
    extra, context = spell(hist, "crack_", "The crack")
    values.update(extra)
    return Reading(key=f"crack:{kind}", title=f"{kind} crack spread: WTI, Gulf Coast gasoline, New York Harbor heating oil",
                   period=d, units="Dollars per Barrel", series_ids=[CRUDE, GASOLINE, DISTILLATE], values=values,
                   note="products minus crude, spot prices; 3-2-1 = (2 x gasoline + 1 x distillate) / 3 - crude",
                   context=context)


def _add_months(ym: str, k: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7]) - 1 + k
    return f"{y + m // 12}-{m % 12 + 1:02d}"


def front_contract(source: DataSource, prefix: str) -> tuple[dt.date, str] | None:
    """(latest date, delivery month) of the contract that is M1 today: the dated contract whose
    settlement equals the M1 series on M1's latest date. Read from the data, so the exchange's
    expiry calendar is not repeated here."""
    m1 = source.history(f"{prefix}.M1.D", start=_since(30))
    if not m1:
        return None
    d, v = m1[-1]
    for k in range(0, 5):
        ym = _add_months(d.isoformat()[:7], k)
        px = dict(source.history(f"{prefix}.{ym}.D", start=d - dt.timedelta(days=5))).get(d)
        if px is not None and abs(px - v) < 1e-6:
            return d, ym
    return None


def futures_spread_parts(source: DataSource) -> tuple[str, History] | None:
    """Brent minus WTI on futures of the same delivery month: (delivery month, history of the spread)."""
    b, w = front_contract(source, "ICE.BRENT"), front_contract(source, "NYMEX.WTI")
    if not b or not w:
        return None
    ym = max(b[1], w[1])  # the nearest month both still trade (Brent's front is the later one)
    rows = aligned(source, [f"ICE.BRENT.{ym}.D", f"NYMEX.WTI.{ym}.D"], 366 * HISTORY_YEARS)
    return (ym, [(d, round(v[0] - v[1], 6)) for d, v in rows]) if len(rows) >= 20 else None


def spot_vs_futures(source: DataSource, ym: str) -> tuple[dict[str, float], str, list[str]]:
    """The spot Brent-WTI spread beside the futures spread of one delivery month, on the latest date
    that has all four prices, and where the difference comes from.

    Spot spread minus futures spread equals (spot Brent minus its future) minus (spot WTI minus its
    future): an identity, so the sentence states arithmetic and no cause. Returns values, a sentence
    and the spot series, or empty ones when spot prices are more than 30 days old.
    """
    rows = aligned(source, [BRENT_SPOT, CRUDE, f"ICE.BRENT.{ym}.D", f"NYMEX.WTI.{ym}.D"], 366 * HISTORY_YEARS)
    if len(rows) < 20 or rows[-1][0] < _since(30):
        return {}, "", []
    d, (bs, ws, bf, wf) = rows[-1]
    spot, fut = round(bs - ws, 6), round(bf - wf, 6)
    b_gap, w_gap = round(bs - bf, 6), round(ws - wf, 6)
    spot_pct = _rank([v for dd, v in spread_history(source, BRENT_SPOT, CRUDE) if dd <= d], spot)
    values = {
        "spot_brent": bs, "spot_wti": ws, "spot_brent_minus_wti": spot, "spot_spread_percentile": spot_pct,
        "futures_spread_on_spot_date": fut, "spot_minus_futures_spread": round(spot - fut, 6),
        "spot_brent_minus_its_future": b_gap, "spot_wti_minus_its_future": w_gap,
    }

    def side(x: float) -> str:
        return f"{abs(x):.2f} {'above' if x >= 0 else 'below'}"

    sentence = (f"Spot prices are published days later than futures. On {d}, the latest date with "
                f"both, spot Brent minus spot WTI was {spot:.2f} (percentile {spot_pct:.1f} of its last three years) "
                f"while the {ym} futures spread was {fut:.2f}. The {abs(spot - fut):.2f} difference is the gap between "
                f"spot and futures in each market: spot Brent stood {side(b_gap)} its {ym} future and spot WTI "
                f"{side(w_gap)} its own.")
    return values, sentence, [BRENT_SPOT, CRUDE]


def futures_spread(source: DataSource) -> Reading | None:
    parts = futures_spread_parts(source)
    if parts is None or parts[1][-1][0] < _since(10):
        return None
    ym, hist = parts
    d, spread = hist[-1]
    ids = [f"ICE.BRENT.{ym}.D", f"NYMEX.WTI.{ym}.D"]
    brent, wti = (dict(source.history(i, start=d - dt.timedelta(days=5)))[d] for i in ids)
    values = {"brent": brent, "wti": wti, "brent_minus_wti": spread,
              "spread_percentile": _rank([v for _, v in hist], spread), "observations": len(hist)}
    extra, context = spell(hist, "spread_", "The futures spread")
    values.update(extra)
    spot_values, spot_sentence, spot_ids = spot_vs_futures(source, ym)
    values.update(spot_values)
    context = (context + " " + spot_sentence).strip()
    return Reading(key="fspread:brent_wti", title=f"Brent minus WTI on futures, {ym} delivery", period=d,
                   units="USD/bbl", series_ids=ids + spot_ids, values=values, context=context,
                   note=(f"Both legs are the {ym} delivery contract, the nearest month both still trade, so the spread "
                         "compares like with like. The percentile ranks today against this contract pair's own "
                         "history (up to three years). Brent is NYMEX BZ, which settles against ICE Brent."))


def futures_crack_parts(source: DataSource, kind: str) -> tuple[str, list] | None:
    """A crack spread on futures of one delivery month: (delivery month, aligned rows of crude, gasoline, distillate)."""
    fronts = [front_contract(source, p) for p in ("NYMEX.WTI", "NYMEX.RBOB", "NYMEX.HO")]
    if kind not in CRACKS or not all(fronts):
        return None
    ym = max(f[1] for f in fronts)
    rows = aligned(source, [f"NYMEX.WTI.{ym}.D", f"NYMEX.RBOB.{ym}.D", f"NYMEX.HO.{ym}.D"], 366 * HISTORY_YEARS)
    return (ym, rows) if len(rows) >= 20 else None


def futures_crack(source: DataSource, kind: str) -> Reading | None:
    parts = futures_crack_parts(source, kind)
    if parts is None or parts[1][-1][0] < _since(10):
        return None
    ym, rows = parts
    d, (crude, gas, dist) = rows[-1]
    hist = [(dd, round(crack_value(kind, *v), 6)) for dd, v in rows]
    values = {
        "crack": hist[-1][1], "crude": crude, "gasoline_per_gallon": gas, "distillate_per_gallon": dist,
        "gallons_per_barrel": GALLONS_PER_BARREL,
        "crack_percentile": _rank([v for _, v in hist], hist[-1][1]), "observations": len(hist),
    }
    extra, context = spell(hist, "crack_", "The futures crack")
    values.update(extra)
    return Reading(key=f"fcrack:{kind}", title=f"{kind} crack spread on futures, {ym} delivery: WTI, RBOB, heating oil",
                   period=d, units="Dollars per Barrel",
                   series_ids=[f"NYMEX.WTI.{ym}.D", f"NYMEX.RBOB.{ym}.D", f"NYMEX.HO.{ym}.D"], values=values,
                   note=(f"All three legs are the {ym} delivery contract. Products minus crude; "
                         "3-2-1 = (2 x gasoline + 1 x distillate) / 3 - crude. The percentile ranks today against "
                         "this contract set's own history (up to three years)."), context=context)


def _same_date(d: dt.date, years_back: int) -> dt.date:
    try:
        return d.replace(year=d.year - years_back)
    except ValueError:  # 29 February
        return d.replace(year=d.year - years_back, day=28)


def seasonal_points(source: DataSource, series_id: str, years: int = 5):
    """The latest date and value, and the (date, value) taken for each of the previous `years` years.

    None when the series is unknown or a year has no observation near enough. The Excel sheet for a seasonal
    reading names these same dates, so this is the one place the choice is made.
    """
    hit = source.meta(series_id)
    if hit is None or not 2 <= years <= 10:
        return None
    hist = source.history(series_id, start=_since(366 * (years + 1) + 30))
    if not hist:
        return None
    d1, v1 = hist[-1]
    window = 16 if hit.frequency == "M" else 5
    # A weekly series is matched on the report week (ISO week number), as EIA and ES.Seasonal do, so the
    # five-year average here is the same number they publish. Other series take the nearest date.
    by_week = {(d.isocalendar()[0], d.isocalendar()[1]): (d, v) for d, v in hist} if hit.frequency == "W" else {}
    year, week = d1.isocalendar()[0], d1.isocalendar()[1]
    prior = []
    for k in range(1, years + 1):
        if (year - k, week) in by_week:
            prior.append(by_week[(year - k, week)])
            continue
        target = _same_date(d1, k)
        near = min(hist, key=lambda o: abs((o[0] - target).days))
        if abs((near[0] - target).days) <= window:
            prior.append(near)
    if len(prior) < years:
        return None
    return d1, v1, prior


def seasonal(source: DataSource, series_id: str, years: int = 5) -> Reading | None:
    """Latest value against the same time of year in each of the previous `years` years."""
    points = seasonal_points(source, series_id, years)
    if points is None:
        return None
    hit = source.meta(series_id)
    d1, v1, dated = points
    prior = [v for _, v in dated]
    avg = sum(prior) / len(prior)
    values = {
        "latest": v1,
        "prior_average": round(avg, 6),
        "difference": round(v1 - avg, 6),
        "difference_pct": round((v1 - avg) / avg * 100, 6) if avg else 0.0,
        "prior_low": min(prior),
        "prior_high": max(prior),
        "years": years,
    }
    return Reading(key=f"seasonal:{series_id}:{years}", title=f"{hit.name}: latest against the same time of year, previous {years} years",
                   period=d1, units=hit.units, series_ids=[series_id], values=values,
                   note="above the range" if v1 > max(prior) else "below the range" if v1 < min(prior) else "inside the range")


def positioning(source: DataSource, market: str) -> Reading | None:
    """Managed-money futures positioning from the weekly commitments of traders report."""
    if market not in POSITIONING:
        return None
    label, base = POSITIONING[market]
    ids = [f"{base}.MM_Net", f"{base}.MM_Long", f"{base}.MM_Short", f"{base}.OI"]
    net = source.history(ids[0], start=_since(7 * PERCENTILE_WEEKS + 30))
    if len(net) < 20:
        return None
    net = net[-PERCENTILE_WEEKS:]
    d, latest = net[-1]
    others = [dict(source.history(sid, start=d - dt.timedelta(days=7))).get(d) for sid in ids[1:]]
    if any(o is None for o in others):
        return None
    sample = [v for _, v in net]
    values = {
        "managed_money_net": latest,
        "managed_money_long": others[0],
        "managed_money_short": others[1],
        "open_interest": others[2],
        "net_change_on_week": round(latest - net[-2][1], 6),
        "net_percentile": _rank(sample, latest),
        "percentile_weeks": len(sample),
    }
    extra, context = spell(net, "net_", "The net position")
    values.update(extra)
    return Reading(key=f"positioning:{market}", title=f"{label}: managed-money positioning", period=d, units="contracts",
                   series_ids=ids, values=values,
                   note="net_percentile ranks the latest net position against the last percentile_weeks weekly reports",
                   context=context)


def percentile(source: DataSource, series_id: str, years: int = 3) -> Reading | None:
    """Where the latest value sits in its own last `years` years, and when it was last this unusual."""
    hit = source.meta(series_id)
    if hit is None or not 1 <= years <= 10:
        return None
    hist = source.history(series_id, start=_since(366 * years))
    if len(hist) < 20:
        return None
    d, v = hist[-1]
    sample = [x for _, x in hist]
    mean = sum(sample) / len(sample)
    sd = (sum((x - mean) ** 2 for x in sample) / len(sample)) ** 0.5
    values = {
        "latest": v,
        "percentile": _rank(sample, v),
        "low": min(sample),
        "high": max(sample),
        "average": round(mean, 6),
        "z_score": round((v - mean) / sd, 2) if sd else 0.0,
        "observations": len(sample),
        "years": years,
    }
    extra, context = spell(hist)
    values.update(extra)
    # The window is the one the data has. A series that begins inside the window asked for is ranked against its
    # own shorter history, and the answer must not say "of its last ten years": code says so in a caveat.
    short = hist[0][0] > _since(366 * years) + dt.timedelta(days=45)
    return Reading(key=f"percentile:{series_id}:{years}", title=f"{hit.name}: latest against its last {years} years",
                   period=d, units=hit.units, series_ids=[series_id], values=values,
                   note="percentile 0 = lowest of the window, 100 = highest", context=context,
                   counter=(f"Shorter history: {series_id} begins on {hist[0][0]}, so its percentile, low, high and average are "
                            f"taken over the {(d - hist[0][0]).days} days since then, not over {years} years.") if short else "")


def _arb_score(brent: float, wti: float, freight: float, m1: float, m12: float,
               spreads: list[float], freights: list[float]) -> tuple[float, float, float, str]:
    """(spread percentile, freight percentile, score from -2 to +2, verdict)."""
    spread_pct, freight_pct = _rank(spreads, round(brent - wti, 6)), _rank(freights, freight)
    parts = [(spread_pct - 50) / 50, (50 - freight_pct) / 50, max(-1.0, min(1.0, (m12 - m1) / m1 / 0.1))]
    score = round(sum(parts) / len(parts) * 2, 2)
    verdict = ("strongly favours" if score >= 1 else "tilts towards" if score >= 0.3 else
               "strongly against" if score <= -1 else "tilts against" if score <= -0.3 else "neutral for")
    return spread_pct, freight_pct, score, verdict


def _crude_arb_inputs(source: DataSource):
    """Latest date with every input, the delivery month, the inputs on that date, and the histories behind
    the percentiles. Brent and WTI are futures of one delivery month (the nearest both still trade), so the
    spread compares like with like and is as recent as the futures."""
    parts = futures_spread_parts(source)
    if parts is None:
        return None
    ym = parts[0]
    legs = aligned(source, [f"ICE.BRENT.{ym}.D", f"NYMEX.WTI.{ym}.D"], 366 * HISTORY_YEARS)
    freight = source.history(FREIGHT, start=_since(366 * HISTORY_YEARS))
    m1 = dict(source.history("ICE.BRENT.M1.D", start=_since(60)))
    m12 = dict(source.history("ICE.BRENT.M12.D", start=_since(60)))
    dates = {d for d, _ in legs} & {d for d, _ in freight} & set(m1) & set(m12)
    if not dates or len(freight) < 60 or max(dates) < _since(10):
        return None
    d = max(dates)
    spread_hist = [(dd, round(v[0] - v[1], 6)) for dd, v in legs if dd <= d]
    freight_hist = [(dd, v) for dd, v in freight if dd <= d]
    brent, wti = dict(legs)[d]
    return d, ym, brent, wti, dict(freight)[d], m1[d], m12[d], spread_hist, freight_hist


ARB_NOTE = ("A price indicator, not an executable arbitrage. +2 = wide spread, cheap freight, contango; -2 = narrow "
            "spread, dear freight, backwardation. The spread is Brent minus WTI on futures of one delivery month, ranked "
            "against that contract pair's own history (up to three years). Freight is the Breakwave tanker ETF, a proxy, "
            "not a route rate; no physical differentials or port costs are included.")


def arbitrage(source: DataSource, route: str) -> Reading | None:
    """Whether the prices favour moving a barrel from the US to Europe. No route freight rates or physical
    differentials are in the data, so this is a price indicator, not the full economics. The crude route
    uses futures of one delivery month and sets the spot spread beside it."""
    if route == "us_crude_to_europe":
        got = _crude_arb_inputs(source)
        if got is None:
            return None
        d, ym, brent, wti, fr, m1, m12, spread_hist, freight_hist = got
        spread_pct, freight_pct, score, verdict = _arb_score(
            brent, wti, fr, m1, m12, [v for _, v in spread_hist], [v for _, v in freight_hist])
        values = {
            "brent": brent, "wti": wti, "brent_minus_wti": round(brent - wti, 6), "spread_percentile": spread_pct,
            "spread_observations": len(spread_hist),
            "freight_proxy": fr, "freight_percentile": freight_pct,
            "curve_M1": m1, "curve_M12": m12, "curve_M12_minus_M1": round(m12 - m1, 6),
            "score": score, "percentile_years": HISTORY_YEARS,
        }
        s_extra, s_context = spell(spread_hist, "spread_", "The futures spread")
        f_extra, f_context = spell(freight_hist, "freight_", "The freight proxy")
        values.update(s_extra)
        values.update(f_extra)
        spot_values, spot_sentence, spot_ids = spot_vs_futures(source, ym)
        values.update(spot_values)
        return Reading(
            key=f"arb:{route}",
            title=f"US crude to Europe, price indicator: Brent-WTI on {ym} futures, tanker freight proxy, Brent curve",
            period=d, units="Dollars per Barrel (prices); USD, the ETF's closing price (freight proxy); percent (percentiles)",
            series_ids=[f"ICE.BRENT.{ym}.D", f"NYMEX.WTI.{ym}.D", FREIGHT, "ICE.BRENT.M1.D", "ICE.BRENT.M12.D"] + spot_ids,
            values=values, note=f"score {verdict} US crude exports: " + ARB_NOTE,
            context=" ".join(x for x in (s_context, f_context, spot_sentence) if x))
    if route == "distillate_us_to_europe":
        rows = aligned(source, [GASOIL, NYH_DIESEL], 366 * HISTORY_YEARS)
        if len(rows) < 60 or rows[-1][0] < _since(60):
            return None
        d, (gasoil_t, nyh) = rows[-1]
        hist = [(dd, round(v[0] / GALLONS_PER_TONNE_GASOIL - v[1], 6)) for dd, v in rows]
        gasoil_gal = gasoil_t / GALLONS_PER_TONNE_GASOIL
        values = {
            "ice_gasoil_per_tonne": gasoil_t, "ice_gasoil_per_gallon": round(gasoil_gal, 6),
            "new_york_diesel_per_gallon": nyh, "europe_minus_us_per_gallon": hist[-1][1],
            "difference_percentile": _rank([v for _, v in hist], hist[-1][1]),
            "gallons_per_tonne": GALLONS_PER_TONNE_GASOIL, "percentile_years": HISTORY_YEARS,
        }
        extra, context = spell(hist, "difference_", "The Europe-minus-US gap")
        values.update(extra)
        return Reading(
            key=f"arb:{route}", title="Distillate, US to Europe: ICE gasoil against New York Harbor diesel",
            period=d, units="Dollars per Gallon (difference); Dollars per Tonne (gasoil)",
            series_ids=[GASOIL, NYH_DIESEL], values=values,
            note=("europe_minus_us is the price gap a cargo would earn before freight; a high percentile means Europe is "
                  "paying up relative to the last three years. ICE gasoil is a futures price, New York diesel a spot "
                  "price; no freight is included."), context=context)
    return None


def _num(x: float) -> str:
    return f"{x:+g}"


def arbitrage_scenario(source: DataSource, route: str, brent_change: float, wti_change: float,
                       freight_change_pct: float) -> Reading | None:
    """What the US-crude-to-Europe score would be if prices moved: a what-if, not an observation."""
    if route != "us_crude_to_europe" or not (abs(brent_change) <= 50 and abs(wti_change) <= 50 and abs(freight_change_pct) <= 90):
        return None
    got = _crude_arb_inputs(source)
    if got is None:
        return None
    d, ym, brent, wti, fr, m1, m12, spread_hist, freight_hist = got
    spreads, freights = [v for _, v in spread_hist], [v for _, v in freight_hist]
    o_spread_pct, o_freight_pct, o_score, _ = _arb_score(brent, wti, fr, m1, m12, spreads, freights)
    brent2, wti2, fr2 = brent + brent_change, wti + wti_change, fr * (1 + freight_change_pct / 100)
    s_spread_pct, s_freight_pct, s_score, verdict = _arb_score(brent2, wti2, fr2, m1, m12, spreads, freights)
    values = {
        "brent_change": brent_change, "wti_change": wti_change, "freight_change_pct": freight_change_pct,
        "observed_brent_minus_wti": round(brent - wti, 6), "observed_spread_percentile": o_spread_pct,
        "observed_freight_proxy": fr, "observed_freight_percentile": o_freight_pct, "observed_score": o_score,
        "scenario_brent": round(brent2, 6), "scenario_wti": round(wti2, 6),
        "scenario_brent_minus_wti": round(brent2 - wti2, 6), "scenario_spread_percentile": s_spread_pct,
        "scenario_freight_proxy": round(fr2, 6), "scenario_freight_percentile": s_freight_pct,
        "scenario_score": s_score, "score_change": round(s_score - o_score, 2),
    }
    return Reading(
        key=f"scenario:arb:{route}:{_num(brent_change)}:{_num(wti_change)}:{_num(freight_change_pct)}",
        title="What if: US crude to Europe with changed prices",
        period=d, units="Dollars per Barrel (prices); USD, the ETF's closing price (freight proxy); percent (percentiles)",
        series_ids=[f"ICE.BRENT.{ym}.D", f"NYMEX.WTI.{ym}.D", FREIGHT, "ICE.BRENT.M1.D", "ICE.BRENT.M12.D"],
        values=values, hypothetical=True,
        note=(f"Hypothetical. The stated changes are applied to the {ym} futures prices of {d} and the score is "
              f"recomputed against the same history; the curve is left as it is. In the scenario the score {verdict} US crude "
              "exports. " + ARB_NOTE),
        context="Numbers labelled scenario are not market observations; numbers labelled observed are.")


def crack_scenario(source: DataSource, kind: str, crude_change: float, gasoline_change_pct: float,
                   distillate_change_pct: float) -> Reading | None:
    """What a crack spread would be if crude or products moved: a what-if, not an observation."""
    if kind not in CRACKS or not (abs(crude_change) <= 50 and abs(gasoline_change_pct) <= 90 and abs(distillate_change_pct) <= 90):
        return None
    rows = aligned(source, [CRUDE, GASOLINE, DISTILLATE], 366 * HISTORY_YEARS)
    if len(rows) < 60 or rows[-1][0] < _since(60):
        return None
    d, (crude, gas, dist) = rows[-1]
    sample = [crack_value(kind, *v) for _, v in rows]
    observed = round(crack_value(kind, crude, gas, dist), 6)
    crude2, gas2, dist2 = crude + crude_change, gas * (1 + gasoline_change_pct / 100), dist * (1 + distillate_change_pct / 100)
    scenario = round(crack_value(kind, crude2, gas2, dist2), 6)
    values = {
        "crude_change": crude_change, "gasoline_change_pct": gasoline_change_pct, "distillate_change_pct": distillate_change_pct,
        "observed_crack": observed, "observed_crack_percentile": _rank(sample, observed),
        "scenario_crude": round(crude2, 6), "scenario_gasoline_per_gallon": round(gas2, 6),
        "scenario_distillate_per_gallon": round(dist2, 6),
        "scenario_crack": scenario, "scenario_crack_percentile": _rank(sample, scenario),
        "crack_change": round(scenario - observed, 6),
    }
    return Reading(
        key=f"scenario:crack:{kind}:{_num(crude_change)}:{_num(gasoline_change_pct)}:{_num(distillate_change_pct)}",
        title=f"What if: {kind} crack spread with changed prices", period=d, units="Dollars per Barrel",
        series_ids=[CRUDE, GASOLINE, DISTILLATE], values=values, hypothetical=True,
        note=(f"Hypothetical. The stated changes are applied to the spot prices of {d}; percentiles rank against the "
              "last three years of the observed crack."),
        context="Numbers labelled scenario are not market observations; numbers labelled observed are.")


# The desk's watchlist: what "what moved?" looks across. Labels carry no digits, so they never
# collide with the number-tracing rule.
WATCHLIST = [
    ("WTI spot", "PET.RWTC.D"),
    ("Brent spot", "PET.RBRTE.D"),
    ("Brent front-month future", "ICE.BRENT.M1.D"),
    ("Henry Hub gas", "NG.RNGWHHD.D"),
    ("Gulf Coast gasoline", "PET.EER_EPMRU_PF4_RGC_DPG.D"),
    ("New York heating oil", "PET.EER_EPD2F_PF4_Y35NY_DPG.D"),
    ("ICE gasoil", "ICE.GASOIL.M1.D"),
    ("Tanker freight proxy", "SHIP.BWET.D"),
    ("US commercial crude stocks", "PET.WCESTUS1.W"),
    ("Cushing crude stocks", "PET.W_EPC0_SAX_YCUOK_MBBL.W"),
    ("US gasoline stocks", "PET.WGTSTUS1.W"),
    ("US distillate stocks", "PET.WDISTUS1.W"),
    ("US refinery utilisation", "PET.WPULEUS3.W"),
    ("US crude production", "PET.WCRFPUS2.W"),
    ("EU gas storage fullness", "AGSI.EU.FULL_PCT.D"),
    ("US rig count", "BH.United_States.Total.W"),
    ("WTI fund net position", "CFTC.WTI.MM_Net"),
    ("Brent fund net position", "ICE_COT.BRENT.MM_Net"),
]
SURPRISE_WINDOWS = {"week": 7, "month": 30}
SURPRISE_YEARS, SURPRISE_TOP, STALE_DAYS = 2, 5, 21


def _window_changes(hist: History, days: int) -> list[float]:
    """Each observation minus the last one at least `days` earlier."""
    out, i = [], 0
    for j, (d, v) in enumerate(hist):
        while i + 1 < j and hist[i + 1][0] <= d - dt.timedelta(days=days):
            i += 1
        if j and hist[i][0] <= d - dt.timedelta(days=days):
            out.append(v - hist[i][1])
    return out


def _unusual_moves(source: DataSource, days: int) -> list[tuple]:
    """(abs z, label, series id, units, latest (date, value), change, z) for every fresh watchlist series."""
    found = []
    for label, sid in WATCHLIST:
        hit = source.meta(sid)
        hist = source.history(sid, start=_since(366 * SURPRISE_YEARS + days)) if hit else []
        changes = _window_changes(hist, days)
        if len(changes) < 30 or hist[-1][0] < _since(STALE_DAYS):
            continue
        mean = sum(changes) / len(changes)
        sd = (sum((c - mean) ** 2 for c in changes) / len(changes)) ** 0.5
        if sd:
            z = (changes[-1] - mean) / sd
            found.append((abs(z), label, sid, hit.units, hist[-1], changes[-1], z))
    return sorted(found, reverse=True)


def surprises(source: DataSource, window: str) -> Reading | None:
    """The watchlist moves that are most unusual against their own history. There are no consensus forecasts in
    the data, so a surprise here is a move that is large for that series, not a miss against expectations."""
    if window not in SURPRISE_WINDOWS:
        return None
    days = SURPRISE_WINDOWS[window]
    top = _unusual_moves(source, days)[:SURPRISE_TOP]
    if not top:
        return None
    values, parts = {}, []
    for _, label, sid, units, (d, v), change, z in top:
        values[f"{label}: latest"] = v
        values[f"{label}: change"] = round(change, 6)
        values[f"{label}: z-score"] = round(z, 2)
        parts.append(f"{label} ({units}, {d.isoformat()})")
    return Reading(
        key=f"surprises:{window}", title=f"Most unusual moves over a {window}, from a watchlist of {len(WATCHLIST)} series",
        period=max(t[4][0] for t in top), units="each series in its own units", series_ids=[t[2] for t in top], values=values,
        note=(f"Change over {days} days, ranked by z-score against two years of {days}-day changes in the same series; "
              "beyond plus or minus two is unusual. Not a miss against forecasts: the data holds no consensus. "
              "Units and dates: " + "; ".join(parts) + "."))


WATCH_STOCKS = [("US commercial crude stocks", "PET.WCESTUS1.W"), ("US gasoline stocks", "PET.WGTSTUS1.W"),
                ("US distillate stocks", "PET.WDISTUS1.W")]
WATCH_PAIRS = [("Brent spot", BRENT_SPOT, "WTI spot", CRUDE), ("Gulf Coast gasoline", GASOLINE, "WTI spot", CRUDE)]


def _pct_change(hist: History, days: int) -> float | None:
    if not hist:
        return None
    d, v = hist[-1]
    base = [x for dd, x in hist if dd <= d - dt.timedelta(days=days)]
    return round((v - base[-1]) / base[-1] * 100, 2) if base and base[-1] else None


def watch(source: DataSource, window: str) -> Reading | None:
    """What a desk should look at: unusual moves, stretched positioning, curve change, stocks outside their
    seasonal range, and markets that usually move together going separate ways. A list of flags, each a
    fact from the data; it ranks nothing by importance and predicts nothing."""
    if window not in SURPRISE_WINDOWS:
        return None
    days = SURPRISE_WINDOWS[window]
    values: dict[str, float] = {}
    flags: list[str] = []
    ids: list[str] = []
    latest = None

    for _, label, sid, units, (d, v), change, z in _unusual_moves(source, days)[:3]:
        if abs(z) >= 1.5:
            values[f"{label}: change"] = round(change, 6)
            values[f"{label}: z-score"] = round(z, 2)
            flags.append(f"{label} moved {change:+.2f} {units} (z-score {z:+.2f}, to {d})")
            ids.append(sid)
            latest = max(latest or d, d)

    for market, (label, base) in POSITIONING.items():
        r = positioning(source, market)
        if r and (r.values["net_percentile"] >= 90 or r.values["net_percentile"] <= 10):
            values[f"{label}: fund net percentile"] = r.values["net_percentile"]
            side = "long" if r.values["net_percentile"] >= 90 else "short"
            flags.append(f"funds are stretched {side} in {label} (net position at the {r.values['net_percentile']:.1f} "
                         f"percentile of three years, report of {r.period})")
            ids.append(f"{base}.MM_Net")
            latest = max(latest or r.period, r.period)

    c = curve(source, "brent")
    if c:
        n = len(CURVES["brent"][1])
        now, was = c.values[f"M1_minus_M{n}"], c.values.get(f"M1_minus_M{n}_a_week_earlier")
        values["Brent curve: front minus back"] = now
        if was is not None:
            values["Brent curve: front minus back a week earlier"] = was
            if abs(now - was) >= 1:
                flags.append(f"the Brent curve front-minus-back spread went from {was:.2f} to {now:.2f} in a week ({c.note})")
        ids.append("ICE.BRENT.M1.D")
        latest = max(latest or c.period, c.period)

    for label, sid in WATCH_STOCKS:
        s = seasonal(source, sid, 5)
        if s and s.note != "inside the range":
            values[f"{label}: against five-year average, pct"] = round(s.values["difference_pct"], 2)
            flags.append(f"{label} are {s.note.replace('the range', 'their five-year range')} for the time of year "
                         f"({s.values['difference_pct']:+.2f}% against the average, week of {s.period})")
            ids.append(sid)
            latest = max(latest or s.period, s.period)

    for la, a, lb, b in WATCH_PAIRS:
        pa = _pct_change(source.history(a, start=_since(days + 40)), days)
        pb = _pct_change(source.history(b, start=_since(days + 40)), days)
        if pa is not None and pb is not None and (pa * pb < 0 or abs(pa - pb) >= 3):
            values[f"{la}: change pct"] = pa
            values[f"{lb}: change pct against {la}"] = pb
            flags.append(f"{la} and {lb} parted ways over the {window}: {pa:+.2f}% against {pb:+.2f}%")
            ids += [a, b]

    if latest is None:
        return None
    values["flags"] = len(flags)
    context = ("Flags, in no order of importance: " + "; ".join(flags) + "." if flags
               else f"Nothing on the watchlist is outside its usual range over the {window}.")
    return Reading(
        key=f"watch:{window}", title=f"What to watch: flags from prices, stocks, the curve and positioning over a {window}",
        period=latest, units="each item in its own units", series_ids=list(dict.fromkeys(ids)), values=values,
        note=("A flag is a fact from the data that is outside its usual range: an unusual move, a stretched position, "
              "a curve that changed shape, stocks outside their five-year range, or two related prices diverging. "
              "No forecasts, no news, no ranking by importance."),
        context=context)


# Days a series may trail today before an answer must say so, by how often it is published.
# Daily allows a weekend and a holiday; weekly allows a holiday-delayed release; monthly data
# is published two to three months in arrears.
STALE_AFTER_DAYS = {"D": 4, "W": 14, "M": 100, "Q": 200, "A": 800}


def stale_inputs(source: DataSource, series_ids: list[str]) -> str:
    """A sentence naming every series whose latest value is older than its publishing rhythm allows,
    or "" when all are current. Written by code and added to the answer's caveats by the validator,
    so a week-old spot price cannot pass as today's."""
    today = clock.today()
    behind: dict[dt.date, list[str]] = {}
    for sid in dict.fromkeys(series_ids):
        hit = source.meta(sid)
        freq = (hit.frequency if hit else "") or sid.rsplit(".", 1)[-1]
        limit = STALE_AFTER_DAYS.get(freq)
        hist = source.history(sid, start=today - dt.timedelta(days=900)) if limit else []
        if hist and (today - hist[-1][0]).days > limit:
            behind.setdefault(hist[-1][0], []).append(sid)
    if not behind:
        return ""
    parts = []
    for d in sorted(behind)[:3]:
        ids = behind[d]
        names = ", ".join(ids[:4]) + (f" and {len(ids) - 4} more" if len(ids) > 4 else "")
        parts.append(f"{names} {'ends' if len(ids) == 1 else 'end'} on {d} ({(today - d).days} days ago)")
    more = f"; {len(behind) - 3} more dates not listed" if len(behind) > 3 else ""
    return f"Not current as of {today}: " + "; ".join(parts) + more + "."


US_STOCKS, CUSHING_STOCKS, REFINERY_UTIL = "PET.WCESTUS1.W", "PET.W_EPC0_SAX_YCUOK_MBBL.W", "PET.WPULEUS3.W"
THESES = ("crude_tightness",)
BASE_RATE_YEARS = 8
GROUPS = {"structure": "Time structure", "stocks": "US crude stocks", "refining": "Refining demand",
          "sentiment": "Sentiment (shown, not counted)"}


def _week_index(hist: History) -> dict[tuple[int, int], int]:
    return {(d.isocalendar()[0], d.isocalendar()[1]): i for i, (d, _) in enumerate(hist)}


def _vs_5y(hist: History, idx: dict, i: int, years: int = 5) -> tuple[float, float] | None:
    """Observation i against the average of the same report week in each of the previous years:
    (difference in percent, difference in the series' own units)."""
    d, v = hist[i]
    y, w = d.isocalendar()[0], d.isocalendar()[1]
    prior = [idx.get((y - k, w)) for k in range(1, years + 1)]
    if any(q is None for q in prior):
        return None
    avg = sum(hist[q][1] for q in prior) / years
    return (v - avg) / avg * 100, v - avg


def _gap_4w(hist: History, idx: dict, i: int, years: int = 5) -> tuple[float, float, float] | None:
    """The change over four reports to observation i, the average change over the same four weeks in
    the previous years, and the gap between them as a percentage of the level."""
    d, v = hist[i]
    y, w = d.isocalendar()[0], d.isocalendar()[1]
    prior = [idx.get((y - k, w)) for k in range(1, years + 1)]
    if i < 4 or any(q is None or q < 4 for q in prior):
        return None
    chg = v - hist[i - 4][1]
    usual = sum(hist[q][1] - hist[q - 4][1] for q in prior) / years
    return chg, usual, (chg - usual) / v * 100


def _rolling_rank(hist: History, i: int, window: int) -> float:
    """Percentile of observation i among the `window` observations ending at it."""
    return _rank([v for _, v in hist[max(0, i - window + 1):i + 1]], hist[i][1])


def _verdict(x: float, lo: float, hi: float, tight_when: str) -> int:
    tight = x > hi if tight_when == "high" else x < lo
    loose = x < lo if tight_when == "high" else x > hi
    return 1 if tight else -1 if loose else 0


def _base_rate(hist: History, metric, lo: float, hi: float, tight_when: str, step: int = 1) -> tuple[dict[str, float], str]:
    """How often this line has read tight and loose over the last eight years, by the same rule and
    with only the data available on each date. A line that reads tight most of the time is weak
    evidence when it reads tight today; printing its record lets the reader discount it."""
    start = _since(366 * BASE_RATE_YEARS)
    seen = [_verdict(x, lo, hi, tight_when) for i in range(0, len(hist), step)
            if hist[i][0] >= start and (x := metric(i)) is not None]
    if len(seen) < 52:
        return {}, ""
    tight, loose = round(seen.count(1) / len(seen) * 100, 1), round(seen.count(-1) / len(seen) * 100, 1)
    first = next(d for d, _ in hist if d >= start)
    return ({"tight_share_pct": tight, "loose_share_pct": loose},
            f"; since {first} this line has read tight {tight:.0f}% of the time and loose {loose:.0f}%")


def _scored(name: str, group: str, text: str, x: float, lo: float, hi: float, tight_when: str, date: dt.date,
            ids: list[str], values: dict[str, float], base: tuple[dict[str, float], str] = ({}, "")) -> dict:
    """One line of evidence. Outside the band lo..hi it reads tight or loose; `beyond` is how far
    outside, in widths of the band, so lines can be ordered by strength."""
    beyond = ((x - hi) if x > hi else (lo - x) if x < lo else 0.0) / (hi - lo)
    values = dict(values, **{f"{name}_{k}": v for k, v in base[0].items()})
    return {"name": name, "group": group, "text": text + base[1] + ")", "verdict": _verdict(x, lo, hi, tight_when),
            "beyond": beyond, "date": date, "ids": ids, "values": values}


def _side(x: float, up: str = "above", down: str = "below") -> str:
    return up if x >= 0 else down


def evidence(source: DataSource, thesis: str) -> Reading | None:
    """Evidence for and against a thesis, in groups.

    crude_tightness: ten lines in four groups. Time structure (two curves, spot against futures for
    WTI and Brent), US crude stocks (level against the five-year average, Cushing against its own
    three years, the four-week change against its usual), refining demand (refinery runs against
    the same week of earlier years, the crack spread), and fund positioning, which is sentiment and
    is shown but not counted. The lines inside a group measure nearly the same thing, so the balance
    counts groups: a group reads tight or loose only when more than half of its lines do.

    Thresholds are fixed here and were set from eight years of weekly data so that a line is neutral
    in roughly half of all weeks; each line with a history prints how often it has read tight and
    loose, so a reader can discount one that usually fires. The model writes the conclusion; it
    cannot choose the lines or leave out the ones that disagree: `counter` goes into the caveats.
    """
    if thesis != "crude_tightness":
        return None
    lines = []
    # The curve series start in 2026, so they have no record of their own. EIA's WTI contracts 1 and 4 give a rough
    # one: how often the front has stood above the fourth month. It is a proxy (three months apart, not eleven, and it
    # ends in 2024), and is labelled as one.
    proxy = aligned(source, ["PET.RCLC1.D", "PET.RCLC4.D"], 366 * BASE_RATE_YEARS)
    if len(proxy) >= 250:
        share = round(sum(a > b for _, (a, b) in proxy) / len(proxy) * 100, 1)
        record = (f"no record of its own, the history starts in 2026; as a rough proxy, EIA's WTI contract 1 stood above "
                  f"contract 4 on {share:.0f}% of days from {proxy[0][0]} to {proxy[-1][0]}")
        record_values = {"wti_front_above_fourth_month_share_pct": share}
    else:
        record, record_values = "no record, the history starts in 2026", {}
    for market, label in (("brent", "Brent"), ("wti", "WTI")):
        c = curve(source, market)
        if c:
            n = max(int(k[1:]) for k in c.values if k[1:].isdigit())
            slope = c.values[f"M1_minus_M{n}"]
            pct = round(slope / c.values["M1"] * 100, 2)
            lines.append(_scored(
                f"{market}_curve", "structure",
                f"{label} futures curve: M1 is {abs(slope):.2f} {_side(slope)} M{n}, {abs(pct):.2f}% of M1 "
                f"({c.period}; tight when M1 is more than 2% above, loose when more than 2% below; {record}",
                pct, -2, 2, "high", c.period, c.series_ids,
                {f"{market}_M1_minus_M{n}": slope, f"{market}_slope_pct": pct, **record_values}))
    parts = futures_spread_parts(source)
    rows = aligned(source, [BRENT_SPOT, CRUDE, f"ICE.BRENT.{parts[0]}.D", f"NYMEX.WTI.{parts[0]}.D"], 60) if parts else []
    if rows and rows[-1][0] >= _since(30):
        d, (bs, ws, bf, wf) = rows[-1]
        for name, label, sid, fid, x in (("wti_spot", "WTI spot", CRUDE, f"NYMEX.WTI.{parts[0]}.D", round(ws - wf, 6)),
                                         ("brent_spot", "Brent spot", BRENT_SPOT, f"ICE.BRENT.{parts[0]}.D", round(bs - bf, 6))):
            lines.append(_scored(
                f"{name}_premium", "structure",
                f"{label}: {abs(x):.2f} dollars {_side(x)} its {parts[0]} future "
                f"({d}; tight when more than 1 dollar above, loose when more than 1 dollar below; no record, the history starts in 2026",
                x, -1, 1, "high", d, [sid, fid], {f"{name}_minus_its_future": x}))

    long_ago = _since(366 * (BASE_RATE_YEARS + 7))
    stocks = source.history(US_STOCKS, start=long_ago)
    if len(stocks) > 60 and stocks[-1][0] >= _since(30):
        idx, last = _week_index(stocks), len(stocks) - 1
        got = _vs_5y(stocks, idx, last)
        if got:
            x = round(got[0], 2)
            lines.append(_scored(
                "us_stocks_vs_5y", "stocks",
                f"US commercial crude stocks: {abs(x):.2f}% {_side(x)} the five-year average for the week "
                f"({stocks[-1][0]}; tight below -5%, loose above 5%",
                x, -5, 5, "low", stocks[-1][0], [US_STOCKS], {"us_stocks_vs_5y_pct": x},
                _base_rate(stocks, lambda i: (g := _vs_5y(stocks, idx, i)) and g[0], -5, 5, "low")))
        gap = _gap_4w(stocks, idx, last)
        if gap:
            chg, usual, g = round(gap[0], 3), round(gap[1], 3), round(gap[2], 2)
            lines.append(_scored(
                "us_stocks_4w", "stocks",
                f"US crude stocks over four weeks: a {_side(chg, 'build', 'draw')} of {abs(chg):,.0f} thousand barrels "
                f"against a usual {_side(usual, 'build', 'draw')} of {abs(usual):,.0f} for the time of year, a gap of {abs(g):.2f}% of stocks "
                f"({stocks[-1][0]}; tight below -2%, loose above 2%",
                g, -2, 2, "low", stocks[-1][0], [US_STOCKS],
                {"us_stocks_4w_change": chg, "us_stocks_4w_usual_change": usual, "us_stocks_4w_gap_pct": g},
                _base_rate(stocks, lambda i: (q := _gap_4w(stocks, idx, i)) and q[2], -2, 2, "low")))
    cushing = source.history(CUSHING_STOCKS, start=long_ago)
    if len(cushing) > 200 and cushing[-1][0] >= _since(30):
        x = _rolling_rank(cushing, len(cushing) - 1, PERCENTILE_WEEKS)
        lines.append(_scored(
            "cushing_stocks", "stocks",
            f"Cushing crude stocks: percentile {x:.1f} of their own last three years "
            f"({cushing[-1][0]}; tight below 20, loose above 80",
            x, 20, 80, "low", cushing[-1][0], [CUSHING_STOCKS], {"cushing_stocks_percentile": x},
            _base_rate(cushing, lambda i: _rolling_rank(cushing, i, PERCENTILE_WEEKS) if i >= PERCENTILE_WEEKS else None, 20, 80, "low")))

    runs = source.history(REFINERY_UTIL, start=long_ago)
    if len(runs) > 60 and runs[-1][0] >= _since(30):
        idx = _week_index(runs)
        got = _vs_5y(runs, idx, len(runs) - 1)
        if got:
            x = round(got[1], 2)
            lines.append(_scored(
                "refinery_utilisation", "refining",
                f"US refinery utilisation: {runs[-1][1]:.1f}% of capacity, {abs(x):.2f} points {_side(x)} the five-year average for the week "
                f"({runs[-1][0]}; tight more than 3 points above, loose more than 3 points below",
                x, -3, 3, "high", runs[-1][0], [REFINERY_UTIL],
                {"refinery_utilisation_pct": runs[-1][1], "refinery_utilisation_vs_5y_points": x},
                _base_rate(runs, lambda i: (g := _vs_5y(runs, idx, i)) and g[1], -3, 3, "high")))
    k = crack(source, "3-2-1")
    if k:
        x = k.values["crack_percentile"]
        hist = crack_history(source, "3-2-1", 366 * (BASE_RATE_YEARS + 3))
        lines.append(_scored(
            "crack", "refining",
            f"3-2-1 crack spread: {k.values['crack']:.2f} dollars per barrel, percentile {x:.1f} of three years "
            f"({k.period}; tight above 70, loose below 30",
            x, 30, 70, "high", k.period, k.series_ids, {"crack_spread": k.values["crack"], "crack_spread_percentile": x},
            _base_rate(hist, lambda i: _rolling_rank(hist, i, 750) if i >= 750 else None, 30, 70, "high", step=5)))
    p = positioning(source, "wti")
    if p:
        x = p.values["net_percentile"]
        net = source.history(p.series_ids[0], start=long_ago)
        lines.append(_scored(
            "fund_positioning", "sentiment",
            f"Fund positioning in WTI, a measure of sentiment and not of barrels: managed-money net at "
            f"percentile {x:.1f} of three years ({p.period}; tight above 70, loose below 30",
            x, 30, 70, "high", p.period, p.series_ids[:1], {"fund_net_percentile": x},
            _base_rate(net, lambda i: _rolling_rank(net, i, PERCENTILE_WEEKS) if i >= PERCENTILE_WEEKS else None, 30, 70, "high")))
    if len(lines) < 5:
        return None

    word = {1: "tight", -1: "loose", 0: "neutral"}

    def weigh(some: list[dict]) -> tuple[dict[str, int], list[int], int, int, str]:
        by_group: dict[str, int] = {}
        for g in GROUPS:
            mine = [ln["verdict"] for ln in some if ln["group"] == g]
            if mine:  # a group reads tight or loose only when more than half of its lines do
                by_group[g] = 1 if mine.count(1) * 2 > len(mine) else -1 if mine.count(-1) * 2 > len(mine) else 0
        physical = [v for g, v in by_group.items() if g != "sentiment"]
        total, threshold = sum(physical), (2 if len(physical) >= 3 else len(physical))
        verdict = "points to a tight market" if total >= threshold else "points to a loose market" if total <= -threshold else "is mixed"
        return by_group, physical, total, threshold, verdict

    groups, counted, diff, need, balance = weigh(lines)
    # One judgement is the analyst's, not a threshold: is a high crack spread evidence of CRUDE tightness, or of
    # plentiful crude against dear products? The note says whether today's verdict depends on the answer.
    without = weigh([ln for ln in lines if ln["name"] != "crack"])
    if any(ln["name"] == "crack" for ln in lines):
        depends = (f" Whether a high crack spread is evidence of crude tightness is a judgement, not a threshold. Without that "
                   f"line, refining demand reads {word[without[0].get('refining', 0)]} and the evidence {without[4]}"
                   + (", so today's verdict depends on it." if without[4] != balance else ", so today's verdict does not depend on it."))
    else:
        depends = ""
    values: dict[str, float] = {"groups_counted": len(counted), "groups_tight": counted.count(1), "groups_loose": counted.count(-1),
                                "groups_neutral": counted.count(0), "lines": len(lines)}
    for g, v in groups.items():
        values[f"{g}_group_verdict"] = v
    for ln in lines:
        values.update(ln["values"])
        values[f"{ln['name']}_verdict"] = ln["verdict"]

    def listing(group: list[dict]) -> str:
        return "; ".join(f"{ln['text']} [{word[ln['verdict']]}]" for ln in sorted(group, key=lambda ln: -ln["beyond"]))

    context = " ".join(
        f"{GROUPS[g]}, {word[v]} ({sum(ln['verdict'] == v for ln in lines if ln['group'] == g)} of "
        f"{sum(ln['group'] == g for ln in lines)} lines): {listing([ln for ln in lines if ln['group'] == g])}."
        for g, v in groups.items())
    side = 1 if diff >= need else -1 if diff <= -need else 0
    minority = [ln for ln in lines if side and ln["verdict"] == -side]
    plain = {"structure": "time structure", "stocks": "US crude stocks", "refining": "refining demand"}
    said = ", ".join(f"{plain[g]} {word[v]}, {sum(ln['verdict'] == v for ln in lines if ln['group'] == g)} of "
                     f"{sum(ln['group'] == g for ln in lines)} lines" for g, v in groups.items() if g != "sentiment")
    return Reading(
        key=f"evidence:{thesis}", title="Is the crude market tight? Evidence for and against, in groups",
        period=max(ln["date"] for ln in lines), units="percent, dollars per barrel, thousand barrels (stated on each line)",
        series_ids=list(dict.fromkeys(i for ln in lines for i in ln["ids"])), values=values,
        note=(f"The evidence {balance}: of {len(counted)} groups of physical evidence, {counted.count(1)} read tight, "
              f"{counted.count(-1)} loose and {counted.count(0)} neutral ({said}). The lines inside a group measure nearly "
              "the same thing, so groups are counted, not lines; a group reads tight or loose only when more than half of its "
              "lines do. Fund positioning "
              f"is sentiment: it reads {word[groups.get('sentiment', 0)]} and is shown but not counted. Each line states its "
              "threshold and, where eight years of history exist, how often it has read tight and loose, so a line that "
              "usually fires can be discounted. It covers the futures curves and US data, not the world balance, and it "
              "is not a forecast." + depends),
        context=context,
        counter=("Against the balance of the evidence: " + "; ".join(ln["text"] for ln in minority) + ".") if minority else "")


def default_units(r: Reading) -> dict[str, str]:
    """The unit of each value of the readings whose values are of one unit (or of two, named): a curve, a crack, a
    futures spread or crack, a positioning. The rest (evidence, watch, surprises, arbitrage, scenarios) mix units
    without naming them, and their values stay of unknown unit: matched on the number alone."""
    from .engine import units_of
    kind = r.key.split(":", 1)[0]
    if kind in ("curve", "fspread", "positioning"):
        return units_of(r.values, r.units)
    if kind in ("crack", "fcrack"):
        out = units_of(r.values, "Dollars per Barrel")
        for k in r.values:
            if k.endswith("_per_gallon"):
                out[k] = "Dollars per Gallon"
            elif k == "gallons_per_barrel":
                out[k] = "gallons per barrel"
        return out
    return {}


def compute(source: DataSource, key: str) -> Reading | None:
    """Rebuild a reading from its key."""
    kind, _, rest = key.partition(":")
    try:
        if kind == "curve":
            return curve(source, rest)
        if kind == "crack":
            return crack(source, rest)
        if kind == "fcrack":
            return futures_crack(source, rest)
        if kind == "fspread":
            return futures_spread(source) if rest == "brent_wti" else None
        if kind == "positioning":
            return positioning(source, rest)
        if kind == "arb":
            return arbitrage(source, rest)
        if kind == "surprises":
            return surprises(source, rest)
        if kind == "watch":
            return watch(source, rest)
        if kind == "evidence":
            return evidence(source, rest)
        if kind in ("percentile", "seasonal"):
            series_id, _, years = rest.rpartition(":")
            if not years.isdigit():
                return None
            return (percentile if kind == "percentile" else seasonal)(source, series_id, int(years))
        if kind == "scenario":
            what, target, a, b, c = rest.split(":")
            fn = arbitrage_scenario if what == "arb" else crack_scenario if what == "crack" else None
            return fn(source, target, float(a), float(b), float(c)) if fn else None
    except (ValueError, KeyError):
        return None
    return None
