"""Reproduce an answer's numbers in Excel, with the EnergyScope add-in.

For each fact, spread and reading in an answer, code writes a small sheet: a label, a formula and the value
The Librarian reported. In Excel the formulas fetch the inputs with `ES.Value` and do the arithmetic in plain
Excel, so a reader can check a number without trusting a model, this service or this module's word. The
sheets reach the reader two ways: as text to paste at cell A1, and as a workbook to download (`workbook`),
which is the one that works in every Excel: pasted text is read by the reader's locale, and where the list
separator is a semicolon and the decimal mark a comma (Spain, Germany) a pasted formula is refused and
"2.538" is read as 2538. A file stores formulas and numbers the same way everywhere.

Two rules keep it honest:

  - Inputs plus visible arithmetic. A formula either fetches one value of one series on one date
    (`=ES.Value("PET.RWTC.D","2026-11-17")`: one number, or the text "no value on 2026-11-17", never a
    neighbouring day; it needs add-in 3.2.0, released 19 Nov 2026) or is ordinary arithmetic on the cells
    above it. Dates are fixed, so the sheet gives the same numbers next month, unless the source revises a
    value: the last day or two of a futures series is revised after the fact, which is why a sheet carries
    the time its answer was given.
  - A sheet is shown only if it reproduces. `evaluate` computes every formula from the same data source the
    answer was checked against, and `sheets` drops any sheet whose result differs from the reported value.
    The release gate requires that none is dropped on the golden questions.

What `evaluate` proves is the logic of the sheet: the right series, the right dates, the right arithmetic.
It does not run Excel. That was done on 19 Nov 2026 with add-in 3.2.0 in Excel 16, on a few sheets, not on
all of them: five sheets entered one after another by a second reviewer (24 cells) and a workbook of four tabs
written by `workbook` (30 cells) gave the reported value in every cell.
It compares values, so a formula that fetches the wrong date passes when the series had the same value on
both days (found by this module's own control: WTI on a US holiday).

Covered: latest values, changes, spreads, futures curves, crack spreads, seasonal comparisons. Not yet:
percentiles and positioning (they rank a whole window), scenarios, evidence and watch lists.
"""
from __future__ import annotations

import ast
import datetime as dt
import io
import operator
import re
import textwrap
import zipfile
from xml.sax.saxutils import escape

from pydantic import BaseModel

from es_agent import readings
from es_agent.models import DeskAnswer, Reading, SeriesFact, Spread
from es_agent.sources import DataSource

ADDIN_URL = "https://energyscope.io/excel"
ADDIN_VERSION = "3.2.0"   # the first with ES.Value
TOLERANCE_ABS, TOLERANCE_REL = 5e-5, 1e-6   # a formula reproduces a reported value within the larger of these


class Row(BaseModel):
    label: str
    formula: str
    value: float


class Sheet(BaseModel):
    title: str
    rows: list[Row]


def _get(series_id: str, d: dt.date) -> str:
    return f'=ES.Value("{series_id}","{d}")'


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

_GET = re.compile(r'^=ES\.Value\("([^"]+)","(\d{4}-\d{2}-\d{2})"\)$')
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
            series_id, day = fetch.groups()
            d = dt.date.fromisoformat(day)
            got = dict(source.history(series_id, start=d)).get(d)
            if got is None:
                raise ValueError(f"{series_id} has no value on {day}")
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
            if abs(g - row.value) > max(TOLERANCE_ABS, TOLERANCE_REL * abs(row.value))]


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


# ---- the same sheets as a workbook: formulas and numbers stored the way the file format stores them,
#      so the reader's locale cannot change them

def _tab_names(titles: list[str]) -> list[str]:
    """Excel allows 31 characters in a tab name, none of []:*?/\\, and no two alike."""
    names: list[str] = []
    for i, title in enumerate(titles, 1):
        name = re.sub(r"[\[\]:*?/\\]", " ", title).strip().strip("'")[:31].rstrip() or f"Sheet {i}"
        base, k = name, i
        while name.lower() in (n.lower() for n in names):
            # A number makes it distinct, and the cut leaves room for it whatever its length: a name of 27
            # characters plus " (10)" is 32, and Excel then refuses to open the file (found by the reviewer
            # with ten tabs; the first control had four). The number starts at the tab's position and moves on
            # if a title already ends that way ("A (3)", "A", "A").
            suffix = f" ({k})"
            name = base[:31 - len(suffix)].rstrip() + suffix
            k += 1
        names.append(name)
    return names


# The workbook is a second rendering of the same sheets, laid out for a person to use (David, 19 Nov 2026: "put
# the date in a cell and refer to it and put the series ids in a neighbouring cell"):
#
#     row 1   A "Date" label                     C the tab's date        <- the one cell to change
#     row 3   A What | B Series | C Date | D Value | E Reported | F Check        the header, frozen
#     row 4.. one row for each row of the sheet
#
# A row that fetches holds its series ID in B and its date in C, and D is =ES.Value(B,C). The date the most rows of
# the tab share (all three legs of a crack, every month of a curve, the latest value of a comparison) is written
# ONCE, in C1, and each of those rows has =$C$1 in its Date cell: change C1 and THOSE rows move, with everything
# calculated from them. A row with another date (the value thirty days earlier, the same week of a prior year)
# keeps a date of its own and does not move; the label in A1 says how many rows follow. Values show with thousands separators and two decimals; the cells keep every digit.
# The sheet's own formulas (Row.formula, the form the page shows and `evaluate` checks) are written as if pasted
# at A1 with the formula in column B, so they are moved FIRST_ROW - 1 rows down and into column D here, and
# `read_back` moves them back to prove nothing was lost.

HEADER = ("What", "Series", "Date", "Value", "Reported", "Check")


def date_label(follow: int, fetching: int) -> str:
    """The words beside C1. They COUNT: the reviewer read the first wording ("the whole sheet moves") against
    77 sheets and the whole tab followed on 7; on a seasonal tab one row of six did, and the average beside it
    then compared a week with other weeks of the year with nothing on the tab to say so."""
    if fetching == 1:
        return "Date: change this cell and the one fetched row follows"
    if follow == fetching:
        return f"Date: change this cell and all {fetching} fetched rows follow"
    others = "one keeps its own date" if fetching - follow == 1 else f"{fetching - follow} keep their own dates"
    return (f"Date: change this cell and {follow} of {fetching} fetched rows follow{'s' if follow == 1 else ''}; "
            f"the other {others}")


HEADER_ROW, FIRST_ROW = 3, 4
# Right of the rows, the HISTORY of the tab's series over the year that ends on the date in C1:
#
#     H1        a label
#     H4..P     a line chart for each of the first three series, one under the other (never two series on one
#               chart: a crack tab has dollars a barrel beside dollars a gallon, and they would share an axis)
#     R3, S3..  "Date" and one cell per series, each a reference to the Series cell of the first row naming it
#     R4        ONE formula, =ES.Table(S3:.., C1-365, C1, "#N/A", "D"), which fills the cells below and beside it
#
# Change C1, or a Series cell, and table and charts follow. Three things learnt in Excel 16 with add-in 3.2.1
# (19 Nov 2026): a formula that fills other cells must be stored the way Excel stores its own dynamic arrays (a
# marker on the cell and a part named metadata.xml), or Excel reads it as =@ES.Table(...) and shows one cell;
# the fill must be "#N/A", because the default leaves "" before a series' first value and a chart draws text as
# zero; and the table has a row for every day (366 rows, 4 to 369), which is also the fixed range the charts read:
# a weekly or monthly series has its values on their own days and #N/A between, and the line spans the gaps.
HISTORY_DAYS = 365
HISTORY_COLUMN = 18                                  # R
HISTORY_LAST_ROW = FIRST_ROW + HISTORY_DAYS          # C1-365 to C1 is 366 days
CHARTS_MOST = 3
CHART_COLUMNS, CHART_ROWS = (7, 16), 16              # H to P (counted from 0), sixteen rows each, a row between
HISTORY_LABEL = ("History: the year to the date in C1. A chart for each of the first three series; "
                 "the table behind them starts in column R")
HISTORY_NOTE = ("To the right: the history of this sheet's series over the year to the date in C1, as charts (the "
                "first three series) and as a table from column R, filled by the one formula in R4. Both follow "
                "C1 and the Series cells. The table has a row for every day; a day with no value shows #N/A in grey. Do not type inside it. "
                "This part needs Excel 365 or Excel 2021.")
_EPOCH = dt.date(1899, 12, 30)   # day 0 of Excel's calendar
_STYLE_NUMBER, _STYLE_DATE, _STYLE_HEAD = 1, 2, 3
# A note is written as LINES, one row each, with an empty row between notes. Left as one long cell it ran on to
# the right under the charts; as a merged, wrapped cell its tall row ran through the history table and stretched
# a chart (seen in a picture of the tab in Excel). A line of 130 characters ends well inside columns A to F,
# which are 148 characters wide.
NOTE_LINE = 130


def note_lines(note: str) -> list[str]:
    return textwrap.wrap(note, NOTE_LINE, break_long_words=False, break_on_hyphens=False)


def tab_date(sheet: Sheet) -> str | None:
    """The date the tab's top cell holds: the one most of its fetching rows use, the first of them on a tie.
    None for a sheet that fetches nothing."""
    days = [m[2] for m in (_GET.match(r.formula) for r in sheet.rows) if m]
    return max(days, key=lambda d: (days.count(d), -days.index(d))) if days else None


def tab_series(sheet: Sheet) -> list[str]:
    """The series a tab fetches, each once, in the order its rows name them."""
    out: list[str] = []
    for m in (_GET.match(r.formula) for r in sheet.rows):
        if m and m[1] not in out:
            out.append(m[1])
    return out


def _column(n: int) -> str:
    """1 -> A, 27 -> AA."""
    s = ""
    while n:
        n, k = divmod(n - 1, 26)
        s = chr(65 + k) + s
    return s


def history_formula(count: int) -> str:
    """The one formula of the history table, as the file stores it, for a tab with `count` series."""
    first, last = _column(HISTORY_COLUMN + 1), _column(HISTORY_COLUMN + count)
    # The frequency is "D", a row for every day. Left to itself ES.Table puts a weekly series on a regular
    # weekly grid counted from its first date, and a report dated on another weekday (a holiday week) falls
    # off it: 155 of 156 weekly positioning reports, seen in Excel. On a daily grid nothing can fall off.
    return f'_xll.ES.Table({first}{HEADER_ROW}:{last}{HEADER_ROW},$C$1-{HISTORY_DAYS},$C$1,"#N/A","D")'


def _moved(formula: str) -> str:
    """An arithmetic formula as the workbook holds it: B{n} of the pasted form is D{n + FIRST_ROW - 1} here."""
    return _REF.sub(lambda m: f"D{int(m[1]) + FIRST_ROW - 1}", formula.lstrip("="))


def _same(r: int) -> str:
    """The Check column: "same" when Value equals Reported by the tolerance `problems` uses, otherwise Value
    minus Reported. A plain difference showed -2.3E-07 on a percent the answer reports to six decimals. The
    column keeps the General format: at two decimals a real difference of 0.003 would read 0.00."""
    return (f'IF(ISNUMBER(D{r}),IF(ABS(D{r}-E{r})<=MAX({TOLERANCE_ABS:.5f},{TOLERANCE_REL:.6f}*ABS(E{r})),'
            f'"same",D{r}-E{r}),"")')


def _text(ref: str, text: str, style: int = 0) -> str:
    s = f' s="{style}"' if style else ""
    return f'<c r="{ref}"{s} t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'


def _serial(day: str) -> int:
    return (dt.date.fromisoformat(day) - _EPOCH).days


def _worksheet(sheet: Sheet, notes: list[str]) -> str:
    shared = tab_date(sheet)
    days = [m[2] for m in (_GET.match(r.formula) for r in sheet.rows) if m]
    xml = []
    if shared is not None:
        xml.append(f'<row r="1">{_text("A1", date_label(days.count(shared), len(days)), _STYLE_HEAD)}'
                   f'<c r="C1" s="{_STYLE_DATE}"><v>{_serial(shared)}</v></c>'
                   f'{_text("H1", HISTORY_LABEL, _STYLE_HEAD)}</row>')
    # the history's header: each series cell REFERS to the Series cell of the first row that names it (the ID is
    # stored beside the reference, as the date is beside =$C$1, for Protected View)
    series = tab_series(sheet)
    named = {}
    for i, row in enumerate(sheet.rows):
        m = _GET.match(row.formula)
        if m:
            named.setdefault(m[1], FIRST_ROW + i)
    d = _column(HISTORY_COLUMN)
    head = (_text(f"{d}{HEADER_ROW}", "Date", _STYLE_HEAD)
            + "".join(f'<c r="{_column(HISTORY_COLUMN + 1 + k)}{HEADER_ROW}" s="{_STYLE_HEAD}" t="str">'
                      f'<f>B{named[sid]}</f><v>{escape(sid)}</v></c>' for k, sid in enumerate(series))) if series else ""
    xml.append(f'<row r="{HEADER_ROW}">'
               + "".join(_text(f"{col}{HEADER_ROW}", name, _STYLE_HEAD) for col, name in zip("ABCDEF", HEADER))
               + head + "</row>")
    for i, row in enumerate(sheet.rows):
        r = FIRST_ROW + i
        fetch = _GET.match(row.formula)
        if fetch:
            series_id, day = fetch.groups()
            # the date is stored beside the reference too: Protected View calculates nothing and showed blanks
            date = f"<f>$C$1</f><v>{_serial(day)}</v>" if day == shared else f"<v>{_serial(day)}</v>"
            inputs = (f'{_text(f"B{r}", series_id)}<c r="C{r}" s="{_STYLE_DATE}">{date}</c>'
                      f'<c r="D{r}" s="{_STYLE_NUMBER}"><f>_xll.ES.Value(B{r},C{r})</f></c>')
        else:
            inputs = f'<c r="D{r}" s="{_STYLE_NUMBER}"><f>{escape(_moved(row.formula))}</f></c>'
        # the history's one formula sits at the end of the first row; cm="1" and t="array" let it fill other cells
        table = (f'<c r="{d}{r}" s="{_STYLE_DATE}" cm="1"><f t="array" ref="{d}{r}">{history_formula(len(series))}</f></c>'
                 if i == 0 and series else "")
        xml.append(f'<row r="{r}">{_text(f"A{r}", row.label)}{inputs}'
                   f'<c r="E{r}" s="{_STYLE_NUMBER}"><v>{row.value!r}</v></c>'
                   f'<c r="F{r}"><f>{escape(_same(r))}</f></c>{table}</row>')
    j = FIRST_ROW + len(sheet.rows) + 1
    for note in notes:
        for line in note_lines(note):
            xml.append(f'<row r="{j}">{_text(f"A{j}", line)}</row>')
            j += 1
        j += 1          # an empty row between notes
    history = ""
    if series:
        first, last = _column(HISTORY_COLUMN + 1), _column(HISTORY_COLUMN + len(series))
        history = (f'<conditionalFormatting sqref="{first}{FIRST_ROW}:{last}{HISTORY_LAST_ROW}">'
                   f'<cfRule type="containsErrors" dxfId="0" priority="1"><formula>ISERROR({first}{FIRST_ROW})</formula>'
                   '</cfRule></conditionalFormatting><drawing r:id="rId1"/>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheetViews><sheetView workbookViewId="0"><pane ySplit="{HEADER_ROW}" topLeftCell="A{FIRST_ROW}" '
            'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            '<cols><col min="1" max="1" width="58" customWidth="1"/><col min="2" max="2" width="34" customWidth="1"/>'
            '<col min="3" max="3" width="12" customWidth="1"/><col min="4" max="5" width="16" customWidth="1"/>'
            '<col min="6" max="6" width="12" customWidth="1"/><col min="7" max="7" width="3" customWidth="1"/>'
            f'<col min="{HISTORY_COLUMN - 1}" max="{HISTORY_COLUMN - 1}" width="3" customWidth="1"/>'
            f'<col min="{HISTORY_COLUMN}" max="{HISTORY_COLUMN}" width="12" style="{_STYLE_DATE}" customWidth="1"/>'
            # a series column is as wide as its ID in bold: at a fixed 20 the longer IDs were cut in the header
            + "".join(f'<col min="{HISTORY_COLUMN + 1 + k}" max="{HISTORY_COLUMN + 1 + k}" width="{max(16, len(sid) + 6)}" '
                      f'style="{_STYLE_NUMBER}" customWidth="1"/>' for k, sid in enumerate(series))
            + '</cols>'
            f'<sheetData>{"".join(xml)}</sheetData>{history}</worksheet>')


_STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
           '<numFmts count="2"><numFmt numFmtId="164" formatCode="#,##0.00"/>'
           '<numFmt numFmtId="165" formatCode="yyyy-mm-dd"/></numFmts>'
           '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
           '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
           '<fills count="2"><fill><patternFill patternType="none"/></fill>'
           '<fill><patternFill patternType="gray125"/></fill></fills>'
           '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
           '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
           '<cellXfs count="4"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
           '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
           '<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
           '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
           '<dxfs count="1"><dxf><font><color rgb="FFB0B0B0"/></font></dxf></dxfs>'       # #N/A in the history, grey
           '</styleSheet>')

_MAIN = "http://schemas.openxmlformats.org/drawingml/2006/main"
_CHART = "http://schemas.openxmlformats.org/drawingml/2006/chart"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">')
# What Excel writes beside a workbook that holds a dynamic array. Its one cell-metadata record says "this formula
# may fill other cells"; the history's formula points at it with cm="1".
_METADATA = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<metadata xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
             'xmlns:xda="http://schemas.microsoft.com/office/spreadsheetml/2017/dynamicarray">'
             '<metadataTypes count="1"><metadataType name="XLDAPR" minSupportedVersion="120000" copy="1" pasteAll="1" '
             'pasteValues="1" merge="1" splitFirst="1" rowColShift="1" clearFormats="1" clearComments="1" assign="1" '
             'coerce="1" cellMeta="1"/></metadataTypes>'
             '<futureMetadata name="XLDAPR" count="1"><bk><extLst><ext uri="{bdbb8cdc-fa1e-496e-a857-3c3f30c029c3}">'
             '<xda:dynamicArrayProperties fDynamic="1" fCollapsed="0"/></ext></extLst></bk></futureMetadata>'
             '<cellMetadata count="1"><bk><rc t="1" v="0"/></bk></cellMetadata></metadata>')
_SMALL = '<c:txPr><a:bodyPr/><a:p><a:pPr><a:defRPr sz="900"/></a:pPr><a:endParaRPr lang="en-GB"/></a:p></c:txPr>'


def _chart(tab: str, k: int) -> str:
    """A line chart of the tab's k-th series (from 0) over the history table: one series, one value axis, its
    title the series' header cell, dates in months, days with no value spanned."""
    q = escape("'" + tab.replace("'", "''") + "'")
    d, col = _column(HISTORY_COLUMN), _column(HISTORY_COLUMN + 1 + k)
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<c:chartSpace xmlns:c="{_CHART}" xmlns:a="{_MAIN}" xmlns:r="{_REL}"><c:roundedCorners val="0"/><c:chart>'
            '<c:title><c:overlay val="0"/><c:txPr><a:bodyPr/><a:p><a:pPr><a:defRPr sz="1100" b="0"/></a:pPr>'
            '<a:endParaRPr lang="en-GB"/></a:p></c:txPr></c:title><c:autoTitleDeleted val="0"/><c:plotArea>'
            # the plot stops short of the right edge: at full width the last month's label was cut ("Nov 2")
            '<c:layout><c:manualLayout><c:layoutTarget val="inner"/><c:xMode val="edge"/><c:yMode val="edge"/>'
            '<c:x val="0.09"/><c:y val="0.15"/><c:w val="0.86"/><c:h val="0.7"/></c:manualLayout></c:layout>'
            '<c:lineChart><c:grouping val="standard"/><c:varyColors val="0"/><c:ser><c:idx val="0"/><c:order val="0"/>'
            f'<c:tx><c:strRef><c:f>{q}!${col}${HEADER_ROW}</c:f></c:strRef></c:tx>'
            '<c:spPr><a:ln w="19050" cap="rnd"><a:solidFill><a:srgbClr val="2F6DB5"/></a:solidFill><a:round/></a:ln></c:spPr>'
            '<c:marker><c:symbol val="none"/></c:marker>'
            f'<c:cat><c:numRef><c:f>{q}!${d}${FIRST_ROW}:${d}${HISTORY_LAST_ROW}</c:f></c:numRef></c:cat>'
            f'<c:val><c:numRef><c:f>{q}!${col}${FIRST_ROW}:${col}${HISTORY_LAST_ROW}</c:f></c:numRef></c:val>'
            '<c:smooth val="0"/></c:ser><c:marker val="1"/><c:axId val="1"/><c:axId val="2"/></c:lineChart>'
            '<c:dateAx><c:axId val="1"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/>'
            '<c:axPos val="b"/><c:numFmt formatCode="mmm yy" sourceLinked="0"/><c:majorTickMark val="none"/>'
            f'<c:minorTickMark val="none"/><c:tickLblPos val="low"/>{_SMALL}<c:crossAx val="2"/><c:crosses val="autoZero"/>'
            '<c:auto val="1"/><c:lblOffset val="100"/><c:baseTimeUnit val="days"/><c:majorUnit val="1"/>'
            '<c:majorTimeUnit val="months"/></c:dateAx>'
            '<c:valAx><c:axId val="2"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/>'
            '<c:axPos val="l"/><c:majorGridlines><c:spPr><a:ln w="6350"><a:solidFill><a:srgbClr val="E3E3E3"/></a:solidFill>'
            '</a:ln></c:spPr></c:majorGridlines><c:numFmt formatCode="#,##0.00" sourceLinked="0"/>'
            '<c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/>'
            f'<c:spPr><a:ln><a:noFill/></a:ln></c:spPr>{_SMALL}<c:crossAx val="1"/><c:crosses val="autoZero"/>'
            '<c:crossBetween val="between"/></c:valAx></c:plotArea><c:plotVisOnly val="1"/><c:dispBlanksAs val="span"/>'
            '</c:chart></c:chartSpace>')


def _drawing(count: int) -> str:
    """Where a tab's charts sit: columns H to P, from row 4 (below the frozen rows), one under the other."""
    anchors = []
    for k in range(count):
        top = FIRST_ROW - 1 + k * (CHART_ROWS + 1)
        anchors.append(
            '<xdr:twoCellAnchor>'
            f'<xdr:from><xdr:col>{CHART_COLUMNS[0]}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{top}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>'
            f'<xdr:to><xdr:col>{CHART_COLUMNS[1]}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{top + CHART_ROWS}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>'
            f'<xdr:graphicFrame macro=""><xdr:nvGraphicFramePr><xdr:cNvPr id="{k + 2}" name="History {k + 1}"/>'
            '<xdr:cNvGraphicFramePr/></xdr:nvGraphicFramePr><xdr:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></xdr:xfrm>'
            f'<a:graphic><a:graphicData uri="{_CHART}"><c:chart xmlns:c="{_CHART}" xmlns:r="{_REL}" r:id="rId{k + 1}"/>'
            '</a:graphicData></a:graphic></xdr:graphicFrame><xdr:clientData/></xdr:twoCellAnchor>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
            f'xmlns:a="{_MAIN}">' + "".join(anchors) + '</xdr:wsDr>')


C1_NOTE = ("The Date in cell C1 belongs to the rows whose Date cell shows the same date: change C1 and those rows "
           "follow, with everything calculated from them. A row with another date keeps its own cell and does not "
           "move, so where a tab compares dates (a change over thirty days, the same week of earlier years) moving "
           "C1 alone changes what is compared. C1 must hold a date: emptied, the rows that follow it find no value.")


def notes(given_at: str) -> list[str]:
    """What a reader needs under the rows of every tab. `given_at` is when the answer was given, as text."""
    return [
        "If Excel shows a yellow bar saying Protected View, click Enable Editing first: until then nothing here calculates.",
        "Then press Refresh All on the EnergyScope tab. Before that the Value cells that fetch are empty, and the "
        "ones that calculate from them read #VALUE! or #DIV/0!.",
        # Second, not last: the reviewer opened all 77 sheets a day after the data was frozen and 86 of 367
        # cells differed, every one from a futures close revised at the source (Brent 17 Nov, NYMEX 18 Nov).
        f"The answer was given on {given_at}. If Check shows a number on the latest day or two of a futures "
        "series, the source has revised that price since; it is not an error in the sheet.",
        "Value is fetched from the Series and Date beside it, or calculated from the Value cells above. Reported is "
        "what The Librarian said. Check says \"same\" when they agree to within 0.00005 or one part in a million, "
        "which is the check the service applies; otherwise it is Value minus Reported.",
        C1_NOTE,
        HISTORY_NOTE,
        "Change a Date or a Series ID and Value follows; Reported stays what the answer said, so Check will then "
        "show the difference. Values are shown to two decimals; the cells hold every digit.",
        # The reviewer, editing as a reader would: "WTI ..., 2026-11-11" stayed beside a Date of 2026-10-12, and an
        # emptied Date gave the latest value with nothing to say which day (on a forecast series, the furthest one).
        "The text in What was written for the original series and date and does not change when you edit them. "
        "Write dates as 2026-11-17 or pick them as dates. A row's own Date left empty gives the last value of the "
        "series, which on a series that includes forecasts is the furthest forecast.",
        f"Value needs the EnergyScope add-in, version {ADDIN_VERSION} or later, and a key: {ADDIN_URL}. If it reads "
        "#NAME?, the add-in is not loaded; with no key, it says so in words.",
    ]


def workbook(good: list[Sheet], given_at: str) -> bytes:
    """One .xlsx, a tab for each sheet. Written by hand so the service needs no spreadsheet library: an .xlsx
    is a zip of small XML files."""
    names = _tab_names([s.title for s in good])
    below = notes(given_at)
    n = range(1, len(good) + 1)
    styles_id = len(good) + 1
    # a tab that fetches has a history table and up to three charts over it
    drawn, overrides, charts = {}, [], 0
    for i, name, sheet in zip(n, names, good):
        count = min(CHARTS_MOST, len(tab_series(sheet)))
        if not count:
            continue
        rels = []
        for k in range(count):
            charts += 1
            drawn[f"xl/charts/chart{charts}.xml"] = _chart(name, k)
            rels.append(f'<Relationship Id="rId{k + 1}" Type="{_REL}/chart" Target="../charts/chart{charts}.xml"/>')
            overrides.append(f'<Override PartName="/xl/charts/chart{charts}.xml" '
                             'ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/>')
        drawn[f"xl/drawings/drawing{i}.xml"] = _drawing(count)
        drawn[f"xl/drawings/_rels/drawing{i}.xml.rels"] = _RELS + "".join(rels) + "</Relationships>"
        drawn[f"xl/worksheets/_rels/sheet{i}.xml.rels"] = (
            _RELS + f'<Relationship Id="rId1" Type="{_REL}/drawing" Target="../drawings/drawing{i}.xml"/></Relationships>')
        overrides.append(f'<Override PartName="/xl/drawings/drawing{i}.xml" '
                         'ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>')
    files = {
        "[Content_Types].xml":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in n)
            + '<Override PartName="/xl/metadata.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheetMetadata+xml"/>'
            + "".join(overrides) + "</Types>",
        "_rels/.rels":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        "xl/workbook.xml":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<bookViews><workbookView/></bookViews><sheets>'
            + "".join(f'<sheet name="{escape(name, {chr(34): "&quot;"})}" sheetId="{i}" r:id="rId{i}"/>' for i, name in zip(n, names))
            + '</sheets><calcPr fullCalcOnLoad="1"/></workbook>',
        "xl/_rels/workbook.xml.rels":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in n)
            + f'<Relationship Id="rId{styles_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            + f'<Relationship Id="rId{styles_id + 1}" Type="{_REL}/sheetMetadata" Target="metadata.xml"/>'
            + "</Relationships>",
        "xl/styles.xml": _STYLES,
        "xl/metadata.xml": _METADATA,
    }
    files.update(drawn)
    for i, sheet in zip(n, good):
        files[f"xl/worksheets/sheet{i}.xml"] = _worksheet(sheet, below)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in files.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))   # a fixed date: same answer, same bytes
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, text)
    return out.getvalue()


_FILE_ROW = re.compile(
    r'<row r="(\d+)"><c r="A\d+" t="inlineStr"><is><t xml:space="preserve">(.*?)</t></is></c>'
    r'(?:<c r="B\d+" t="inlineStr"><is><t xml:space="preserve">(.*?)</t></is></c>'
    r'<c r="C\d+" s="\d+">(?:<v>(\d+)</v>|<f>(\$C\$1)</f><v>\d+</v>)</c>)?'
    r'<c r="D\d+" s="\d+"><f>(.*?)</f></c><c r="E\d+" s="\d+"><v>(.*?)</v></c>')
_FILE_TOP = re.compile(r'<c r="C1" s="\d+"><v>(\d+)</v></c>')
_FILE_REF = re.compile(r"\bD(\d+)\b")


def read_back(data: bytes) -> list[list[tuple[str, str, float]]]:
    """What a workbook written by `workbook` says, tab by tab, turned back into the sheet's own form:
    (label, formula as a sheet row writes it, value). A fetching row is rebuilt from the series in its cell and
    the date in its cell or, where that cell refers to the top of the tab, the date in C1; a calculating row has
    its references moved back. For the control that the file and the page say the same thing."""
    unescape = lambda s: s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    tabs = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        # the worksheets themselves: beside them now sit their relation parts (xl/worksheets/_rels/...)
        for name in sorted((n for n in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)),
                           key=lambda n: int(re.search(r"(\d+)", n)[1])):
            xml = z.read(name).decode("utf-8")
            top = _FILE_TOP.search(xml)
            rows = []
            for r, label, series_id, serial, refers, formula, value in _FILE_ROW.findall(xml):
                if series_id:
                    if formula != f"_xll.ES.Value(B{r},C{r})":
                        raise ValueError(f"{name} row {r}: a fetching row does not read its own cells: {formula}")
                    if refers and not top:
                        raise ValueError(f"{name} row {r}: the Date refers to C1 and C1 holds no date")
                    day = _EPOCH + dt.timedelta(days=int(top[1] if refers else serial))
                    canonical = f'=ES.Value("{unescape(series_id)}","{day}")'
                else:
                    canonical = "=" + _FILE_REF.sub(lambda m: f"B{int(m[1]) - FIRST_ROW + 1}", unescape(formula))
                rows.append((unescape(label), canonical, float(value)))
            tabs.append(rows)
    return tabs
