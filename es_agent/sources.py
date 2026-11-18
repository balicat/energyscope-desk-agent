"""Data sources the agent's tools read from.

The agent never talks to storage directly: tools call a DataSource that is
injected through Pydantic AI's dependency system (RunContext.deps). Two
implementations:

- ParquetLakeSource: reads the EnergyScope Parquet lake on disk (MS-02),
  no network, no key. Used for the offline evals.
- FlightSource: the same calls over Arrow Flight with the public
  energyscope-client package (needs ENERGYSCOPE_API_KEY).

Arithmetic (changes, percentages) lives in metrics.py, not in the model.
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
from typing import Protocol

import polars as pl

from . import clock
from .models import SeriesHit


def parse_period(p: str) -> dt.date:
    """EnergyScope periods arrive as YYYY-MM-DD, YYYYMMDD, YYYYMM or YYYY."""
    s = str(p).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return dt.date.fromisoformat(s)
    if re.fullmatch(r"\d{8}", s):
        return dt.date(int(s[:4]), int(s[4:6]), int(s[6:]))
    if re.fullmatch(r"\d{6}", s):
        return dt.date(int(s[:4]), int(s[4:6]), 1)
    if re.fullmatch(r"\d{4}-\d{2}", s):
        return dt.date(int(s[:4]), int(s[5:7]), 1)
    if re.fullmatch(r"\d{4}", s):
        return dt.date(int(s), 1, 1)
    raise ValueError(f"unrecognised period {p!r}")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower().replace("u.s.", "us"))


class DataSource(Protocol):
    def search(self, query: str, limit: int = 10, dataset: str | None = None) -> list[SeriesHit]: ...
    def meta(self, series_id: str) -> SeriesHit | None: ...
    def history(self, series_id: str, start: dt.date | None = None) -> list[tuple[dt.date, float]]: ...


# Datasets the agent may search, with the one line the model is given about each.
DATASETS = {
    "PET": "EIA petroleum: US and world spot prices, stocks, production, refinery runs, imports, product supplied",
    "NG": "EIA natural gas: Henry Hub, storage, production, consumption, prices by state",
    "ICE": "Brent futures, constant-maturity months M1 to M12 and dated contracts (NYMEX BZ)",
    "ICE_GASOIL": "ICE low sulphur gasoil front month, USD per tonne",
    "CFTC": "CFTC commitments of traders: WTI, natural gas, RBOB, heating oil positioning, weekly",
    "ICE_COT": "ICE commitments of traders: Brent, gasoil, Dubai positioning, weekly",
    "AGSI": "European gas storage by country and EU total: fullness %, TWh, injection, withdrawal, daily",
    "BAKER_HUGHES": "Baker Hughes rig counts: US, basins, Canada, weekly and monthly",
    "SHIP": "Shipping proxies: Breakwave tanker (BWET) and dry bulk (BDRY) freight ETFs, tanker equities",
    "PORTWATCH": "IMF PortWatch: daily tanker and vessel transits at chokepoints (Hormuz, Suez, Bab el-Mandeb), port calls",
    "WEATHER": "NOAA US heating and cooling degree days, weekly, by state, region and fuel",
    "EU_OIL_BULLETIN": "EU weekly consumer fuel prices by country, with and without tax",
    "GAS": "TTF and other gas futures front months, LNG shipping equities",
    "MACRO": "S&P 500, VIX, dollar index, US 10-year yield, daily",
    "FRED": "FRED daily energy prices and macro series",
    "OILEQ": "Oil company share prices",
    "ECB": "ECB euro exchange rates",
    "OPEC": "OPEC Monthly Oil Market Report tables: supply, demand, stocks",
    "JODI": "JODI oil data by country: production, refinery intake, demand, stocks, monthly",
    "IEA": "IEA Oil Market Report balances by country",
    "INTL": "EIA international: production, consumption, reserves by country",
    "PET_IMPORTS": "EIA US crude imports by origin country, refinery and grade, monthly",
}


class ParquetLakeSource:
    """Reads <root>/<DATASET>/series_meta.parquet and year=*/data.parquet."""

    def __init__(self, root: str = "/opt/energyscope/data", datasets: tuple[str, ...] = tuple(DATASETS)):
        self.root = root
        self.datasets = datasets
        frames = []
        for ds in datasets:
            m = pl.read_parquet(f"{root}/{ds}/series_meta.parquet", columns=["series_id", "name", "units", "f"])
            frames.append(m.select(pl.all().cast(pl.Utf8)).with_columns(pl.lit(ds).alias("dataset")))
        self._meta = pl.concat(frames).with_columns(
            pl.col("name").fill_null("").map_elements(_norm, return_dtype=pl.Utf8).alias("_norm"),
        )
        self._by_id = {r["series_id"]: r for r in self._meta.iter_rows(named=True)}

    def _hit(self, r: dict) -> SeriesHit:
        return SeriesHit(series_id=r["series_id"], name=r["name"] or "", units=r["units"] or "", frequency=r["f"] or "")

    def search(self, query: str, limit: int = 10, dataset: str | None = None) -> list[SeriesHit]:
        """All query words in the name first; if none match, names holding most of the words (whole words only)."""
        tokens = list(dict.fromkeys(t for t in _norm(query).split() if t))
        if not tokens:
            return []
        meta = self._meta if dataset is None else self._meta.filter(pl.col("dataset") == dataset.upper())
        expr = pl.lit(True)
        for t in tokens:
            expr = expr & pl.col("_norm").str.contains(t, literal=True)
        rows = meta.filter(expr)
        if rows.is_empty() and len(tokens) > 1:
            # A desk word the publisher does not use ("commercial", "inventories") must not sink the search.
            score = pl.lit(0)
            for t in tokens:
                score = score + pl.col("_norm").str.contains(rf"\b{re.escape(t)}\b").cast(pl.Int32)
            need = max(2, (len(tokens) + 1) // 2)
            rows = meta.with_columns(score.alias("_score")).filter(pl.col("_score") >= need)
        else:
            rows = rows.with_columns(pl.lit(len(tokens)).alias("_score"))
        rows = (
            rows.with_columns(pl.col("name").str.len_chars().alias("_len"))
            .sort(["_score", "_len"], descending=[True, False])
            .head(limit)
        )
        return [self._hit(r) for r in rows.iter_rows(named=True)]

    def meta(self, series_id: str) -> SeriesHit | None:
        r = self._by_id.get(series_id)
        return self._hit(r) if r else None

    def history(self, series_id, start=None):
        r = self._by_id.get(series_id)
        if r is None:
            return []
        files = sorted(glob.glob(f"{self.root}/{r['dataset']}/year=*/data.parquet"))
        if start is not None:
            files = [f for f in files if int(re.search(r"year=(\d{4})", f).group(1)) >= start.year]
        if not files:
            return []
        df = (
            pl.scan_parquet(files)
            .filter(pl.col("series_id").cast(pl.Utf8) == series_id)
            .select("period", "value")
            .collect()
        )
        return _clean(df.iter_rows(), start)


def _clean(rows, start: dt.date | None) -> list[tuple[dt.date, float]]:
    """Sorted (date, value) pairs: no nulls, no unreadable periods, nothing dated after today (forecasts)."""
    end, out = clock.today(), []
    for p, v in rows:
        if v is None:
            continue
        try:
            d = p if isinstance(p, dt.date) else parse_period(p)
        except ValueError:
            continue
        if d <= end and (start is None or d >= start):
            out.append((d, float(v)))
    return sorted(out)


class FixtureSource:
    """A small frozen copy of the series the eval suite touches (fixtures/series.json).

    With LIBRARIAN_TODAY pinned to the fixture's date, every computed number is
    reproducible, so CI can run the suite with no lake and no key.
    """

    def __init__(self, path: str = "fixtures/series.json"):
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        self.as_of = doc["as_of"]
        self._meta = {m["series_id"]: SeriesHit(**m) for m in doc["meta"]}
        self._data = {sid: [(dt.date.fromisoformat(d), v) for d, v in rows] for sid, rows in doc["data"].items()}

    def search(self, query: str, limit: int = 10, dataset: str | None = None) -> list[SeriesHit]:
        tokens = [t for t in _norm(query).split() if t]
        hits = [m for m in self._meta.values() if tokens and all(t in _norm(m.name) for t in tokens)]
        return sorted(hits, key=lambda m: len(m.name))[:limit]

    def meta(self, series_id: str) -> SeriesHit | None:
        return self._meta.get(series_id)

    def history(self, series_id, start=None):
        return _clean(self._data.get(series_id, []), start)


class FlightSource:
    """Same interface over Arrow Flight (pip install energyscope-client)."""

    def __init__(self, api_key: str | None = None, server: str = "data"):
        import energyscope as es  # optional dependency

        self._c = es.Client(api_key or os.environ["ENERGYSCOPE_API_KEY"], server=server)
        self._cache: dict[str, SeriesHit] = {}

    def search(self, query, limit=10, dataset=None):
        hits = [
            SeriesHit(series_id=h["series_id"], name=h.get("name", ""), units=h.get("units", ""), frequency=h.get("f", ""))
            for h in self._c.search(query)[:limit]
        ]
        self._cache.update({h.series_id: h for h in hits})
        return hits

    def meta(self, series_id):
        if series_id not in self._cache:
            rows = self._c.latest(series_id)
            if not rows:
                return None
            r = rows[0]
            self._cache[series_id] = SeriesHit(series_id=series_id, name=r.get("name", ""), units=r.get("units", ""), frequency="")
        return self._cache[series_id]

    def history(self, series_id, start=None):
        df = self._c.get(series_id, start=start.isoformat() if start else None)
        return _clean(df.select("period", "value").iter_rows(), start)


class RecordingSource:
    """Wraps a source and remembers every series it served, to write the fixture file from a real run."""

    def __init__(self, inner: DataSource):
        self.inner = inner
        self._meta: dict[str, SeriesHit] = {}
        self._data: dict[str, dict[dt.date, float]] = {}

    def search(self, query: str, limit: int = 10, dataset: str | None = None) -> list[SeriesHit]:
        hits = self.inner.search(query, limit, dataset)
        self._meta.update({h.series_id: h for h in hits})
        return hits

    def meta(self, series_id: str) -> SeriesHit | None:
        hit = self.inner.meta(series_id)
        if hit is not None:
            self._meta[series_id] = hit
        return hit

    def history(self, series_id, start=None):
        rows = self.inner.history(series_id, start)
        self._data.setdefault(series_id, {}).update(rows)
        return rows

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        doc = {
            "as_of": clock.today().isoformat(),
            "meta": [m.model_dump() for _, m in sorted(self._meta.items())],
            "data": {sid: [[d.isoformat(), v] for d, v in sorted(rows.items())] for sid, rows in sorted(self._data.items())},
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, separators=(",", ":"))
            f.write("\n")
