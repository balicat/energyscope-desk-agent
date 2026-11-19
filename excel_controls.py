"""Control for the Excel sheets: a sheet with an error planted in it must be reported as not reproducing.

`ExcelReproduces` in the suite only proves that correct sheets pass. This proves the check can fail: each case
takes a sheet that reproduces on the frozen data, breaks one thing a careless edit would break, and requires
`excel.problems` to say so. Run with the date of the frozen data:

    LIBRARIAN_TODAY=<as_of of fixtures/series.json> python excel_controls.py
"""
import sys

from es_agent import excel, metrics, readings
from es_agent.models import SeriesFact, Spread
from es_agent.sources import FixtureSource

source = FixtureSource("fixtures/series.json")
BRENT, WTI = "PET.RBRTE.D", "PET.RWTC.D"


def spread_sheet() -> excel.Sheet:
    rows = readings.aligned(source, [BRENT, WTI], 30)
    d, (a, b) = rows[-1]
    return excel.for_spread(Spread(series_a=BRENT, name_a="Brent spot", series_b=WTI, name_b="WTI spot",
                                   units="Dollars per Barrel", period=d, value_a=a, value_b=b, spread=round(a - b, 6)))


def edited(sheet: excel.Sheet, row: int, old: str, new: str) -> excel.Sheet:
    copy = sheet.model_copy(deep=True)
    assert old in copy.rows[row].formula, (old, copy.rows[row].formula)
    copy.rows[row].formula = copy.rows[row].formula.replace(old, new)
    return copy


def fact_sheet(percent_places: int) -> excel.Sheet:
    c = metrics.change_over(source.meta(WTI), source.history(WTI), 30)
    return excel.for_fact(SeriesFact(series_id=WTI, name=c.name, units=c.units, latest_period=c.latest_period,
                                     latest_value=c.latest_value, lookback_days=30, base_period=c.base_period,
                                     base_value=c.base_value, change_abs=c.change_abs,
                                     change_pct=round(c.change_pct, percent_places)))


good = {
    "fact": fact_sheet(6),
    "spread": spread_sheet(),
    "curve": excel.for_reading(readings.curve(source, "brent"), source),
    "crack": excel.for_reading(readings.crack(source, "3-2-1"), source),
    "seasonal": excel.for_reading(readings.seasonal(source, "PET.WCESTUS1.W", 5), source),
}
failures = []
for name, sheet in good.items():
    if sheet is None or excel.problems(sheet, source):
        failures.append(f"the true {name} sheet does not reproduce: {sheet and excel.problems(sheet, source)}")
if failures:
    print("\n".join(failures))
    sys.exit(1)

day = str(good["spread"].rows[0].formula).split('"')[3]
earlier = str(readings.aligned(source, [BRENT, WTI], 30)[-2][0])
n_curve = len(good["curve"].rows) - 2
last_prior = len(good["seasonal"].rows) - 3
planted = [
    ("the other series", edited(good["spread"], 0, BRENT, WTI)),
    # Brent, not WTI: on the frozen data WTI has the same price on both days (a US holiday), and a wrong date
    # with the same value reproduces. The check compares values; it cannot see that kind of wrong date.
    ("the day before", edited(good["spread"], 0, f'"{day}")', f'"{earlier}")')),
    ("the subtraction reversed", edited(good["spread"], 2, "=B1-B2", "=B2-B1")),
    ("a reference one row off", edited(good["curve"], n_curve + 1, f"=B1-B{n_curve}", f"=B1-B{n_curve - 1}")),
    ("41 gallons to the barrel", edited(good["crack"], 3, "B3*42", "B3*41")),
    ("the weights of the 3-2-1 swapped", edited(good["crack"], 3, "(2*B2*42+B3*42)", "(B2*42+2*B3*42)")),
    ("an average over one year too few", edited(good["seasonal"], last_prior, f"B2:B{last_prior}", f"B2:B{last_prior - 1}")),
    ("an average that includes this year", edited(good["seasonal"], last_prior, f"B2:B{last_prior}", f"B1:B{last_prior}")),
    ("percent of the wrong base", edited(good["seasonal"], last_prior + 2, f"/B{last_prior + 1}*100", "/B1*100")),
    ("a date with no observation", edited(good["spread"], 0, f'"{day}")', '"2026-01-01")')),
    ("the percent of the wrong base", edited(good["fact"], 3, "/B2*100", "/B1*100")),
    # The reported value wrong, not the formula: a percent to two decimals where the data gives six. This is what
    # the live model wrote on 19 Nov 2026. It must be reported, because the validator now copies the tool's
    # figure into the fact, and a rounded one reaching a sheet means that copy did not happen.
    ("a percent the model rounded to two decimals", fact_sheet(2)),
]
for what, sheet in planted:
    if not excel.problems(sheet, source):
        failures.append(f"NOT CAUGHT: {what}")

# The workbook a reader downloads must say what the page shows: the same labels, formulas and values, tab by
# tab, in the same cells. Titles that Excel would refuse as tab names must come out legal and distinct.
book = excel.workbook(list(good.values()), "19 November 2026, 16:00 UTC")
try:
    back = excel.read_back(book)
except Exception as e:  # a workbook read_back cannot read is a failure of the writer, not of this script
    back = None
    failures.append(f"the workbook cannot be read back: {type(e).__name__}: {e}"[:200])
want = [[(r.label, r.formula, r.value) for r in s.rows] for s in good.values()]
if back != want:
    failures.append("the workbook does not say what the sheets say")
if excel.workbook(list(good.values()), "19 November 2026, 16:00 UTC") != book:
    failures.append("the same sheets gave two different workbooks")
# The file is laid out for a person: a header, series and date in their own cells, the value formula reading
# them, number formats, a Check column. `read_back` above goes through the writer's own idea of the layout, so a
# writer that is wrong in a way read_back shares would pass it (the reviewer broke the writer fourteen ways and
# six passed: arithmetic left in the pasted form's column, a Check that always says "same", styles swapped).
# So what every cell must hold is written out HERE, from the sheets alone, and nothing below calls excel's helpers.
import datetime as _dt, io as _io, re as _re, zipfile as _zip
_CELL = _re.compile(r'<c r="([A-Z]+)(\d+)"(?: s="(\d+)")?(?: t="inlineStr")?>(.*?)</c>')
_FETCH = _re.compile(r'^=ES\.Value\("([^"]+)","(\d{4}-\d{2}-\d{2})"\)$')


def _cells(xml):
    """{(column, row): (style or None, 'text' | 'formula' | 'value', content)} of one worksheet."""
    out = {}
    for col, row, style, body in _CELL.findall(xml):
        for kind, pat in (("text", r"<is><t[^>]*>(.*?)</t></is>"), ("formula", r"<f>(.*?)</f>"), ("value", r"<v>(.*?)</v>")):
            m = _re.fullmatch(pat, body)
            if m:
                text = m[1].replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
                out[(col, int(row))] = (style or None, kind, text)   # no s= attribute: the default style
    return out


with _zip.ZipFile(_io.BytesIO(book)) as _z:
    _tabs = [_z.read(f"xl/worksheets/sheet{i}.xml").decode("utf-8") for i in range(1, len(good) + 1)]
    _styles = _z.read("xl/styles.xml").decode("utf-8") if "xl/styles.xml" in _z.namelist() else ""
_codes = dict(_re.findall(r'<numFmt numFmtId="(\d+)" formatCode="([^"]*)"', _styles))
_xfs = _re.findall(r'<xf numFmtId="(\d+)" fontId="(\d+)"[^>]*xfId="0"[^>]*/>', _styles)      # cellXfs, in order
_shown = lambda style: _codes.get(_xfs[int(style)][0], "General") if style is not None and int(style) < len(_xfs) else "General"
_bold = lambda style: style is not None and int(style) < len(_xfs) and _xfs[int(style)][1] != "0"
layout = []
for _t, (_xml, _sheet) in enumerate(zip(_tabs, good.values()), 1):
    c = _cells(_xml)
    where = f"tab {_t}"
    if [c.get((col, 1), (None, "", ""))[2] for col in "ABCDEF"] != ["What", "Series", "Date", "Value", "Reported", "Check"]:
        layout.append(f"{where}: the header row is not What | Series | Date | Value | Reported | Check")
    if not all(_bold(c.get((col, 1), (None,))[0]) for col in "ABCDEF"):
        layout.append(f"{where}: the header is not bold")
    if '<pane ySplit="1"' not in _xml or 'state="frozen"' not in _xml:
        layout.append(f"{where}: the header row is not frozen")
    for i, row in enumerate(_sheet.rows, 1):
        r = i + 1
        at = f"{where} row {r}"
        if c.get(("A", r), (None, "", ""))[1:] != ("text", row.label):
            layout.append(f"{at}: column A is not the row's label")
        value = c.get(("D", r), (None, "", ""))
        fetch = _FETCH.match(row.formula)
        if fetch:
            series_id, day = fetch.groups()
            serial = (_dt.date.fromisoformat(day) - _dt.date(1899, 12, 30)).days
            if c.get(("B", r), (None, "", ""))[1:] != ("text", series_id):
                layout.append(f"{at}: column B is not the series ID {series_id}")
            date = c.get(("C", r), (None, "", ""))
            if date[1:] != ("value", str(serial)) or _shown(date[0]) != "yyyy-mm-dd":
                layout.append(f"{at}: column C is not the date {day} as a real date shown yyyy-mm-dd")
            if value[1:] != ("formula", f"_xll.ES.Value(B{r},C{r})"):
                layout.append(f"{at}: Value does not fetch from this row's series and date cells: {value[2]}")
        else:
            # the sheet's arithmetic names cells of the pasted form (formula in column B, first row 1); in the
            # file the same cells are column D, one row down. No other column may be named.
            moved = _re.sub(r"\bB(\d+)\b", lambda m: f"D{int(m[1]) + 1}", row.formula.lstrip("="))
            named = {col for col, _ in _re.findall(r"\b([A-Z]{1,3})(\d+)\b", value[2])}
            if value[1:] != ("formula", moved) or named - {"D"}:
                layout.append(f"{at}: Value should be {moved}, the file has {value[2]}")
            if ("B", r) in c or ("C", r) in c:
                layout.append(f"{at}: a calculated row has something in Series or Date")
        if _shown(value[0]) != "#,##0.00":
            layout.append(f"{at}: Value is shown as {_shown(value[0])}, not #,##0.00")
        reported = c.get(("E", r), (None, "", ""))
        if reported[1] != "value" or float(reported[2] or "nan") != row.value or _shown(reported[0]) != "#,##0.00":
            layout.append(f"{at}: Reported is not {row.value!r} shown as #,##0.00")
        # Check is the reader's verdict, so its formula is spelled out here: "same" within the larger of 0.00005
        # and one part in a million of Reported, otherwise Value minus Reported, and not rounded for display.
        verdict = (f'IF(ISNUMBER(D{r}),IF(ABS(D{r}-E{r})<=MAX(0.00005,0.000001*ABS(E{r})),"same",D{r}-E{r}),"")')
        check = c.get(("F", r), (None, "", ""))
        if check[1:] != ("formula", verdict) or _shown(check[0]) != "General":
            layout.append(f"{at}: Check is not the verdict formula in the General format: {check[2][:80]}")
if not _tabs or not _styles:
    layout.append("the workbook has no worksheets or no styles")
failures += layout[:6]
# Twelve tabs, so that a repeat falls at a two-digit position: the first version made a 32-character name there
# and Excel refused the file. Long titles, repeats in another case, characters Excel forbids, an empty title.
long = "U.S. Ending Stocks excluding SPR of Crude Oil, Weekly: latest against the same time of year"
tabs = excel._tab_names(["A (3)", "A", "A", "Brent/WTI: spread [futures]", "brent/wti: spread [futures]", "x" * 40, ""]
                        + [long] * 4 + ["x" * 27] * 4 + [long.upper()] * 100)
if (len({t.lower() for t in tabs}) != len(tabs) or any(len(t) > 31 or not t or set(t) & set("[]:*?/\\") for t in tabs)):
    failures.append(f"tab names Excel would refuse: {[t for t in tabs if len(t) > 31][:3]}")
missed = [f for f in failures if f.startswith("NOT CAUGHT")]
for line in failures:
    print(line)
print(f"excel control: {len(planted) - len(missed)} of {len(planted)} planted errors reported; "
      f"{len(good)} true sheets reproduce; the workbook "
      + ("reads back as the sheets and every cell is as the layout says" if back == want and not layout
         else "DOES NOT match the sheets or the layout") + f" ({len(book)} bytes)")
sys.exit(1 if failures else 0)
