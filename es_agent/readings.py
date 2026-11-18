"""Computed readings: a futures curve, a crack spread, a seasonal comparison, positioning.

Each function reads series through a DataSource and does the arithmetic in
code. A reading has a key ("curve:brent", "crack:3-2-1", ...) that is enough to
recompute it, so the output validator, the eval and the live check can all
rebuild the same numbers with `compute(source, key)`.
"""

from __future__ import annotations

import datetime as dt

from . import clock
from .models import Reading
from .sources import DataSource

CURVES = {
    "brent": ("Brent futures curve (NYMEX BZ, settles on ICE Brent)", [f"ICE.BRENT.M{i}.D" for i in range(1, 13)]),
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


def _since(days: int) -> dt.date:
    return clock.today() - dt.timedelta(days=days)


def _on_common_date(source: DataSource, ids: list[str], days: int = 60) -> tuple[dt.date, list[float]] | None:
    """Values of every series on the latest date they all have."""
    hists = [dict(source.history(sid, start=_since(days))) for sid in ids]
    common = set(hists[0]).intersection(*hists[1:]) if hists and all(hists) else set()
    if not common:
        return None
    d = max(common)
    return d, [h[d] for h in hists]


def curve(source: DataSource, market: str) -> Reading | None:
    if market not in CURVES:
        return None
    title, ids = CURVES[market]
    got = _on_common_date(source, ids)
    if got is None:
        return None
    d, vals = got
    n = len(vals)
    values = {f"M{i + 1}": v for i, v in enumerate(vals)}
    values["M1_minus_M2"] = round(vals[0] - vals[1], 6)
    values[f"M1_minus_M{n}"] = round(vals[0] - vals[-1], 6)
    slope = vals[0] - vals[-1]
    note = "backwardation (front above back)" if slope > 0 else "contango (front below back)" if slope < 0 else "flat"
    return Reading(key=f"curve:{market}", title=title, period=d, units=source.meta(ids[0]).units,
                   series_ids=ids, values=values, note=note)


def crack(source: DataSource, kind: str) -> Reading | None:
    if kind not in CRACKS:
        return None
    ids = [CRUDE, GASOLINE, DISTILLATE]
    got = _on_common_date(source, ids)
    if got is None:
        return None
    d, (crude, gas, dist) = got
    gas_bbl, dist_bbl = gas * GALLONS_PER_BARREL, dist * GALLONS_PER_BARREL
    products = {"3-2-1": (2 * gas_bbl + dist_bbl) / 3, "gasoline": gas_bbl, "distillate": dist_bbl}[kind]
    values = {
        "crack": round(products - crude, 6),
        "crude": crude,
        "gasoline_per_gallon": gas,
        "distillate_per_gallon": dist,
        "gasoline_per_barrel": round(gas_bbl, 6),
        "distillate_per_barrel": round(dist_bbl, 6),
        "gallons_per_barrel": GALLONS_PER_BARREL,
    }
    return Reading(key=f"crack:{kind}", title=f"{kind} crack spread: WTI, Gulf Coast gasoline, New York Harbor heating oil",
                   period=d, units="Dollars per Barrel", series_ids=ids, values=values,
                   note="products minus crude, spot prices; 3-2-1 = (2 x gasoline + 1 x distillate) / 3 - crude")


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
    if len(net) < 2:
        return None
    d, latest = net[-1]
    others = [dict(source.history(sid, start=d - dt.timedelta(days=7))).get(d) for sid in ids[1:]]
    if any(o is None for o in others):
        return None
    sample = [v for _, v in net[-PERCENTILE_WEEKS:]]
    values = {
        "managed_money_net": latest,
        "managed_money_long": others[0],
        "managed_money_short": others[1],
        "open_interest": others[2],
        "net_change_on_week": round(latest - net[-2][1], 6),
        "net_percentile": round(sum(v <= latest for v in sample) / len(sample) * 100, 1),
        "percentile_weeks": len(sample),
    }
    return Reading(key=f"positioning:{market}", title=f"{label}: managed-money positioning", period=d, units="contracts",
                   series_ids=ids, values=values,
                   note="net_percentile ranks the latest net position against the last percentile_weeks weekly reports")


def _rank(sample: list[float], v: float) -> float:
    """Share of the sample at or below v, in percent."""
    return round(sum(x <= v for x in sample) / len(sample) * 100, 1)


def percentile(source: DataSource, series_id: str, years: int = 3) -> Reading | None:
    """Where the latest value sits in its own last `years` years."""
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
    return Reading(key=f"percentile:{series_id}:{years}", title=f"{hit.name}: latest against its last {years} years",
                   period=d, units=hit.units, series_ids=[series_id], values=values,
                   note="percentile 0 = lowest of the window, 100 = highest")


ARB_YEARS = 3
BRENT_SPOT, FREIGHT = "PET.RBRTE.D", "SHIP.BWET.D"
GASOIL, NYH_DIESEL = "ICE.GASOIL.M1.D", "PET.EER_EPD2DXL0_PF4_Y35NY_DPG.D"
GALLONS_PER_TONNE_GASOIL = 312.9  # 7.45 barrels a tonne x 42
ROUTES = ("us_crude_to_europe", "distillate_us_to_europe")


def _paired(source: DataSource, a: str, b: str) -> list[tuple[dt.date, float, float]]:
    start = _since(366 * ARB_YEARS)
    hb = dict(source.history(b, start=start))
    return [(d, va, hb[d]) for d, va in source.history(a, start=start) if d in hb]


def arbitrage(source: DataSource, route: str) -> Reading | None:
    """Whether the prices favour moving a barrel from the US to Europe. No route freight rates or physical
    differentials are in the data, so this is the price side of the arbitrage, not the full economics."""
    if route == "us_crude_to_europe":
        pairs = _paired(source, BRENT_SPOT, CRUDE)
        freight = source.history(FREIGHT, start=_since(366 * ARB_YEARS))
        m1 = dict(source.history("ICE.BRENT.M1.D", start=_since(60)))
        m12 = dict(source.history("ICE.BRENT.M12.D", start=_since(60)))
        dates = {d for d, _, _ in pairs} & {d for d, _ in freight} & set(m1) & set(m12)
        if not dates or len(pairs) < 60 or len(freight) < 60:
            return None
        d = max(dates)
        spreads = [a - b for dd, a, b in pairs if dd <= d]
        brent, wti = next((a, b) for dd, a, b in pairs if dd == d)
        fr_sample = [v for dd, v in freight if dd <= d]
        fr = dict(freight)[d]
        spread_pct, freight_pct = _rank(spreads, brent - wti), _rank(fr_sample, fr)
        slope = m12[d] - m1[d]
        parts = [(spread_pct - 50) / 50, (50 - freight_pct) / 50, max(-1.0, min(1.0, slope / m1[d] / 0.1))]
        score = round(sum(parts) / len(parts) * 2, 2)
        verdict = ("strongly favours" if score >= 1 else "tilts towards" if score >= 0.3 else
                   "strongly against" if score <= -1 else "tilts against" if score <= -0.3 else "neutral for")
        values = {
            "brent": brent, "wti": wti, "brent_minus_wti": round(brent - wti, 6), "spread_percentile": spread_pct,
            "freight_proxy": fr, "freight_percentile": freight_pct,
            "curve_M1": m1[d], "curve_M12": m12[d], "curve_M12_minus_M1": round(slope, 6),
            "score": score, "percentile_years": ARB_YEARS,
        }
        return Reading(
            key=f"arb:{route}", title="US crude to Europe: Brent-WTI spread, tanker freight proxy, Brent curve",
            period=d, units="Dollars per Barrel (prices); index points (freight proxy); percent (percentiles)",
            series_ids=[BRENT_SPOT, CRUDE, FREIGHT, "ICE.BRENT.M1.D", "ICE.BRENT.M12.D"], values=values,
            note=(f"score {verdict} US crude exports: +2 = wide spread, cheap freight, contango; -2 = narrow spread, dear "
                  "freight, backwardation. Freight is the Breakwave tanker ETF, a proxy, not a route rate; no physical "
                  "differentials or port costs are included."))
    if route == "distillate_us_to_europe":
        pairs = _paired(source, GASOIL, NYH_DIESEL)
        if len(pairs) < 60 or pairs[-1][0] < _since(60):
            return None
        d, gasoil_t, nyh = pairs[-1]
        diffs = [a / GALLONS_PER_TONNE_GASOIL - b for _, a, b in pairs]
        gasoil_gal = gasoil_t / GALLONS_PER_TONNE_GASOIL
        values = {
            "ice_gasoil_per_tonne": gasoil_t, "ice_gasoil_per_gallon": round(gasoil_gal, 6),
            "new_york_diesel_per_gallon": nyh, "europe_minus_us_per_gallon": round(gasoil_gal - nyh, 6),
            "difference_percentile": _rank(diffs, diffs[-1]), "gallons_per_tonne": GALLONS_PER_TONNE_GASOIL,
            "percentile_years": ARB_YEARS,
        }
        return Reading(
            key=f"arb:{route}", title="Distillate, US to Europe: ICE gasoil against New York Harbor diesel",
            period=d, units="Dollars per Gallon (difference); Dollars per Tonne (gasoil)",
            series_ids=[GASOIL, NYH_DIESEL], values=values,
            note=("europe_minus_us is the price gap a cargo would earn before freight; a high percentile means Europe is "
                  "paying up relative to the last three years. ICE gasoil is a futures price, New York diesel a spot "
                  "price; no freight is included."))
    return None


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


def _window_changes(hist: list[tuple[dt.date, float]], days: int) -> list[float]:
    """Each observation minus the last one at least `days` earlier."""
    out, i = [], 0
    for j, (d, v) in enumerate(hist):
        while i + 1 < j and hist[i + 1][0] <= d - dt.timedelta(days=days):
            i += 1
        if j and hist[i][0] <= d - dt.timedelta(days=days):
            out.append(v - hist[i][1])
    return out


def surprises(source: DataSource, window: str) -> Reading | None:
    """The watchlist moves that are most unusual against their own history. There are no consensus forecasts in
    the data, so a surprise here is a move that is large for that series, not a miss against expectations."""
    if window not in SURPRISE_WINDOWS:
        return None
    days = SURPRISE_WINDOWS[window]
    found = []
    for label, sid in WATCHLIST:
        hit = source.meta(sid)
        hist = source.history(sid, start=_since(366 * SURPRISE_YEARS + days)) if hit else []
        changes = _window_changes(hist, days)
        if len(changes) < 30 or hist[-1][0] < _since(STALE_DAYS):
            continue
        mean = sum(changes) / len(changes)
        sd = (sum((c - mean) ** 2 for c in changes) / len(changes)) ** 0.5
        if not sd:
            continue
        found.append((abs((changes[-1] - mean) / sd), label, sid, hit.units, hist[-1], changes[-1], (changes[-1] - mean) / sd))
    if not found:
        return None
    top = sorted(found, reverse=True)[:SURPRISE_TOP]
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


def compute(source: DataSource, key: str) -> Reading | None:
    """Rebuild a reading from its key."""
    kind, _, rest = key.partition(":")
    if kind == "curve":
        return curve(source, rest)
    if kind == "crack":
        return crack(source, rest)
    if kind == "positioning":
        return positioning(source, rest)
    if kind == "arb":
        return arbitrage(source, rest)
    if kind == "surprises":
        return surprises(source, rest)
    if kind == "percentile":
        series_id, _, years = rest.rpartition(":")
        return percentile(source, series_id, int(years)) if years.isdigit() else None
    if kind == "seasonal":
        series_id, _, years = rest.rpartition(":")
        return seasonal(source, series_id, int(years)) if years.isdigit() else None
    return None
