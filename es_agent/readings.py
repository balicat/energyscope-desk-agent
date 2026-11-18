"""Computed readings: a futures curve, a crack spread, a seasonal comparison, positioning.

Each function reads series through a DataSource and does the arithmetic in
code. A reading has a key ("curve:brent", "crack:3-2-1", ...) that is enough to
recompute it, so the output validator, the eval and the live check can all
rebuild the same numbers with `compute(source, key)`.
"""

from __future__ import annotations

import datetime as dt

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
    return dt.date.today() - dt.timedelta(days=days)


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


def compute(source: DataSource, key: str) -> Reading | None:
    """Rebuild a reading from its key."""
    kind, _, rest = key.partition(":")
    if kind == "curve":
        return curve(source, rest)
    if kind == "crack":
        return crack(source, rest)
    if kind == "positioning":
        return positioning(source, rest)
    if kind == "seasonal":
        series_id, _, years = rest.rpartition(":")
        return seasonal(source, series_id, int(years)) if years.isdigit() else None
    return None
