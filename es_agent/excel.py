"""Reproduce an answer's numbers in Excel, with the EnergyScope add-in.

For each fact, spread and reading in an answer, code writes a small sheet: a label, a formula and the value
The Librarian reported. Pasted at cell A1 of an empty sheet, the formulas fetch the inputs with `ES.Get` and
do the arithmetic in plain Excel, so a reader can check a number without trusting a model, this service or
this module's word.

Two rules keep it honest:

  - Inputs plus visible arithmetic. A formula either fetches one value of one series on one date
    (`=INDEX(ES.Get("PET.RWTC.D","2026-11-17","2026-11-17"),2,2)`: ES.Get returns a header row and the columns
    period | value, so row 2, column 2 is the value) or is ordinary arithmetic on the cells above it. Dates are
    fixed, so the sheet gives the same numbers next month.
  - A sheet is shown only if it reproduces. `evaluate` computes every formula from the same data source the
    answer was checked against, and `sheets` drops any sheet whose result differs from the reported value.
    The release gate requires that none is dropped on the golden questions.

What `evaluate` proves is the logic of the sheet: the right series, the right dates, the right arithmetic.
It does not run Excel. The form of the ES.Get call was taken from the add-in's source (Functions.cs, `Get`).
It compares values, so a formula that fetches the wrong date passes when the series had the same value on
both days (found by this module's own control: WTI on a US holiday).

Covered: latest values, changes, spreads, futures curves, crack spreads, seasonal comparisons. Not yet:
percentiles and positioning (they rank a whole window), scenarios, evidence and watch lists.
"""
from __future__ import annotations

import ast
import datetime as dt
import operator
import re

from pydantic import BaseModel

from es_agent import readings
from es_agent.models import DeskAnswer, Reading, SeriesFact, Spread
from es_agent.sources import DataSource

ADDIN_URL = "https://energyscope.io/excel"


class Row(BaseModel):
    label: str
    formula: str
    value: float


class Sheet(BaseModel):
    title: str
    rows: list[Row]


def _get(series_id: str, d: dt.date) -> str:
    return f'=INDEX(ES.Get("{series_id}","{d}","{d}"),2,2)'


def for_fact(f: SeriesFact) -> Sheet:
    rows = [Row(label=f"{f.name}, {f.latest_period} ({f.units})", formula=_get(f.series_id, f.latest_period),
                value=f.latest_value)]
    if f.base_period is not None and f.base_value is not None and f.change_abs is not None:
        rows.append(Row(label=f"The same series on {f.base_period}", formula=_get(f.series_id, f.base_period),
                        value=f.base_value))
        rows.append(Row(label="Change", formula="=B1-B2", value=f.change_abs))
        if f.change_pct is not None:
            rows.append(Row(label="Change, percent", formula="=(B1-B2)/B2*100", value=f.change_pct))
    return Sheet(title=f.name, rows=rows)


def for_spread(s: Spread) -> Sheet:
    return Sheet(title=f"{s.name_a} minus {s.name_b}", rows=[
        Row(label=f"{s.name_a}, {s.period}", formula=_get(s.series_a, s.period), value=s.value_a),
        Row(label=f"{s.name_b}, {s.period}", formula=_get(s.series_b, s.period), value=s.value_b),
        Row(label=f"Spread ({s.units})", formula="=B1-B2", value=s.spread),
    ])


def _curve(r: Reading) -> Sheet:
    n = len(r.series_ids)
    rows = [Row(label=f"M{i + 1}, {r.period}", formula=_get(sid, r.period), value=r.values[f"M{i + 1}"])
            for i, sid in enumerate(r.series_ids)]
    rows.append(Row(label="M1 minus M2", formula="=B1-B2", value=r.values["M1_minus_M2"]))
    rows.append(Row(label=f"M1 minus M{n}", formula=f"=B1-B{n}", value=r.values[f"M1_minus_M{n}"]))
    return Sheet(title=r.title, rows=rows)


_CRACK_FORMULA = {"3-2-1": "=(2*B2*42+B3*42)/3-B1", "gasoline": "=B2*42-B1", "distillate": "=B3*42-B1"}


def _crack(r: Reading) -> Sheet:
    kind = r.key.split(":", 1)[1]
    crude, gasoline, distillate = r.series_ids
    return Sheet(title=r.title, rows=[
        Row(label=f"WTI, dollars a barrel, {r.period}", formula=_get(crude, r.period), value=r.values["crude"]),
        Row(label="Gulf Coast gasoline, dollars a gallon", formula=_get(gasoline, r.period),
            value=r.values["gasoline_per_gallon"]),
        Row(label="New York Harbor heating oil, dollars a gallon", formula=_get(distillate, r.period),
            value=r.values["distillate_per_gallon"]),
        Row(label=f"{kind} crack, dollars a barrel (42 gallons to the barrel)", formula=_CRACK_FORMULA[kind],
            value=r.values["crack"]),
    ])


def _seasonal(r: Reading, source: DataSource) -> Sheet | None:
    series_id, years = r.series_ids[0], int(r.values["years"])
    points = readings.seasonal_points(source, series_id, years)
    if points is None or points[0] != r.period:
        return None
    _, latest, prior = points
    rows = [Row(label=f"Latest, {r.period} ({r.units})", formula=_get(series_id, r.period), value=latest)]
    rows += [Row(label=f"The same time of year, {d}", formula=_get(series_id, d), value=v) for d, v in prior]
    last = 1 + len(prior)
    rows.append(Row(label=f"Average of the previous {years} years", formula=f"=AVERAGE(B2:B{last})",
                    value=r.values["prior_average"]))
    rows.append(Row(label="Latest minus that average", formula=f"=B1-B{last + 1}", value=r.values["difference"]))
    rows.append(Row(label="Difference, percent", formula=f"=(B1-B{last + 1})/B{last + 1}*100",
                    value=r.values["difference_pct"]))
    return Sheet(title=r.title, rows=rows)


def for_reading(r: Reading, source: DataSource) -> Sheet | None:
    kind = r.key.split(":", 1)[0]
    if r.hypothetical:
        return None
    if kind == "curve":
        return _curve(r)
    if kind == "crack":
        return _crack(r)
    if kind == "seasonal":
        return _seasonal(r, source)
    return None


# ---- checking a sheet against the data, without Excel

_GET = re.compile(r'^=INDEX\(ES\.Get\("([^"]+)","(\d{4}-\d{2}-\d{2})","(\d{4}-\d{2}-\d{2})"\),2,2\)$')
_RANGE = re.compile(r"\b(AVERAGE|MIN|MAX)\(B(\d+):B(\d+)\)")
_REF = re.compile(r"\bB(\d+)\b")
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.USub: operator.neg, ast.UAdd: operator.pos}


def _arithmetic(node) -> float:
    """Numbers, + - * / and brackets. Nothing else is a formula this module writes."""
    if isinstance(node, ast.Expression):
        return _arithmetic(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_arithmetic(node.left), _arithmetic(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_arithmetic(node.operand))
    raise ValueError("not arithmetic")


def evaluate(sheet: Sheet, source: DataSource) -> list[float]:
    """What each formula gives, in order, as if the rows were pasted at A1 (so row i is cell B{i})."""
    out: list[float] = []
    for row in sheet.rows:
        fetch = _GET.match(row.formula)
        if fetch:
            series_id, start, end = fetch.groups()
            d = dt.date.fromisoformat(start)
            got = dict(source.history(series_id, start=d)).get(d) if start == end else None
            if got is None:
                raise ValueError(f"{series_id} has no value on {start}")
            out.append(float(got))
            continue

        def over(m):
            cells = out[int(m[2]) - 1:int(m[3])]
            return repr({"AVERAGE": sum(cells) / len(cells), "MIN": min(cells), "MAX": max(cells)}[m[1]])

        text = _RANGE.sub(over, row.formula.lstrip("="))
        text = _REF.sub(lambda m: f"({out[int(m[1]) - 1]!r})", text)
        out.append(_arithmetic(ast.parse(text, mode="eval")))
    return out


def problems(sheet: Sheet, source: DataSource) -> list[str]:
    """Rows whose formula does not give the value The Librarian reported."""
    try:
        got = evaluate(sheet, source)
    except Exception as e:
        return [f"{sheet.title}: {type(e).__name__}: {e}"]
    return [f"{sheet.title}: {row.label}: the formula gives {g:.6g}, the answer says {row.value:.6g}"
            for row, g in zip(sheet.rows, got)
            if abs(g - row.value) > max(5e-5, 1e-6 * abs(row.value))]


def sheets(answer: DeskAnswer, source: DataSource) -> tuple[list[Sheet], list[str]]:
    """The sheets for an answer that reproduce its numbers, and what was wrong with any that did not."""
    built = [for_fact(f) for f in answer.facts] + [for_spread(s) for s in answer.spreads]
    built += [s for s in (for_reading(r, source) for r in answer.readings) if s is not None]
    good, wrong = [], []
    for sheet in built:
        found = problems(sheet, source)
        if found:
            wrong.extend(found)
        else:
            good.append(sheet)
    return good, wrong


def tsv(sheet: Sheet) -> str:
    """The sheet as text to paste at A1: label, formula, reported value."""
    return "\n".join(f"{r.label}\t{r.formula}\t{r.value!r}" for r in sheet.rows)
