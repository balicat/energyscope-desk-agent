"""Typed shapes: what the tools return and what the agent must answer with."""

from __future__ import annotations

import datetime as dt

from typing import Literal

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
    also: dict[str, float] = Field(default_factory=dict, description="Written by code: the same value in the unit people ask for, e.g. million_barrels. Quote it with that unit.")


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
    also: dict[str, float] = Field(default_factory=dict, description="Written by code: the latest value in the unit people ask for.")


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
    words: dict[str, str] = Field(default_factory=dict, description="Written by code: short phrases a summary may place as slots (a curve's shape, a verdict).")
    # How code writes each value into a sentence (see slots.py). Not part of the published answer: the check
    # rebuilds every reading from the data, and these with it.
    unit_of: dict[str, str] = Field(default_factory=dict, exclude=True)    # the unit of a value when they differ; '*' = default
    label_of: dict[str, str] = Field(default_factory=dict, exclude=True)   # the noun a value is written with; 'A|B' for a gap
    window_of: dict[str, str] = Field(default_factory=dict, exclude=True)  # what a percentile ranks against, what a change spans
    date_of: dict[str, dt.date] = Field(default_factory=dict, exclude=True)  # the date of a value when it is not the reading's
    slot_values: bool = Field(True, exclude=True)                           # False: only its words and sentences are slots


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
    also: dict[str, float] = Field(default_factory=dict, description="Leave empty. Code copies it from the tool result.")


Limit = Literal["not_in_data", "out_of_scope", "no_secrets", "no_forecast", "no_causes", "no_freight", "no_physical",
                "no_consensus", "partial", "unconfirmed_figure", "us_only"]


class Draft(BaseModel):
    """What the model writes: a template, what it relied on, and which limits apply. Code builds the answer."""

    summary: str = Field(
        description=(
            "Two to four plain sentences for a desk analyst, written as a template. Every number, unit, date, direction of a "
            "change and curve shape is a slot: an address in braces copied exactly from a tool result, e.g. "
            "{curve:brent.M1_minus_M12}. The page replaces each slot with the text shown beside it in the tool result, and "
            "that text already names its subject: write a lead-in and a colon or 'with' before a slot, not the subject again. "
            "Outside the braces type no digit (not in a name either: no M1, no 3-2-1, no delivery month), no spelled-out "
            "number (not 'two' or 'five-year': say 'both', or leave it out), no month, weekday or 'today', and none of rose, "
            "fell, higher, lower, backwardation, contango, tight, loose: the slots say those."
        )
    )
    cites: list[str] = Field(
        default_factory=list,
        description="The `source` of any tool result you relied on without placing one of its slots. Usually empty.",
    )
    limits: list[Limit] = Field(
        default_factory=list,
        description=(
            "What the reader must be told, chosen from the list; code writes the sentence. not_in_data: the data does not hold "
            "what was asked. out_of_scope: not about energy markets. no_secrets: asked for instructions or credentials. "
            "no_forecast: asked what will happen. no_causes: asked why. no_freight / no_physical: the answer would need route "
            "freight rates / physical differentials. no_consensus: asked about surprises against expectations. partial: only "
            "part was answered. unconfirmed_figure: the question quoted a figure the data does not show. us_only: asked about "
            "the world, answered from US data."
        ),
    )


class Part(BaseModel):
    """One stretch of the summary: the model's own words, or a slot that code filled."""

    text: str
    slot: str | None = Field(None, description="The address, when code wrote this text.")
    source: str | None = None
    series: list[str] = Field(default_factory=list)
    date: dt.date | None = None


class DeskAnswer(BaseModel):
    """The answer as shown. Built by code from the model's draft and the tool results of the run."""

    facts: list[SeriesFact] = Field(default_factory=list, description="One entry per series the summary draws on, copied from the tool results.")
    spreads: list[Spread] = Field(default_factory=list, description="Each spread the summary draws on, copied from the tool result.")
    cites: list[str] = Field(default_factory=list, description="Keys of the readings the summary draws on.")
    readings: list[Reading] = Field(default_factory=list, description="The readings themselves, copied from the tool results.")
    summary: str = Field(description="The summary as rendered: the model's words with every slot filled by code.")
    template: str = Field("", description="The summary as the model wrote it, slots unfilled.")
    parts: list[Part] = Field(default_factory=list, description="The summary in pieces, so a page can mark which words code wrote.")
    limits: list[str] = Field(default_factory=list, description="The limits the model chose; their sentences are in caveats.")
    caveats: list[str] = Field(default_factory=list, description="Every caveat, each worded by code.")
