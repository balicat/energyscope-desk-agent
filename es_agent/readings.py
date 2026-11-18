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
    if v >= p90:
        side, pct, line = "above", 90, p90
        out = [x >= p90 for _, x in hist]
    elif v <= p10:
        side, pct, line = "below", 10, p10
        out = [x <= p10 for _, x in hist]
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
    slope = vals[0] - vals[-1]
    note = "backwardation (front above back)" if slope > 0 else "contango (front below back)" if slope < 0 else "flat"
    earlier = [(dd, v) for dd, v in rows if dd <= d - dt.timedelta(days=7)]
    context = ""
    if earlier:
        was = round(earlier[-1][1][0] - earlier[-1][1][-1], 6)
        values[f"M1_minus_M{n}_a_week_earlier"] = was
        move = "steepened" if abs(slope) > abs(was) else "flattened" if abs(slope) < abs(was) else "not moved"
        context = (f"M1 minus M{n} was {was:.2f} on {earlier[-1][0]} and is {slope:.2f} now: the curve has {move} over the week.")
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


def seasonal(source: DataSource, series_id: str, years: int = 5) -> Reading | None:
    """Latest value against the same time of year in each of the previous `years` years."""
    hit = source.meta(series_id)
    if hit is None or not 2 <= years <= 10:
        return None
    hist = source.history(series_id, start=_since(366 * (years + 1) + 30))
    if not hist:
        return None
    d1, v1 = hist[-1]
    window = 16 if hit.frequency == "M" else 5
    prior = []
    for k in range(1, years + 1):
        target = _same_date(d1, k)
        near = min(hist, key=lambda o: abs((o[0] - target).days))
        if abs((near[0] - target).days) <= window:
            prior.append(near[1])
    if len(prior) < years:
        return None
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
    return Reading(key=f"percentile:{series_id}:{years}", title=f"{hit.name}: latest against its last {years} years",
                   period=d, units=hit.units, series_ids=[series_id], values=values,
                   note="percentile 0 = lowest of the window, 100 = highest", context=context)


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
            period=d, units="Dollars per Barrel (prices); index points (freight proxy); percent (percentiles)",
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
        period=d, units="Dollars per Barrel (prices); index points (freight proxy); percent (percentiles)",
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


def _usual_change(source: DataSource, series_id: str, days: int = 28, years: int = 5):
    """(date, latest, change over `days`, average change over the same days in each prior year)."""
    hist = source.history(series_id, start=_since(366 * (years + 1) + 60))
    if len(hist) < 60:
        return None

    def at(target: dt.date) -> float | None:
        near = min(hist, key=lambda o: abs((o[0] - target).days))
        return near[1] if abs((near[0] - target).days) <= 5 else None

    d1, v1 = hist[-1]
    base = at(d1 - dt.timedelta(days=days))
    prior = [(at(_same_date(d1, k)), at(_same_date(d1, k) - dt.timedelta(days=days))) for k in range(1, years + 1)]
    if base is None or any(a is None or b is None for a, b in prior):
        return None
    return d1, v1, v1 - base, sum(a - b for a, b in prior) / years


def _scored(name: str, text: str, x: float, lo: float, hi: float, tight_when: str, date: dt.date,
            ids: list[str], values: dict[str, float]) -> dict:
    """One line of evidence. Outside the band lo..hi it reads tight or loose; `beyond` is how far
    outside, in widths of the band, so lines can be ordered by strength."""
    tight = x > hi if tight_when == "high" else x < lo
    loose = x < lo if tight_when == "high" else x > hi
    beyond = ((x - hi) if x > hi else (lo - x) if x < lo else 0.0) / (hi - lo)
    return {"name": name, "text": text, "verdict": 1 if tight else -1 if loose else 0, "beyond": beyond,
            "date": date, "ids": ids, "values": values}


def _side(x: float, up: str = "above", down: str = "below") -> str:
    return up if x >= 0 else down


def evidence(source: DataSource, thesis: str) -> Reading | None:
    """Evidence for and against a thesis, one fixed line at a time.

    crude_tightness: ten lines (two curves, stocks against the five-year average, the four-week stock
    change against its usual, spot against futures, refinery runs, the crack spread, fund positioning).
    Each is a level or a change against its own norm with a threshold fixed here; lines count equally.
    The model writes the conclusion; it cannot choose the lines or leave out the ones that disagree,
    because `counter` goes into the caveats by code.
    """
    if thesis != "crude_tightness":
        return None
    lines = []
    for market, label in (("brent", "Brent"), ("wti", "WTI")):
        c = curve(source, market)
        if c:
            n = max(int(k[1:]) for k in c.values if k[1:].isdigit())
            slope = c.values[f"M1_minus_M{n}"]
            pct = round(slope / c.values["M1"] * 100, 2)
            lines.append(_scored(
                f"{market}_curve", f"{label} futures curve: M1 is {abs(slope):.2f} {_side(slope)} M{n}, {abs(pct):.2f}% of M1 "
                f"({c.period}; tight when M1 is more than 2% above, loose when more than 2% below)",
                pct, -2, 2, "high", c.period, c.series_ids,
                {f"{market}_M1_minus_M{n}": slope, f"{market}_slope_pct": pct}))
    for name, label, sid, band in (("us_stocks", "US commercial crude stocks", US_STOCKS, 3),
                                   ("cushing_stocks", "Cushing crude stocks", CUSHING_STOCKS, 10)):
        r = seasonal(source, sid, 5)
        if r:
            x = round(r.values["difference_pct"], 2)
            lines.append(_scored(
                f"{name}_vs_5y", f"{label}: {abs(x):.2f}% {_side(x)} the five-year average for the week, {r.note} "
                f"({r.period}; tight below -{band}%, loose above {band}%)",
                x, -band, band, "low", r.period, [sid], {f"{name}_vs_5y_pct": x}))
    got = _usual_change(source, US_STOCKS)
    if got:
        d, level, chg, usual = got
        chg, usual = round(chg, 3), round(usual, 3)
        gap = round((chg - usual) / level * 100, 2)
        lines.append(_scored(
            "us_stocks_4w", f"US crude stocks over four weeks: a {_side(chg, 'build', 'draw')} of {abs(chg):,.0f} thousand barrels "
            f"against a usual {_side(usual, 'build', 'draw')} of {abs(usual):,.0f} for the time of year, a gap of {abs(gap):.2f}% of stocks "
            f"({d}; tight below -0.5%, loose above 0.5%)",
            gap, -0.5, 0.5, "low", d, [US_STOCKS],
            {"us_stocks_4w_change": chg, "us_stocks_4w_usual_change": usual, "us_stocks_4w_gap_pct": gap}))
    parts = futures_spread_parts(source)
    rows = aligned(source, [BRENT_SPOT, CRUDE, f"ICE.BRENT.{parts[0]}.D", f"NYMEX.WTI.{parts[0]}.D"], 60) if parts else []
    if rows and rows[-1][0] >= _since(30):
        d, (bs, ws, bf, wf) = rows[-1]
        for name, label, sid, fid, x in (("wti_spot", "WTI spot", CRUDE, f"NYMEX.WTI.{parts[0]}.D", round(ws - wf, 6)),
                                         ("brent_spot", "Brent spot", BRENT_SPOT, f"ICE.BRENT.{parts[0]}.D", round(bs - bf, 6))):
            lines.append(_scored(
                f"{name}_premium", f"{label}: {abs(x):.2f} dollars {_side(x)} its {parts[0]} future "
                f"({d}; tight when more than 1 dollar above, loose when more than 1 dollar below)",
                x, -1, 1, "high", d, [sid, fid], {f"{name}_minus_its_future": x}))
    runs = source.history(REFINERY_UTIL, start=_since(60))
    if runs and runs[-1][0] >= _since(30):
        d, x = runs[-1]
        lines.append(_scored(
            "refinery_utilisation", f"US refinery utilisation: {x:.1f}% of capacity ({d}; tight above 92%, loose below 85%)",
            x, 85, 92, "high", d, [REFINERY_UTIL], {"refinery_utilisation_pct": x}))
    k = crack(source, "3-2-1")
    if k:
        x = k.values["crack_percentile"]
        lines.append(_scored(
            "crack", f"3-2-1 crack spread: {k.values['crack']:.2f} dollars per barrel, percentile {x:.1f} of three years "
            f"({k.period}; tight above 70, loose below 30)",
            x, 30, 70, "high", k.period, k.series_ids, {"crack_spread": k.values["crack"], "crack_spread_percentile": x}))
    p = positioning(source, "wti")
    if p:
        x = p.values["net_percentile"]
        lines.append(_scored(
            "fund_positioning", f"Fund positioning in WTI, a measure of sentiment and not of barrels: managed-money net at "
            f"percentile {x:.1f} of three years ({p.period}; tight above 70, loose below 30)",
            x, 30, 70, "high", p.period, p.series_ids[:1], {"fund_net_percentile": x}))
    if len(lines) < 5:
        return None
    tight = sorted((ln for ln in lines if ln["verdict"] > 0), key=lambda ln: -ln["beyond"])
    loose = sorted((ln for ln in lines if ln["verdict"] < 0), key=lambda ln: -ln["beyond"])
    neutral = [ln for ln in lines if ln["verdict"] == 0]
    n, diff = len(lines), len(tight) - len(loose)
    balance = "points to a tight market" if diff >= 3 else "points to a loose market" if diff <= -3 else "is mixed"
    values: dict[str, float] = {"lines": n, "tight": len(tight), "loose": len(loose), "neutral": len(neutral)}
    for ln in lines:
        values.update(ln["values"])
        values[f"{ln['name']}_verdict"] = ln["verdict"]

    def listing(group: list[dict]) -> str:
        return "; ".join(ln["text"] for ln in group)

    context = " ".join(s for s in (
        f"Tight ({len(tight)} of {n} lines, the one furthest beyond its threshold first): {listing(tight)}." if tight else "",
        f"Loose ({len(loose)} of {n}): {listing(loose)}." if loose else "",
        f"Neutral ({len(neutral)} of {n}): {listing(neutral)}." if neutral else "") if s)
    minority = loose if diff >= 3 else tight if diff <= -3 else []
    return Reading(
        key=f"evidence:{thesis}", title="Is the crude market tight? Evidence for and against",
        period=max(ln["date"] for ln in lines), units="percent, dollars per barrel, thousand barrels (stated on each line)",
        series_ids=list(dict.fromkeys(i for ln in lines for i in ln["ids"])), values=values,
        note=(f"The evidence {balance}: {len(tight)} of {n} lines read tight, {len(loose)} loose, {len(neutral)} neutral. "
              "Each line is a level or a change against its own norm, with a fixed threshold stated beside it; lines count "
              "equally. It covers the futures curves and US data, not the world balance, and it is not a forecast."),
        context=context,
        counter=f"Against the balance of the evidence: {listing(minority)}." if minority else "")


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
