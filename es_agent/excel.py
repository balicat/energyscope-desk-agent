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
#     A What | B Series | C Date | D Value | E Reported | F Check        row 1 is the header
#
# A row that fetches holds its series ID in B and its date in C, and D is =ES.Value(B,C), so a reader can change
# either and watch the value follow. A row that calculates has its arithmetic in D. Values show with thousands
# separators and two decimals; the cells keep every digit. The sheet's own formulas (Row.formula, the form the
# page shows and `evaluate` checks) are written as if pasted at A1 with the formula in column B, so they are
# moved one row down and into column D here, and `read_back` moves them back to prove nothing was lost.

HEADER = ("What", "Series", "Date", "Value", "Reported", "Check")
_EPOCH = dt.date(1899, 12, 30)   # day 0 of Excel's calendar
_STYLE_NUMBER, _STYLE_DATE, _STYLE_HEAD = 1, 2, 3


def _moved(formula: str) -> str:
    """An arithmetic formula as the workbook holds it: B{n} of the pasted form is D{n+1} here."""
    return _REF.sub(lambda m: f"D{int(m[1]) + 1}", formula.lstrip("="))


def _same(r: int) -> str:
    """The Check column: "same" when Value equals Reported by the tolerance `problems` uses, otherwise Value
    minus Reported. A plain difference showed -2.3E-07 on a percent the answer reports to six decimals. The
    column keeps the General format: at two decimals a real difference of 0.003 would read 0.00."""
    return (f'IF(ISNUMBER(D{r}),IF(ABS(D{r}-E{r})<=MAX({TOLERANCE_ABS:.5f},{TOLERANCE_REL:.6f}*ABS(E{r})),'
            f'"same",D{r}-E{r}),"")')


def _text(ref: str, text: str, style: int = 0) -> str:
    s = f' s="{style}"' if style else ""
    return f'<c r="{ref}"{s} t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'


def _worksheet(sheet: Sheet, notes: list[str]) -> str:
    xml = ['<row r="1">' + "".join(_text(f"{col}1", name, _STYLE_HEAD) for col, name in zip("ABCDEF", HEADER)) + "</row>"]
    for i, row in enumerate(sheet.rows, 1):
        r = i + 1
        fetch = _GET.match(row.formula)
        if fetch:
            series_id, day = fetch.groups()
            serial = (dt.date.fromisoformat(day) - _EPOCH).days
            inputs = (f'{_text(f"B{r}", series_id)}<c r="C{r}" s="{_STYLE_DATE}"><v>{serial}</v></c>'
                      f'<c r="D{r}" s="{_STYLE_NUMBER}"><f>_xll.ES.Value(B{r},C{r})</f></c>')
        else:
            inputs = f'<c r="D{r}" s="{_STYLE_NUMBER}"><f>{escape(_moved(row.formula))}</f></c>'
        xml.append(f'<row r="{r}">{_text(f"A{r}", row.label)}{inputs}'
                   f'<c r="E{r}" s="{_STYLE_NUMBER}"><v>{row.value!r}</v></c>'
                   f'<c r="F{r}"><f>{escape(_same(r))}</f></c></row>')
    for j, note in enumerate(notes, len(sheet.rows) + 3):
        xml.append(f'<row r="{j}">{_text(f"A{j}", note)}</row>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
            'state="frozen"/></sheetView></sheetViews>'
            '<cols><col min="1" max="1" width="58" customWidth="1"/><col min="2" max="2" width="34" customWidth="1"/>'
            '<col min="3" max="3" width="12" customWidth="1"/><col min="4" max="5" width="16" customWidth="1"/>'
            '<col min="6" max="6" width="12" customWidth="1"/></cols>'
            f'<sheetData>{"".join(xml)}</sheetData></worksheet>')


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
           '</styleSheet>')


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
        "Change a Date or a Series ID and Value follows; Reported stays what the answer said, so Check will then "
        "show the difference. Values are shown to two decimals; the cells hold every digit.",
        # The reviewer, editing as a reader would: "WTI ..., 2026-11-11" stayed beside a Date of 2026-10-12, and an
        # emptied Date gave the latest value with nothing to say which day (on a forecast series, the furthest one).
        "The text in What was written for the original series and date and does not change when you edit them. "
        "Write dates as 2026-11-17 or pick them as dates. An empty Date gives the last value of the series, which "
        "on a series that includes forecasts is the furthest forecast.",
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
    files = {
        "[Content_Types].xml":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in n)
            + "</Types>",
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
            + "</Relationships>",
        "xl/styles.xml": _STYLES,
    }
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
    r'(?:<c r="B\d+" t="inlineStr"><is><t xml:space="preserve">(.*?)</t></is></c><c r="C\d+" s="\d+"><v>(\d+)</v></c>)?'
    r'<c r="D\d+" s="\d+"><f>(.*?)</f></c><c r="E\d+" s="\d+"><v>(.*?)</v></c>')
_FILE_REF = re.compile(r"\bD(\d+)\b")


def read_back(data: bytes) -> list[list[tuple[str, str, float]]]:
    """What a workbook written by `workbook` says, tab by tab, turned back into the sheet's own form:
    (label, formula as a sheet row writes it, value). A fetching row is rebuilt from the series and the date in
    its cells, a calculating row has its references moved back. For the control that the file and the page say
    the same thing."""
    unescape = lambda s: s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    tabs = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in sorted((n for n in z.namelist() if n.startswith("xl/worksheets/")),
                           key=lambda n: int(re.search(r"(\d+)", n)[1])):
            rows = []
            for r, label, series_id, serial, formula, value in _FILE_ROW.findall(z.read(name).decode("utf-8")):
                if series_id:
                    if formula != f"_xll.ES.Value(B{r},C{r})":
                        raise ValueError(f"{name} row {r}: a fetching row does not read its own cells: {formula}")
                    canonical = f'=ES.Value("{unescape(series_id)}","{_EPOCH + dt.timedelta(days=int(serial))}")'
                else:
                    canonical = "=" + _FILE_REF.sub(lambda m: f"B{int(m[1]) - 1}", unescape(formula))
                rows.append((unescape(label), canonical, float(value)))
            tabs.append(rows)
    return tabs
