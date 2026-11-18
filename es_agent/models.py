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


class Spread(BaseModel):
    """series_a minus series_b on the latest date both have a value."""

    series_a: str
    name_a: str
    series_b: str
    name_b: str
    units: str
    period: dt.date
    value_a: float
    value_b: float
    spread: float
    extras: dict[str, float] = Field(default_factory=dict, description="Written by code: where the spread ranks in its own history. Leave as returned.")
    context: str = Field("", description="Written by code: whether the spread is unusual and when it was last so.")
    note: str = Field("", description="Written by code when the two series are not like for like. Code adds it to the caveats.")


class Reading(BaseModel):
    """A computed result from one tool call: a curve, a crack spread, a seasonal comparison, positioning."""

    key: str = Field(description="Identifies the computation, e.g. 'curve:brent'. Cite this key in the answer.")
    title: str
    period: dt.date
    units: str
    series_ids: list[str]
    values: dict[str, float]
    note: str = ""
    context: str = Field("", description="Written by code: whether the level is unusual and when it was last seen.")
    hypothetical: bool = Field(False, description="True for a what-if scenario: its scenario_ values are not observations.")
    counter: str = Field("", description="Written by code: the lines of evidence that point against the balance. Code adds it to the caveats.")


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
    spreads: list[Spread] = Field(
        default_factory=list, description="One entry per get_spread result used, copied unchanged. Usually empty."
    )
    cites: list[str] = Field(
        default_factory=list,
        description="Keys of the readings used (the 'key' a curve, crack, seasonal or positioning tool returned).",
    )
    readings: list[Reading] = Field(
        default_factory=list, description="Leave empty. The system copies the cited readings in from the tool results."
    )
    summary: str = Field(
        description=(
            "Two or three plain sentences for a desk analyst. Quote numbers exactly as they appear in facts, spreads or the cited readings "
            "(same units, at most 2 decimals, no unit conversion). Write dates as YYYY-MM-DD."
        )
    )
    caveats: list[str] = Field(default_factory=list, description="Data gaps, stale dates, or why nothing was found.")
