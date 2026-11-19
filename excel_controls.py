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
_CELL = _re.compile(r'<c r="([A-Z]+)(\d+)"(?: s="(\d+)")?((?: [a-zA-Z]+="[^"]*")*)>(.*?)</c>')
_FETCH = _re.compile(r'^=ES\.Value\("([^"]+)","(\d{4}-\d{2}-\d{2})"\)$')


def _cells(xml):
    """{(column, row): (style or None, kind, content)} of one worksheet. Kinds: 'text', 'formula', 'value';
    'stored' (a formula with its result beside it: "$C$1 = 46337"); 'stored text' (the same, a text result);
    'spill' (the one formula that fills other cells: "R4: formula"); 'odd' for any cell written another way, so
    that nothing in the file goes unseen."""
    un = lambda s: s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    out = {}
    for col, row, style, attrs, body in _CELL.findall(xml):
        key, style = (col, int(row)), style or None      # no s= attribute: the default style
        spill = _re.fullmatch(r'<f t="array" ref="([A-Z]+\d+)">(.*?)</f>', body)
        both = _re.fullmatch(r"<f>(.*?)</f><v>(.*?)</v>", body)
        if spill:
            out[key] = (style, "spill" if attrs == ' cm="1"' else "odd", f"{spill[1]}: {un(spill[2])}")
        elif both:
            out[key] = (style, {"": "stored", ' t="str"': "stored text"}.get(attrs, "odd"), f"{un(both[1])} = {un(both[2])}")
        else:
            out[key] = (style, "odd", body[:60])
            for kind, pat in (("text", r"<is><t[^>]*>(.*?)</t></is>"), ("formula", r"<f>(.*?)</f>"), ("value", r"<v>(.*?)</v>")):
                m = _re.fullmatch(pat, body)
                if m and attrs == (' t="inlineStr"' if kind == "text" else ""):
                    out[key] = (style, kind, un(m[1]))
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
# The words beside C1 count the rows that follow it, and the note under the rows says what does not move. Both
# are spelled out here: the reviewer rewrote the note to say ALL rows follow and the first control passed it.
_C1_NOTE = ("The Date in cell C1 belongs to the rows whose Date cell shows the same date: change C1 and those rows "
            "follow, with everything calculated from them. A row with another date keeps its own cell and does not "
            "move, so where a tab compares dates (a change over thirty days, the same week of earlier years) moving "
            "C1 alone changes what is compared. C1 must hold a date: emptied, the rows that follow it find no value.")
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
        _n, _k = len(days), days.count(shared)
        _label = ("Date: change this cell and the one fetched row follows" if _n == 1 else
                  f"Date: change this cell and all {_n} fetched rows follow" if _k == _n else
                  f"Date: change this cell and {_k} of {_n} fetched rows follow{'s' if _k == 1 else ''}; the other "
                  + ("one keeps its own date" if _n - _k == 1 else f"{_n - _k} keep their own dates"))
        if c.get(("A", 1), (None, "", ""))[1:] != ("text", _label) or not _bold(c.get(("A", 1), (None,))[0]):
            layout.append(f"{where}: A1 does not say, in bold, that {_k} of {_n} fetched rows follow C1")
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
            # (and it stores that date beside the reference, which is what Protected View shows)
            wanted = ("stored", f"$C$1 = {_serial(day)}") if day == shared else ("value", str(_serial(day)))
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
    # (columns A to F; what stands right of them is the history, stated further down)
    stray = sorted(k for k in c if k[1] < _FIRST and len(k[0]) == 1 and k[0] <= "F"
                   and k not in {("A", 1), ("C", 1)} | {(col, _HEAD) for col in "ABCDEF"})
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
                        ("3.2.0", "which add-in the formulas need"), ("Refresh All", "how to make the values appear")):
        if not any(needed in n for n in notes):
            layout.append(f"tab {_t}: no note says {why} ({needed!r})")
    if _C1_NOTE not in notes:
        layout.append(f"tab {_t}: the note on C1 is not the one that says which rows follow and which do not move")
# ---- The history: a table from column R and charts in columns H to P. Stated here, from the sheets alone.
# On every tab that fetches: H1 a label; R3 "Date" and from S3 one cell per series of the tab, in the order the
# rows name them, each a REFERENCE to the Series cell of the first row naming it with the ID stored beside it;
# R4 the one formula, ES.Table over those header cells for the 365 days to C1 with "#N/A" for a day without a
# value, stored as a dynamic array (so it fills the cells around it; stored plainly Excel shows one cell). No
# other cell right of column F: inside the table's range it would stop the formula filling (#SPILL!). One line
# chart per series, three at most, in columns H to P below the frozen rows and clear of each other, each reading
# the dates R4:R369, its own series column and its own header cell, with ONE value axis.
_HISTORY_LABEL = ("History: the year to the date in C1. A chart for each of the first three series; "
                  "the table behind them starts in column R")
_HISTORY_NOTE = ("To the right: the history of this sheet's series over the year to the date in C1, as charts (the "
                 "first three series) and as a table from column R, filled by the one formula in R4. Both follow "
                 "C1 and the Series cells. A day with no value shows #N/A in grey; do not type inside the table. "
                 "This part needs Excel 365 or Excel 2021.")
_num = lambda col: sum((ord(ch) - 64) * 26 ** i for i, ch in enumerate(reversed(col)))


def _col(n):
    s = ""
    while n:
        n, k = divmod(n - 1, 26)
        s = chr(65 + k) + s
    return s


with _zip.ZipFile(_io.BytesIO(book)) as _z:
    _parts = {n: _z.read(n).decode("utf-8") for n in _z.namelist()}
_types = _parts.get("[Content_Types].xml", "")
_meta = _parts.get("xl/metadata.xml", "")
if "XLDAPR" not in _meta or 'fDynamic="1"' not in _meta or '<rc t="1" v="0"/>' not in _meta:
    layout.append("no part declaring dynamic arrays (xl/metadata.xml): the history formula would show one cell")
if 'Target="metadata.xml"' not in _rels_xml or '"/xl/metadata.xml"' not in _types:
    layout.append("the dynamic-array part is not related to the workbook or has no content type")
if not _re.search(r'<dxfs count="1"><dxf><font><color rgb="FF(?!000000)[0-9A-F]{6}"/></font></dxf></dxfs>', _styles):
    layout.append("no format to show the history's days without a value in grey")
_used = set()
for _t, (_xml, _sheet) in enumerate(zip(_tabs, good.values()), 1):
    c = _cells(_xml)
    where = f"tab {_t}"
    ids, first = [], {}
    for i, row in enumerate(_sheet.rows):
        m = _FETCH.match(row.formula)
        if m and m[1] not in first:
            first[m[1]] = _FIRST + i
            ids.append(m[1])
    right = {k: v for k, v in c.items() if _num(k[0]) > 6}
    if not ids:
        if right or "<drawing" in _xml:
            layout.append(f"{where}: fetches nothing and has a history")
        continue
    last = _col(18 + len(ids))
    stated = {("H", 1): ("text", _HISTORY_LABEL, True, None), ("R", _HEAD): ("text", "Date", True, None),
              ("R", _FIRST): ("spill", f'R{_FIRST}: _xll.ES.Table(S{_HEAD}:{last}{_HEAD},$C$1-365,$C$1,"#N/A")', False, "yyyy-mm-dd")}
    for k, sid in enumerate(ids):
        stated[(_col(19 + k), _HEAD)] = ("stored text", f"B{first[sid]} = {sid}", True, None)
    for key, (kind, content, bold, shown) in stated.items():
        got = c.get(key, (None, "nothing", ""))
        if got[1:] != (kind, content) or (bold and not _bold(got[0])) or (shown and _shown(got[0]) != shown):
            layout.append(f"{where}: {key[0]}{key[1]} should be {kind} {content[:70]}, the file has {got[1]} {got[2][:70]}")
    extra = sorted(set(right) - set(stated))
    if extra:
        layout.append(f"{where}: cells right of the rows that the history does not own; inside the table they stop it filling: {extra[:4]}")
    cols = {}
    for lo, hi, w, st in _re.findall(r'<col min="(\d+)" max="(\d+)" width="([\d.]+)"(?: style="(\d+)")?', _xml):
        for n in range(int(lo), int(hi) + 1):
            cols[n] = (float(w), st or None)
    if cols.get(18, (0, None))[0] < 10 or _shown(cols.get(18, (0, None))[1]) != "yyyy-mm-dd":
        layout.append(f"{where}: column R would not show the history's dates as yyyy-mm-dd")
    if any(cols.get(19 + k, (0, None))[0] < 12 or _shown(cols.get(19 + k, (0, None))[1]) != "#,##0.00" for k in range(len(ids))):
        layout.append(f"{where}: a series column of the history is too narrow or not shown as #,##0.00")
    if (f'<conditionalFormatting sqref="S{_FIRST}:{last}369"><cfRule type="containsErrors" dxfId="0" priority="1">'
            f'<formula>ISERROR(S{_FIRST})</formula></cfRule></conditionalFormatting>') not in _xml:
        layout.append(f"{where}: the history's days without a value are not shown in grey over S{_FIRST}:{last}369")
    notes = [v[2] for (col, r), v in c.items() if col == "A" and r >= _FIRST + len(_sheet.rows) and v[1] == "text"]
    if _HISTORY_NOTE not in notes:
        layout.append(f"{where}: the note on the history is missing or reworded")
    # the charts
    name = _unx(_named[_t - 1][0]) if _t <= len(_named) else ""
    q = "'" + name.replace("'", "''") + "'"
    target = _re.search(r'<Relationship Id="rId1" Type="[^"]*/drawing" Target="\.\./drawings/(drawing\d+\.xml)"/>',
                        _parts.get(f"xl/worksheets/_rels/sheet{_t}.xml.rels", ""))
    if '<drawing r:id="rId1"/>' not in _xml or not target or f'"/xl/drawings/{target[1]}"' not in _types:
        layout.append(f"{where}: no drawing holds its charts")
        continue
    drawing = _parts.get("xl/drawings/" + target[1], "")
    charts = dict(_re.findall(r'<Relationship Id="(rId\d+)" Type="[^"]*/chart" Target="\.\./charts/(chart\d+\.xml)"/>',
                              _parts.get(f"xl/drawings/_rels/{target[1]}.rels", "")))
    anchors = sorted((int(r0), int(r1), int(c0), int(c1), rid) for c0, r0, c1, r1, rid in _re.findall(
        r'<xdr:from><xdr:col>(\d+)</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>(\d+)</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>'
        r'<xdr:to><xdr:col>(\d+)</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>(\d+)</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>'
        r'.*?r:id="(rId\d+)"', drawing))
    if len(anchors) != min(3, len(ids)) or drawing.count("<xdr:twoCellAnchor>") != len(anchors):
        layout.append(f"{where}: {drawing.count('<xdr:twoCellAnchor>')} charts for {len(ids)} series (one each, three at most)")
    floor = _FIRST - 1          # rows count from 0 here: the first row below the frozen ones
    for k, (r0, r1, c0, c1, rid) in enumerate(anchors):
        at = f"{where} chart {k + 1}"
        if c0 < 7 or c1 > 16 or c1 <= c0 or r0 < floor or r1 <= r0:
            layout.append(f"{at}: not in columns H to P below the frozen rows and clear of the chart above")
        floor = r1
        part = charts.get(rid, "")
        chart = _parts.get("xl/charts/" + part, "")
        if not chart or part in _used or f'"/xl/charts/{part}"' not in _types:
            layout.append(f"{at}: its chart part is missing, shared with another chart or has no content type")
            continue
        _used.add(part)
        col = _col(19 + k)
        reads = [_unx(f) for f in _re.findall(r"<c:f>(.*?)</c:f>", chart)]
        should = [f"{q}!${col}${_HEAD}", f"{q}!$R${_FIRST}:$R$369", f"{q}!${col}${_FIRST}:${col}$369"]
        if reads != should:
            layout.append(f"{at}: reads {reads}, should read {should}")
        if chart.count("<c:ser>") != 1 or chart.count("<c:valAx>") != 1 or chart.count("<c:dateAx>") != 1 or "<c:lineChart>" not in chart:
            layout.append(f"{at}: not one line on one date axis and one value axis")
        if '<c:dispBlanksAs val="span"/>' not in chart:
            layout.append(f"{at}: days without a value would break the line or draw it at zero")
        if "<c:title>" not in chart or '<c:autoTitleDeleted val="0"/>' not in chart:
            layout.append(f"{at}: no title, so nothing says which series it is")
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
