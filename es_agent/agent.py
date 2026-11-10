"""The agent: three tools over EnergyScope data, a typed answer, and a
validator that sends the model back when a number cannot be traced to a
tool result.

The model is chosen at run time (agent.run_sync(..., model=...)), so the
same agent runs against Anthropic, OpenAI, or the offline scripted model.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from pydantic_ai import Agent, ModelRetry, RunContext

from . import metrics
from .models import Change, DeskAnswer, Observation, SeriesHit
from .sources import DataSource


@dataclass
class Deps:
    source: DataSource
    # Every number a tool handed to the model, keyed by (series_id, lookback_days or None).
    ledger: dict[tuple[str, int | None], Observation | Change] = field(default_factory=dict)
    enforce: bool = True  # False = validator off, to prove the evals catch what it would have caught


INSTRUCTIONS = """\
You answer energy-market questions for a desk analyst using EnergyScope data.
- Find series with search_series; prefer daily (D) or weekly (W) series unless asked otherwise.
- Get numbers only from get_latest or get_change. Never compute or estimate numbers yourself.
- Copy tool values into facts unchanged. In the summary, quote numbers as they appear in facts.
- If no suitable series exists, return empty facts and say why in caveats. Do not guess.
"""

agent = Agent(
    deps_type=Deps,
    output_type=DeskAnswer,
    instructions=INSTRUCTIONS,
    retries=2,
    name="energyscope-desk",
)


@agent.tool
def search_series(ctx: RunContext[Deps], query: str, limit: int = 8) -> list[SeriesHit]:
    """Search EnergyScope series by keywords in the series name, e.g. 'WTI spot price' or 'Cushing ending stocks'."""
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


@agent.output_validator
def grounded(ctx: RunContext[Deps], answer: DeskAnswer) -> DeskAnswer:
    """Reject any fact that differs from what a tool returned, and any summary number that traces to no fact."""
    if not ctx.deps.enforce:
        return answer
    problems = []
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
    bad = metrics.untraceable_numbers(answer)
    if bad:
        problems.append(f"Summary numbers {bad} match no value in facts. Quote fact values, no conversions.")
    if not answer.facts and not answer.caveats:
        problems.append("No facts and no caveat: say why nothing was found.")
    if problems:
        raise ModelRetry("Fix these and answer again:\n- " + "\n- ".join(problems))
    return answer
