"""Typed shapes: what the tools return and what the agent must answer with."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field


class SeriesHit(BaseModel):
    series_id: str
    name: str
    units: str
    frequency: str = Field(description="D daily, W weekly, M monthly, A annual")


class Observation(BaseModel):
    series_id: str
    name: str
    units: str
    period: dt.date
    value: float


class Change(BaseModel):
    series_id: str
    name: str
    units: str
    lookback_days: int
    latest_period: dt.date
    latest_value: float
    base_period: dt.date
    base_value: float
    change_abs: float
    change_pct: float


class SeriesFact(BaseModel):
    """One line of the answer. Every number must come from a tool result."""

    series_id: str
    name: str
    units: str
    latest_period: dt.date
    latest_value: float
    lookback_days: int | None = Field(None, description="Set only when the fact comes from get_change")
    base_period: dt.date | None = None
    base_value: float | None = None
    change_abs: float | None = None
    change_pct: float | None = None


class DeskAnswer(BaseModel):
    facts: list[SeriesFact] = Field(description="One entry per series used. Empty if no suitable series was found.")
    summary: str = Field(
        description=(
            "Two or three plain sentences for a desk analyst. Quote numbers exactly as they appear in facts "
            "(same units, at most 2 decimals, no unit conversion). Write dates as YYYY-MM-DD."
        )
    )
    caveats: list[str] = Field(default_factory=list, description="Data gaps, stale dates, or why nothing was found.")
