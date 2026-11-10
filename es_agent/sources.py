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
import os
import re
from typing import Protocol

import polars as pl

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
    def search(self, query: str, limit: int = 10) -> list[SeriesHit]: ...
    def meta(self, series_id: str) -> SeriesHit | None: ...
    def history(self, series_id: str, start: dt.date | None = None) -> list[tuple[dt.date, float]]: ...


class ParquetLakeSource:
    """Reads <root>/<DATASET>/series_meta.parquet and year=*/data.parquet."""

    def __init__(self, root: str = "/opt/energyscope/data", datasets: tuple[str, ...] = ("PET", "NG")):
        self.root = root
        self.datasets = datasets
        frames = []
        for ds in datasets:
            m = pl.read_parquet(f"{root}/{ds}/series_meta.parquet", columns=["series_id", "name", "units", "f"])
            frames.append(m.with_columns(pl.lit(ds).alias("dataset")))
        self._meta = pl.concat(frames).with_columns(
            pl.col("series_id").cast(pl.Utf8),
            pl.col("name").map_elements(_norm, return_dtype=pl.Utf8).alias("_norm"),
        )
        self._by_id = {r["series_id"]: r for r in self._meta.iter_rows(named=True)}

    def _hit(self, r: dict) -> SeriesHit:
        return SeriesHit(series_id=r["series_id"], name=r["name"], units=r["units"] or "", frequency=r["f"] or "")

    def search(self, query: str, limit: int = 10) -> list[SeriesHit]:
        tokens = [t for t in _norm(query).split() if t]
        if not tokens:
            return []
        expr = pl.lit(True)
        for t in tokens:
            expr = expr & pl.col("_norm").str.contains(t, literal=True)
        rows = (
            self._meta.filter(expr)
            .with_columns(pl.col("name").str.len_chars().alias("_len"))
            .sort("_len")
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
        out = sorted((parse_period(p), float(v)) for p, v in df.iter_rows() if v is not None)
        return [o for o in out if start is None or o[0] >= start]


class FlightSource:
    """Same interface over Arrow Flight (pip install energyscope-client)."""

    def __init__(self, api_key: str | None = None, server: str = "data"):
        import energyscope as es  # optional dependency

        self._c = es.Client(api_key or os.environ["ENERGYSCOPE_API_KEY"], server=server)
        self._cache: dict[str, SeriesHit] = {}

    def search(self, query, limit=10):
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
        return sorted((parse_period(p), float(v)) for p, v in df.select("period", "value").iter_rows() if v is not None)
