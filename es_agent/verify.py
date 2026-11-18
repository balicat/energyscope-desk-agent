"""Recompute an answer from the data source, independently of the run that produced it.

Used twice: by the evaluators on the test questions, and by `serve.py` on every live answer, so the
same check that scores the suite also watches real traffic.

Three things are rebuilt and compared:
- the tables: every fact, spread and reading, from the data;
- the summary: the slot table is built again from those recomputed values, the stored template is
  rendered again, and the result must equal the summary that is shown, character for character;
- the caveats: they must be exactly the ones code writes for this answer.
Problems about the summary start "summary:", about the caveats "caveats:"; the rest are the tables'.

The comparison is against the data at the moment of the check. A row that lands between the answer
and the check makes it fail, and the tick is withheld: that is the safe side.
"""

from __future__ import annotations

import datetime as dt

from . import clock, metrics, readings, slots
from .agent import code_caveats
from .models import DeskAnswer, SeriesFact
from .sources import DataSource


def verify(answer: DeskAnswer, source: DataSource) -> list[str]:
    """Problems found; an empty list means the answer equals a fresh computation."""
    problems = []
    facts, spreads, found = [], [], []
    for f in answer.facts:
        hit = source.meta(f.series_id)
        if hit is None:
            problems.append(f"{f.series_id} does not exist")
            continue
        lb = f.lookback_days or 0
        hist = source.history(f.series_id, start=clock.today() - dt.timedelta(days=lb + 400))
        truth = metrics.change_over(hit, hist, lb) if lb else metrics.latest_obs(hit, hist)
        if truth is None:
            problems.append(f"{f.series_id}: source has no value to compare")
            continue
        tv = truth.latest_value if lb else truth.value
        tp = truth.latest_period if lb else truth.period
        if f.latest_period != tp or not metrics.close(f.latest_value, tv):
            problems.append(f"{f.series_id}: source says {tp}={tv}, answer says {f.latest_period}={f.latest_value}")
        elif lb and not (metrics.close(f.change_pct, truth.change_pct) and metrics.close(f.base_value, truth.base_value)):
            problems.append(f"{f.series_id}: change differs from source")
        facts.append(SeriesFact(**truth.model_dump()) if lb else SeriesFact(
            series_id=truth.series_id, name=truth.name, units=truth.units, latest_period=truth.period,
            latest_value=truth.value, also=truth.also))
    start = clock.today() - dt.timedelta(days=400)
    for s in answer.spreads:
        a, b = source.meta(s.series_a), source.meta(s.series_b)
        truth = a and b and metrics.spread_of(a, source.history(s.series_a, start=start), b, source.history(s.series_b, start=start))
        if not truth or s.period != truth.period or not metrics.close(s.spread, truth.spread):
            problems.append(f"spread {s.series_a} minus {s.series_b} differs from source")
            continue
        if not readings.pairing_note(s.series_a, s.series_b)[1] or readings.frequency_note(source, s.series_a, s.series_b):
            problems.append(f"spread {s.series_a} minus {s.series_b} subtracts two prices of different kinds")
            continue
        extras, context, note = readings.spread_context(source, s.series_a, s.series_b, s.period)
        if s.context != context or s.note != note or set(s.extras) != set(extras) or not all(
            metrics.close(extras[k], s.extras[k]) for k in extras
        ):
            problems.append(f"spread {s.series_a} minus {s.series_b}: history differs from source")
        spreads.append(truth.model_copy(update={"extras": extras, "context": context, "note": note}))
    for r in answer.readings:
        truth = readings.compute(source, r.key)
        if truth is None or truth.period != r.period or truth.context != r.context or truth.counter != r.counter or truth.words != r.words or set(truth.values) != set(r.values) or not all(
            metrics.close(truth.values[k], r.values[k]) for k in r.values
        ):
            problems.append(f"reading {r.key} differs from source")
        if truth is not None:
            found.append(truth)
    # The summary, rebuilt: recomputed values -> slot table -> the stored template rendered again.
    table = slots.table(facts, spreads, found)
    problems += [f"summary: {cause}: {text}" for cause, text in slots.template_problems(answer.template, table)]
    if slots.render(answer.template, table)[0] != answer.summary:
        problems.append("summary: differs from its template rendered again from the data")
    rebuilt = answer.model_copy(update={"facts": facts, "spreads": spreads, "readings": found})
    if answer.caveats != code_caveats(source, rebuilt):
        problems.append("caveats: not the ones code writes for this answer")
    return problems
