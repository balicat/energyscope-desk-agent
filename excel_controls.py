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
GIVEN_AT = "19 November 2026, 16:00 UTC"
book = excel.workbook(list(good.values()), GIVEN_AT)
try:
    back = excel.read_back(book)
except Exception as e:  # a workbook read_back cannot read is a failure of the writer, not of this script
    back = None
    failures.append(f"the workbook cannot be read back: {type(e).__name__}: {e}"[:200])
want = [[(r.label, r.formula, r.value) for r in s.rows] for s in good.values()]
if back != want:
    failures.append("the workbook does not say what the sheets say")
if excel.workbook(list(good.values()), GIVEN_AT) != book:
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
    _book_xml = _z.read("xl/workbook.xml").decode("utf-8")
    _rels_xml = _z.read("xl/_rels/workbook.xml.rels").decode("utf-8")
_codes = dict(_re.findall(r'<numFmt numFmtId="(\d+)" formatCode="([^"]*)"', _styles))
_xfs = _re.findall(r'<xf numFmtId="(\d+)" fontId="(\d+)"[^>]*xfId="0"[^>]*/>', _styles)      # cellXfs, in order
_shown = lambda style: _codes.get(_xfs[int(style)][0], "General") if style is not None and int(style) < len(_xfs) else "General"
_bold = lambda style: style is not None and int(style) < len(_xfs) and _xfs[int(style)][1] != "0"
layout = []
# Where things are, stated here and not taken from the writer: the tab's date in C1 beside a label in A1, the
# header in row 3 (frozen), the sheet's rows from row 4.
_TOP_LABEL = "Date (change this one cell: every row below that shows this date follows)"
_HEAD, _FIRST = 3, 4
_serial = lambda day: (_dt.date.fromisoformat(day) - _dt.date(1899, 12, 30)).days
for _t, (_xml, _sheet) in enumerate(zip(_tabs, good.values()), 1):
    c = _cells(_xml)
    where = f"tab {_t}"
    # the tab's date: the one most of its fetching rows use, the first of them on a tie
    days = [m[2] for m in (_FETCH.match(row.formula) for row in _sheet.rows) if m]
    shared = max(days, key=lambda d: (days.count(d), -days.index(d))) if days else None
    top = c.get(("C", 1), (None, "", ""))
    if shared is not None:
        if c.get(("A", 1), (None, "", ""))[1:] != ("text", _TOP_LABEL) or not _bold(c.get(("A", 1), (None,))[0]):
            layout.append(f"{where}: A1 is not the label of the tab's date, in bold")
        if top[1:] != ("value", str(_serial(shared))) or _shown(top[0]) != "yyyy-mm-dd":
            layout.append(f"{where}: C1 is not the tab's date {shared} as a real date shown yyyy-mm-dd")
    if [c.get((col, _HEAD), (None, "", ""))[2] for col in "ABCDEF"] != ["What", "Series", "Date", "Value", "Reported", "Check"]:
        layout.append(f"{where}: row {_HEAD} is not the header What | Series | Date | Value | Reported | Check")
    if not all(_bold(c.get((col, _HEAD), (None,))[0]) for col in "ABCDEF"):
        layout.append(f"{where}: the header is not bold")
    if f'<pane ySplit="{_HEAD}"' not in _xml or 'state="frozen"' not in _xml:
        layout.append(f"{where}: the rows down to the header are not frozen")
    for i, row in enumerate(_sheet.rows):
        r = _FIRST + i
        at = f"{where} row {r}"
        if c.get(("A", r), (None, "", ""))[1:] != ("text", row.label):
            layout.append(f"{at}: column A is not the row's label")
        value = c.get(("D", r), (None, "", ""))
        fetch = _FETCH.match(row.formula)
        if fetch:
            series_id, day = fetch.groups()
            if c.get(("B", r), (None, "", ""))[1:] != ("text", series_id):
                layout.append(f"{at}: column B is not the series ID {series_id}")
            # a row on the tab's date must REFER to C1, so that one edit moves it; a row on another date must
            # hold its own date, or an edit of C1 would move a row it should not
            date = c.get(("C", r), (None, "", ""))
            wanted = ("formula", "$C$1") if day == shared else ("value", str(_serial(day)))
            if date[1:] != wanted or _shown(date[0]) != "yyyy-mm-dd":
                layout.append(f"{at}: the Date cell should be {wanted[1]} ({day}) shown yyyy-mm-dd, the file has {date[2]}")
            if value[1:] != ("formula", f"_xll.ES.Value(B{r},C{r})"):
                layout.append(f"{at}: Value does not fetch from this row's series and date cells: {value[2]}")
        else:
            # the sheet's arithmetic names cells of the pasted form (formula in column B, first row 1); in the
            # file the same cells are column D, three rows down. No other column may be named.
            moved = _re.sub(r"\bB(\d+)\b", lambda m: f"D{int(m[1]) + _FIRST - 1}", row.formula.lstrip("="))
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
    # nothing may sit between the top cell and the header, or in the header's own row beyond its six cells
    stray = sorted(k for k in c if k[1] < _FIRST and k not in {("A", 1), ("C", 1)} | {(col, _HEAD) for col in "ABCDEF"})
    if stray:
        layout.append(f"{where}: unexpected cells above the rows: {stray[:4]}")
# What holds for the workbook as a whole. The reviewer's second set, written before it had read the control:
# tabs named in reverse (the tab called "U.S. Ending Stocks" held the crack rows), names attached to the wrong
# worksheet through workbook.xml, the 1904 calendar switched on (Date read 2030-11-07 beside the value of
# 2026-11-06 and Check said "same"), a Value column three characters wide (## in every cell), and the notes a
# reader depends on dropped or carrying another time.
_targets = dict(_re.findall(r'<Relationship Id="(rId\d+)"[^>]*Target="([^"]+)"', _rels_xml))
_named = _re.findall(r'<sheet name="([^"]*)" sheetId="\d+" r:id="(rId\d+)"/>', _book_xml)
_unx = lambda s: s.replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
for _t, _sheet in enumerate(good.values(), 1):
    # a tab's name is its sheet's title with the characters Excel forbids made spaces, cut to 31 (no repeats here)
    expected = _re.sub(r"[\[\]:*?/\\]", " ", _sheet.title).strip().strip("'")[:31].rstrip()
    name, rid = (_unx(_named[_t - 1][0]), _named[_t - 1][1]) if _t <= len(_named) else ("", "")
    if name != expected or _targets.get(rid) != f"worksheets/sheet{_t}.xml":
        layout.append(f"tab {_t}: named {name!r} on {_targets.get(rid)}, expected {expected!r} on worksheets/sheet{_t}.xml")
if _re.search(r'date1904="(1|true)"', _book_xml):
    layout.append("the workbook uses the 1904 calendar: every date would read four years and a day late")
# The file holds formulas and no cached results, so it asks Excel to calculate when it opens. Excel 16 does so
# anyway (the reviewer removed the flag and saw no difference), but the request is deliberate and stays.
if 'fullCalcOnLoad="1"' not in _book_xml:
    layout.append("the workbook does not ask Excel to calculate on opening")
for _t, (_xml, _sheet) in enumerate(zip(_tabs, good.values()), 1):
    widths = {}
    for lo, hi, w in _re.findall(r'<col min="(\d+)" max="(\d+)" width="([\d.]+)"', _xml):
        for col in range(int(lo), int(hi) + 1):
            widths[col] = float(w)
    if min(widths.get(4, 0), widths.get(5, 0)) < 12 or widths.get(3, 0) < 10:
        layout.append(f"tab {_t}: the Date, Value or Reported column is too narrow to show its values: {widths}")
    c = _cells(_xml)
    notes = [v[2] for (col, r), v in c.items() if col == "A" and r >= _FIRST + len(_sheet.rows) and v[1] == "text"]
    for needed, why in (("Protected View", "what to do when nothing calculates"), (GIVEN_AT, "when the answer was given"),
                        ("3.2.0", "which add-in the formulas need"), ("Refresh All", "how to make the values appear"),
                        ("C1", "which cell moves the whole tab to another date")):
        if not any(needed in n for n in notes):
            layout.append(f"tab {_t}: no note says {why} ({needed!r})")
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
