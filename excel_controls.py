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
back = excel.read_back(book)
want = [[(r.label, r.formula, r.value) for r in s.rows] for s in good.values()]
if back != want:
    failures.append("the workbook does not say what the sheets say")
if excel.workbook(list(good.values()), "19 November 2026, 16:00 UTC") != book:
    failures.append("the same sheets gave two different workbooks")
# Twelve tabs, so that a repeat falls at a two-digit position: the first version made a 32-character name there
# and Excel refused the file. Long titles, repeats in another case, characters Excel forbids, an empty title.
long = "U.S. Ending Stocks excluding SPR of Crude Oil, Weekly: latest against the same time of year"
tabs = excel._tab_names(["A (3)", "A", "A", "Brent/WTI: spread [futures]", "brent/wti: spread [futures]", "x" * 40, ""]
                        + [long] * 4 + ["x" * 27] * 4 + [long.upper()] * 100)
if (len({t.lower() for t in tabs}) != len(tabs) or any(len(t) > 31 or not t or set(t) & set("[]:*?/\\") for t in tabs)):
    failures.append(f"tab names Excel would refuse: {[t for t in tabs if len(t) > 31][:3]}")
for line in failures:
    print(line)
print(f"excel control: {len(planted) - len(failures)} of {len(planted)} planted errors reported; "
      f"{len(good)} true sheets reproduce; the workbook reads back as the sheets ({len(book)} bytes)")
sys.exit(1 if failures else 0)
