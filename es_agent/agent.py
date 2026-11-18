"""The agent: eight tools over EnergyScope data, a typed answer, and a
validator that sends the model back when a number cannot be traced to a
tool result.

The model is chosen at run time (agent.run_sync(..., model=...)), so the
same agent runs against Anthropic, OpenAI, or the offline scripted model.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Literal

from pydantic_ai import Agent, ModelRetry, RunContext

from . import metrics, readings
from .models import Change, DeskAnswer, Observation, Reading, SeriesHit, Spread
from .sources import DataSource


@dataclass
class Deps:
    source: DataSource
    # Every number a tool handed to the model, keyed by (series_id, lookback_days or None).
    ledger: dict[tuple[str, int | None], Observation | Change] = field(default_factory=dict)
    spreads: dict[tuple[str, str], Spread] = field(default_factory=dict)  # every spread a tool returned
    readings: dict[str, Reading] = field(default_factory=dict)  # every computed reading a tool returned, by key
    searches: int = 0  # search_series calls so far in this run
    enforce: bool = True  # False = validator off, to prove the evals catch what it would have caught


SEARCH_BUDGET = 4  # a model that cannot find a series tends to keep rephrasing; the tool stops it

INSTRUCTIONS = """\
You answer energy-market questions for a desk analyst using EnergyScope data.
- Find series with search_series; prefer daily (D) or weekly (W) series unless asked otherwise.
- Get numbers only from get_latest or get_change. Never compute or estimate numbers yourself.
- For the difference between two series (a spread) call get_spread and copy its result into spreads. Never subtract yourself.
- Curve shape (backwardation, contango): get_curve. Refining margins: get_crack_spread. A level against its
  usual level for the time of year: get_seasonal. Fund or speculative positioning: get_positioning.
  These return a reading with a key: list the keys you used in cites and quote the reading's values in the summary.
- Copy tool values into facts unchanged. In the summary, quote numbers as they appear in facts.
- Report what the data shows. Do not predict, and do not explain causes the data cannot show; when a question needs
  data you lack (freight, physical differentials, news), say which in caveats.
- If two searches find no suitable series, stop searching: return empty facts and say why in caveats. Do not guess.
"""

agent = Agent(
    deps_type=Deps,
    output_type=DeskAnswer,
    instructions=INSTRUCTIONS,
    retries=2,
    name="energyscope-desk",
)


@agent.tool
def search_series(ctx: RunContext[Deps], query: str, limit: int = 8) -> list[SeriesHit] | str:
    """Search EnergyScope series by keywords in the series name, e.g. 'WTI spot price' or 'Cushing ending stocks'.

    Names use the publisher's wording (EIA): inventories are 'ending stocks', and commercial crude stocks are
    'ending stocks excluding SPR'. Use few, plain keywords; one or two searches should be enough.
    """
    ctx.deps.searches += 1
    if ctx.deps.searches > SEARCH_BUDGET:
        return (f"Search budget of {SEARCH_BUDGET} used; this search was not run. Answer from what you have, "
                "or return no facts and say in caveats that the data does not hold it.")
    return ctx.deps.source.search(query, limit)


@agent.tool
def get_latest(ctx: RunContext[Deps], series_ids: list[str]) -> list[Observation]:
    """Latest observation (date and value) for one or more series IDs."""
    out = []
    for sid in series_ids:
        hit = ctx.deps.source.meta(sid)
        if hit is None:
            raise ModelRetry(f"Unknown series_id {sid!r}. Use search_series to find a valid ID.")
        obs = metrics.latest_obs(hit, ctx.deps.source.history(sid))
        if obs:
            ctx.deps.ledger[(sid, None)] = obs
            out.append(obs)
    return out


@agent.tool
def get_change(ctx: RunContext[Deps], series_id: str, lookback_days: int) -> Change:
    """Latest value against the value `lookback_days` earlier (e.g. 7 = week, 28 = four weeks, 365 = year)."""
    hit = ctx.deps.source.meta(series_id)
    if hit is None:
        raise ModelRetry(f"Unknown series_id {series_id!r}. Use search_series to find a valid ID.")
    hist = ctx.deps.source.history(series_id, start=dt.date.today() - dt.timedelta(days=lookback_days + 400))
    ch = metrics.change_over(hit, hist, lookback_days)
    if ch is None:
        raise ModelRetry(f"Not enough history in {series_id} for a {lookback_days}-day change.")
    ctx.deps.ledger[(series_id, lookback_days)] = ch
    return ch


@agent.tool
def get_spread(ctx: RunContext[Deps], series_a: str, series_b: str) -> Spread:
    """series_a minus series_b on the latest date both have a value, e.g. Brent minus WTI. Both must share units."""
    hits = []
    for sid in (series_a, series_b):
        hit = ctx.deps.source.meta(sid)
        if hit is None:
            raise ModelRetry(f"Unknown series_id {sid!r}. Use search_series to find a valid ID.")
        hits.append(hit)
    a, b = hits
    if a.units != b.units:
        raise ModelRetry(f"Units differ ({a.units!r} vs {b.units!r}): no spread. Report the two values separately.")
    start = dt.date.today() - dt.timedelta(days=400)
    sp = metrics.spread_of(a, ctx.deps.source.history(series_a, start=start), b, ctx.deps.source.history(series_b, start=start))
    if sp is None:
        raise ModelRetry(f"{series_a} and {series_b} share no date in the last 400 days.")
    ctx.deps.spreads[(series_a, series_b)] = sp
    return sp


def _keep(ctx: RunContext[Deps], reading: Reading | None, why: str) -> Reading:
    if reading is None:
        raise ModelRetry(why)
    ctx.deps.readings[reading.key] = reading
    return reading


@agent.tool
def get_curve(ctx: RunContext[Deps], market: Literal["brent"]) -> Reading:
    """Futures curve on the latest date: each contract month (M1 = front), M1 minus M2, M1 minus the last month,
    and whether the curve is in backwardation or contango. Brent only (12 months); there is no WTI curve in the data."""
    return _keep(ctx, readings.curve(ctx.deps.source, market), f"No complete {market} curve in the last 60 days.")


@agent.tool
def get_crack_spread(ctx: RunContext[Deps], kind: Literal["3-2-1", "gasoline", "distillate"]) -> Reading:
    """Refining margin in dollars per barrel from spot prices: products (Gulf Coast gasoline, New York Harbor
    heating oil, converted from gallons) minus WTI crude."""
    return _keep(ctx, readings.crack(ctx.deps.source, kind), "The three spot prices share no date in the last 60 days.")


@agent.tool
def get_seasonal(ctx: RunContext[Deps], series_id: str, years: int = 5) -> Reading:
    """Latest value of a series against the average, low and high at the same time of year in the previous
    `years` years (2 to 10). Use for 'versus the five-year average' or 'is this high for the season'."""
    if ctx.deps.source.meta(series_id) is None:
        raise ModelRetry(f"Unknown series_id {series_id!r}. Use search_series to find a valid ID.")
    return _keep(ctx, readings.seasonal(ctx.deps.source, series_id, years),
                 f"{series_id} lacks {years} earlier years of history (or years is outside 2 to 10).")


@agent.tool
def get_positioning(ctx: RunContext[Deps], market: Literal["wti", "brent", "gasoil", "natural_gas", "gasoline"]) -> Reading:
    """Managed-money (fund) futures positioning from the weekly commitments of traders report: net, long, short,
    change on the week, open interest, and where the net position ranks against the last three years."""
    return _keep(ctx, readings.positioning(ctx.deps.source, market), f"No positioning data for {market}.")


@agent.output_validator
def grounded(ctx: RunContext[Deps], answer: DeskAnswer) -> DeskAnswer:
    """Reject any fact that differs from what a tool returned, and any summary number that traces to no fact."""
    problems = []
    # The model cites reading keys; code copies the readings in, so their numbers cannot be mistyped.
    answer.readings = []
    for key in dict.fromkeys(answer.cites):
        if key in ctx.deps.readings:
            answer.readings.append(ctx.deps.readings[key])
        else:
            problems.append(f"cites {key!r}, which no tool returned in this run. Keys available: {sorted(ctx.deps.readings)}.")
    answer.cites = [r.key for r in answer.readings]
    if not ctx.deps.enforce:
        return answer
    for f in answer.facts:
        src = ctx.deps.ledger.get((f.series_id, f.lookback_days))
        if src is None:
            problems.append(f"{f.series_id} (lookback {f.lookback_days}) was not returned by any tool call in this run.")
            continue
        latest_p = src.period if isinstance(src, Observation) else src.latest_period
        latest_v = src.value if isinstance(src, Observation) else src.latest_value
        if f.latest_period != latest_p or not metrics.close(f.latest_value, latest_v):
            problems.append(f"{f.series_id}: latest is {latest_p} = {latest_v}, you wrote {f.latest_period} = {f.latest_value}.")
        if isinstance(src, Change):
            for name in ("base_value", "change_abs", "change_pct"):
                if not metrics.close(getattr(f, name), getattr(src, name)):
                    problems.append(f"{f.series_id}: {name} is {getattr(src, name)}, you wrote {getattr(f, name)}.")
    for s in answer.spreads:
        src = ctx.deps.spreads.get((s.series_a, s.series_b))
        if src is None:
            problems.append(f"Spread {s.series_a} minus {s.series_b} was not returned by get_spread in this run.")
        elif s.period != src.period or not all(metrics.close(getattr(s, n), getattr(src, n)) for n in ("value_a", "value_b", "spread")):
            problems.append(f"Spread {s.series_a} minus {s.series_b}: tool returned {src.period} {src.value_a} - {src.value_b} = {src.spread}; copy it unchanged.")
    bad = metrics.untraceable_numbers(answer)
    if bad:
        problems.append(f"Summary numbers {bad} match no value in facts, spreads or cited readings. Quote those values, no conversions, and cite every reading you quote.")
    if not answer.facts and not answer.spreads and not answer.readings and not answer.caveats:
        problems.append("No facts and no caveat: say why nothing was found.")
    if problems:
        raise ModelRetry("Fix these and answer again:\n- " + "\n- ".join(problems))
    return answer
