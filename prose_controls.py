"""Control for the summary: what the model may write, and what it may not.

    python prose_controls.py        # exit 1 if any expectation below is not met

Since 18 Nov 2026 a summary is a template: the model places slots and code writes every figure
(es_agent/slots.py). This file holds the cases that rule must decide, each with what must happen.
No model, no data, no cost; it runs in CI and in the release gate.

- TYPED: the forty wrong sentences of the earlier control (thirty-six that the old prose rules
  rejected and four they could not). Every one must now be rejected, because none of them can be
  written without typing a figure.
- WRONG: templates that break a rule: an address the run never earned, a brace that is not a slot,
  the usual ways of abusing a format string, a number in words, a date in words, a direction or a
  verdict in the model's own word, two figures joined into a ratio.
- RIGHT: templates that must pass, so that the rules cannot be tightened into refusing good answers.
- WRITES: what code prints for a slot, character for character.
- LIMIT: wrong, and still accepted. The free words between slots are the model's. They are listed
  here so the gap stays visible; if one starts to be caught, this file fails until it is moved.
- TAMPERED: a true answer built from the frozen data, then altered after the fact in four ways (a
  value in a table, a character of the summary, an added caveat, a typed figure in the template).
  The check that runs on every live answer must refuse each. The model can no longer mistype a
  table, so this is where a wrong table is planted.
"""

from __future__ import annotations

import datetime as dt
import os
import sys

from es_agent import slots
from es_agent.models import Reading, SeriesFact, Spread

D = dt.date(2026, 11, 17)
brent = SeriesFact(series_id="ICE.BRENT.M1.D", name="Brent futures M1", units="USD/bbl", latest_period=D, latest_value=93.07)
wti_up = SeriesFact(series_id="PET.RWTC.D", name="Cushing, OK WTI Spot Price FOB", units="Dollars per Barrel", latest_period=D,
                    latest_value=88.10, lookback_days=7, base_period=dt.date(2026, 11, 10), base_value=86.90, change_abs=1.20,
                    change_pct=1.380898)
flat = SeriesFact(series_id="X.FLAT.D", name="A flat series", units="USD/bbl", latest_period=D, latest_value=50.0, lookback_days=7,
                  base_period=dt.date(2026, 11, 10), base_value=50.0, change_abs=0.0, change_pct=0.0)
tiny = SeriesFact(series_id="X.TINY.D", name="A {braced} series", units="USD/bbl", latest_period=D, latest_value=50.00001,
                  lookback_days=7, base_period=dt.date(2026, 11, 10), base_value=50.0, change_abs=0.00001, change_pct=0.00002)
stocks = SeriesFact(series_id="PET.WCESTUS1.W", name="US ending stocks excluding SPR of crude oil", units="Thousand Barrels",
                    latest_period=dt.date(2026, 11, 13), latest_value=414417.0, also={"million_barrels": 414.417})
gap = Spread(series_a="PET.RBRTE.D", name_a="Brent spot", series_b="PET.RWTC.D", name_b="WTI spot", units="USD/bbl",
             period=dt.date(2026, 11, 11), value_a=87.48, value_b=88.10, spread=-0.62,
             extras={"percentile": 17.4, "percentile_years": 3})
curve = Reading(key="curve:brent", title="Brent futures curve", period=D, units="USD/bbl", series_ids=["ICE.BRENT.M1.D", "ICE.BRENT.M12.D"],
                values={"M1": 93.07, "M12": 77.26, "M1_minus_M2": 1.41, "M1_minus_M12": 15.81, "M1_minus_M12_a_week_earlier": 13.60},
                note="backwardation (front above back)",
                context="M1 minus M12 was 13.60 on 2026-11-10 and is 15.81 now: the curve has steepened over the week.",
                words={"shape": "the Brent curve is in backwardation (front above back)",
                       "move": "the Brent curve has steepened over the week, since 2026-11-10"},
                label_of={"M1": "Brent M1", "M12": "Brent M12", "M1_minus_M2": "Brent M1|M2", "M1_minus_M12": "Brent M1|M12",
                          "M1_minus_M12_a_week_earlier": "Brent M1|M12"},
                date_of={"M1_minus_M12_a_week_earlier": dt.date(2026, 11, 10)})
funds = Reading(key="positioning:wti", title="WTI crude (NYMEX): managed-money positioning", period=dt.date(2026, 11, 10),
                units="contracts", series_ids=["CFTC.WTI.MM_Net"],
                values={"managed_money_net": 151200.0, "net_change_on_week": 12000.0, "net_percentile": 6.8, "percentile_weeks": 156},
                label_of={"managed_money_net": "the managed-money net position in WTI", "net_change_on_week": "the managed-money net position in WTI",
                          "net_percentile": "the managed-money net position in WTI"},
                window_of={"net_change_on_week": "on the week", "net_percentile": "of the last 156 weekly reports"})
arb = Reading(key="arb:us_crude_to_europe", title="US crude to Europe, price indicator", period=D, units="mixed",
              series_ids=["ICE.BRENT.2027-01.D", "NYMEX.WTI.2027-01.D"], values={"score": -0.64, "spread_percentile": 99.6},
              words={"verdict": "the score tilts against US crude exports"}, unit_of={"*": "Dollars per Barrel"},
              label_of={"score": "the arbitrage score", "spread_percentile": "the futures spread"},
              window_of={"spread_percentile": "of that contract pair's own history"})
what_if = Reading(key="scenario:crack:3-2-1:+5:+0:-10", title="What if", period=D, units="Dollars per Barrel", series_ids=["PET.RWTC.D"],
                  values={"crude_change": 5.0, "observed_crack": 38.37, "scenario_crack": 27.68}, hypothetical=True,
                  label_of={"crude_change": "WTI spot", "observed_crack": "the observed 3-2-1 crack spread", "scenario_crack": "the 3-2-1 crack spread"},
                  window_of={"crude_change": "in the scenario"})
TABLE = slots.table([brent, wti_up, flat, tiny, stocks], [gap], [curve, funds, arb, what_if])
NO_ARB = slots.table([brent, wti_up, stocks], [gap], [curve, funds])

B, W, C = "{ICE.BRENT.M1.D.value}", "{PET.RWTC.D.7d.change}", "{curve:brent.M1_minus_M12}"

TYPED = [  # the earlier control's wrong sentences: none can be written any more
    "Freight is at the 96th percentile and has been above the 90th percentile line since 2026-01-05, 110 days.",
    "Freight is at the 96th percentile of 3 years, the highest since 2014.",
    "US crude stocks are 414,417 thousand barrels, a build of 2,000 thousand barrels on the week.",
    "Brent is at 93.07 USD/bbl; gasoil is near 2050 dollars per tonne.",
    "Funds cut their net long in WTI by 12,000 contracts to 151,200, percentile 6.8 over 156 weeks.",
    "Brent spot was 0.62 USD/bbl above WTI spot on 2026-11-11: 87.48 against 88.10.",
    "WTI rose 1.38 USD/bbl on the week, and is up 7 dollars on the month.",
    "Brent was about 4.75 USD/bbl above Dubai and 31% above its level a year ago.",
    "The margin is 0.03 USD/gal.",
    "WTI fell 1.20 USD/bbl on the week to 88.10, still above 86.90.",
    "WTI fell 1.20 USD/bbl on the week to 88.10, more than Brent did.",
    "WTI dropped 1.20 USD/bbl on the week to 88.10 as stocks built.",
    "Freight is at the 96th percentile and has been high since 30 July.",
    "Freight is at the 96th percentile, its highest since Q1.",
    "Freight is at the 96th percentile after 31 days above the line.",
    "Brent M1 is 14.55 below M12.",
    "US crude stocks are 4.47% above the five-year average.",
    "WTI slid 1.20 USD/bbl on the week to 88.10.",
    "WTI tumbled 1.38% on the week.",
    "WTI was unchanged on the week at 88.10 USD/bbl.",
    "WTI trades at a premium of 8.42 USD/bbl to Brent: 84.65 against 93.07.",
    "The Brent curve is not in backwardation: M1 is 93.07 and M12 is 77.26.",
    "The Brent curve is in contango, M1 93.07 against M12 77.26, unlike the backwardation in WTI.",
    "The Brent curve is in backwardation and has flattened over the week.",
    "Tanker freight is at 31.40, percentile 96 of 3 years, which is near the low end of its range.",
    "Brent futures settled at USD97.72 a barrel.",
    "Brent futures settled at c.97.72 a barrel.",
    "Brent futures are near ninety-eight dollars a barrel.",
    "Brent futures are at 93.07 million dollars.",
    "US crude stocks are 414,417 million barrels.",
    "Brent is 93.07 dollars per tonne.",
    "Brent futures settled at 93.07 USD/bbl on 2026-11-18.",
    "Freight is at 31.40, its highest level since 2026.",
    "The last report was released on 2026-10-02.",
    "Brent futures are at 97.72 USD/bbl.",
    "WTI fell 1.20 USD/bbl on the week to 88.10.",
    # the four the old rules accepted, and listed as limits
    "WTI futures are at 93.07 USD/bbl and Brent futures at 88.10.",
    "US crude stocks are 414,417 thousand barrels, a record high, roughly double their ten-year average.",
    "The Brent-WTI spread for the same delivery month is 8.42 USD/bbl and has narrowed sharply.",
    "Freight is at percentile 96, above the line since 2024-02-12; the previous spell ended 2026-07-30.",
]

WRONG = [  # (what is wrong, the template, the table); every one must be rejected
    ("an address no tool returned", "Dubai: {NYMEX.DUBAI.FRONT.D.value}.", TABLE),
    ("a real series with a field that does not exist", "Brent: {ICE.BRENT.M1.D.price}.", TABLE),
    ("an address of the right shape for a lookback the run never asked for", "WTI: {PET.RWTC.D.30d.change}.", TABLE),
    ("a slot with a format specification", "Brent: {ICE.BRENT.M1.D.value:>20}.", TABLE),
    ("a slot with a conversion", "Brent: {ICE.BRENT.M1.D.value!r}.", TABLE),
    ("an attribute walk, as a format string would allow", "Brent: {ICE.BRENT.M1.D.value.__class__}.", TABLE),
    ("a positional field", "Brent: {0}.", TABLE),
    ("an empty slot", "Brent: {}.", TABLE),
    ("a nested brace", "Brent: {{ICE.BRENT.M1.D.value}}.", TABLE),
    ("a doubled brace as an escape", "Brent: {{7*7}}.", TABLE),
    ("an opening brace that never closes", f"Brent: {B[:-1]}.", TABLE),
    ("a closing brace alone", f"Brent: {B} }} and more.", TABLE),
    ("a filter that would let the model choose the word", "WTI: {PET.RWTC.D.7d.change|fell}.", TABLE),
    ("a space inside the address", "Brent: { ICE.BRENT.M1.D.value }.", TABLE),
    ("a figure typed beside a slot", f"Brent: {B}, about 4.75 over Dubai.", TABLE),
    ("a contract code typed as a name", f"The front of the curve, M1: {C}.", TABLE),
    ("a ratio typed as a name", f"The 3-2-1 margin is firm, and {B}.", TABLE),
    ("a year", f"The widest since 2022: {C}.", TABLE),
    ("a full-width digit", f"About ９ dollars wider: {C}.", TABLE),
    ("a superscript digit", f"Squared² for effect: {C}.", TABLE),
    ("a vulgar fraction", f"Up by ½ on the day: {C}.", TABLE),
    ("a number in words", f"Nearly ninety-eight dollars: {B}.", TABLE),
    ("a window in words", f"Against its five-year norm: {B}.", TABLE),
    ("a multiple in words", f"Stocks have doubled: {B}.", TABLE),
    ("a scale word after a slot", f"Stocks: {B} million.", TABLE),
    ("a dollar in words", f"A dollar more than last week: {B}.", TABLE),
    ("a month", f"The widest since July: {C}.", TABLE),
    ("a weekday", f"As of Tuesday: {B}.", TABLE),
    ("today in words", f"Today: {B}.", TABLE),
    ("this morning", f"As of this morning: {B}.", TABLE),
    ("a change verb in the model's own word", f"Brent fell: {B}.", TABLE),
    ("a change verb the old lists missed, now listed", f"Brent tumbled: {B}.", TABLE),
    ("a comparative", f"Brent is higher: {B}.", TABLE),
    ("a curve shape in the model's own word", f"The curve is in contango: {C}.", TABLE),
    ("a trader's synonym for a curve shape", f"The curve is inverted: {C}.", TABLE),
    ("a scorecard verdict in the model's own word", f"The market is tight: {C}.", TABLE),
    ("an arbitrage verdict in the model's own word", "The arbitrage is open: {arb:us_crude_to_europe.score}.", TABLE),
    ("a sign typed before a slot", f"Brent: -{B}.", TABLE),
    ("a slot glued to a letter", f"Brent: {B}s.", TABLE),
    ("a letter glued before a slot", f"Brent: x{B}.", TABLE),
    ("two figures joined by a slash", f"The ratio: {B} / {C}.", TABLE),
    ("two figures joined by a dash", f"The range: {B} - {C}.", TABLE),
    ("two figures with nothing between them", f"Brent: {B}{C}.", TABLE),
    ("two figures joined by a plus sign", f"Together: {B} + {C}.", TABLE),
    ("a percent sign glued after a slot", f"Brent: {B}%.", TABLE),
]

RIGHT = [  # templates that must pass
    (f"Brent is firm: {B}.", TABLE),
    (f"{B}. {W}.", TABLE),
    (f"Yes: {{curve:brent.shape}}, with {C}. {{curve:brent.move}}.", TABLE),
    (f"The prices side by side: {B}, and {W}.", TABLE),
    ("Funds are cautious: {positioning:wti.managed_money_net}; {positioning:wti.net_percentile}.", TABLE),
    (f"The front of the curve is well bid ({C}).", TABLE),
    ("Brent spot against WTI spot: {PET.RBRTE.D-minus-PET.RWTC.D.gap}, and {PET.RBRTE.D-minus-PET.RWTC.D.percentile}.", TABLE),
    ("Not on this indicator: {arb:us_crude_to_europe.verdict}, with {arb:us_crude_to_europe.score}.", TABLE),
    ("Open interest is a term a positioning answer may use when no arbitrage was read: {positioning:wti.managed_money_net}.", NO_ARB),
    ("If the assumed changes happened: {scenario:crack:3-2-1:+5:+0:-10.scenario_crack}, against {scenario:crack:3-2-1:+5:+0:-10.observed_crack}.", TABLE),
    ("Stocks in the unit asked for: {PET.WCESTUS1.W.million_barrels}.", TABLE),
    ("The data does not hold a carbon price.", TABLE),
    (f"The week-earlier reading for comparison: {{curve:brent.M1_minus_M12_a_week_earlier}}; now {C}.", TABLE),
    ("{curve:brent.context}", TABLE),
    (f"{B} {W}", TABLE),
    (f"The curve \u2014 {C} \u2014 is steep.", TABLE),
]

WRITES = [  # (template, what the page prints)
    (f"Brent: {B}.", "Brent: Brent front-month future at 93.07 dollars per barrel (2026-11-17)."),
    (f"{W}.", "WTI spot up 1.20 dollars per barrel (1.38%) over 7 days, from 86.90 dollars per barrel on 2026-11-10 (2026-11-17)."),
    (f"{B}, and {W}.",  # one date, printed once
     "Brent front-month future at 93.07 dollars per barrel (2026-11-17), and WTI spot up 1.20 dollars per barrel (1.38%) over 7 days, "
     "from 86.90 dollars per barrel on 2026-11-10."),
    (f"Now {C}; before, {{curve:brent.M1_minus_M12_a_week_earlier}}; and again {C}.",  # the date is printed whenever it changes
     "Now Brent M1 15.81 dollars per barrel above M12 (2026-11-17); before, Brent M1 13.60 dollars per barrel above M12 (2026-11-10); "
     "and again Brent M1 15.81 dollars per barrel above M12 (2026-11-17)."),
    ("{curve:brent.shape}. {curve:brent.move}.",  # a statement that opens a sentence is capitalised
     "The Brent curve is in backwardation (front above back). The Brent curve has steepened over the week, since 2026-11-10."),
    ("{X.FLAT.D.7d.change}.", "A flat series unchanged over 7 days, from 50.00 dollars per barrel on 2026-11-10 (2026-11-17)."),
    ("{X.TINY.D.7d.change}.", "A (braced) series almost unchanged over 7 days, from 50.00 dollars per barrel on 2026-11-10 (2026-11-17)."),
    ("{PET.RBRTE.D-minus-PET.RWTC.D.gap}.", "Brent spot 0.62 dollars per barrel below WTI spot (2026-11-11)."),
    ("{PET.WCESTUS1.W.value}; {PET.WCESTUS1.W.million_barrels}.",
     "US commercial crude stocks at 414,417 thousand barrels (2026-11-13); US commercial crude stocks at 414.42 million barrels."),
    ("{positioning:wti.net_change_on_week}; {positioning:wti.net_percentile}.",
     "The managed-money net position in WTI up 12,000 contracts on the week (2026-11-10); the managed-money net position in WTI at the 7th "
     "percentile of the last 156 weekly reports."),
    ("{arb:us_crude_to_europe.spread_percentile}.", "The futures spread above the 99th percentile of that contract pair's own history (2026-11-17)."),
    ("{arb:us_crude_to_europe.score}.", "The arbitrage score at -0.64 on a scale from -2 to +2 (2026-11-17)."),
    ("{scenario:crack:3-2-1:+5:+0:-10.scenario_crack}.", "The 3-2-1 crack spread at 27.68 dollars per barrel (hypothetical) (2026-11-17)."),
    ("Unknown stays visible: {NO.SUCH.value}.", "Unknown stays visible: {NO.SUCH.value}."),
    # the model wrote the slot's own subject: it is printed once
    (f"Brent front-month future is {B}.", "Brent front-month future is at 93.07 dollars per barrel (2026-11-17)."),
    (f"The Brent front-month future stood at {B}.", "The Brent front-month future stood at 93.07 dollars per barrel (2026-11-17)."),
    (f"WTI spot is {W}.", "WTI spot is up 1.20 dollars per barrel (1.38%) over 7 days, from 86.90 dollars per barrel on 2026-11-10 (2026-11-17)."),
    # another noun is not the slot's subject: nothing is left out, and the contradiction shows
    (f"WTI spot is {B}.", "WTI spot is Brent front-month future at 93.07 dollars per barrel (2026-11-17)."),
    # a code sentence inside the model's sentence, and its own full stop
    (f"Brent is firm, and {{curve:brent.context}}.", "Brent is firm, and M1 minus M12 was 13.60 on 2026-11-10 and is 15.81 now: the curve has steepened over the week."),
]

LIMIT = [  # wrong, and still accepted: the words between slots are the model's
    ("the wrong noun in the model's words: it now reads as a contradiction, and is not refused", f"WTI is weak: {B}."),
    ("a claim in words alone", f"A record, and well beyond anything seen before: {B}."),
    ("a cause the data cannot show", f"Because of the cartel's decision: {B}."),
    ("a negation in front of a slot", f"It is not the case that {B}."),
    ("a change verb that is on no list", f"Brent slid: {B}."),
    ("relative time in words", f"This week and for the rest of the year: {B}."),
    ("a dictated sentence shorter than the echo rule's twelve words", f"Analysts expect a rally by spring. {B}."),
]


def tampered() -> int:
    """A true answer, altered after the fact: verify() must refuse every alteration. Returns expectations not met."""
    from es_agent import readings
    from es_agent.agent import Deps, compose
    from es_agent.models import Draft
    from es_agent.sources import FixtureSource
    from es_agent.verify import verify

    source = FixtureSource("fixtures/series.json")
    os.environ.setdefault("LIBRARIAN_TODAY", source.as_of)
    reading = readings.compute(source, "curve:brent")
    answer, problems = compose(Deps(source=source, readings={reading.key: reading}),
                               Draft(summary="{curve:brent.shape}, with {curve:brent.M1_minus_M2}."))
    failed = 0
    if problems or verify(answer, source):
        print(f"REFUSED   the untouched answer: {problems or verify(answer, source)}")
        failed += 1

    def altered(**changes):
        return answer.model_copy(deep=True, update=changes)

    value = altered()
    value.readings[0].values["M1_minus_M2"] += 1.0
    digit = next(ch for ch in answer.summary if ch.isdigit())
    cases = [
        ("a value in a table", value, "reading curve:brent differs"),
        ("a character of the summary", altered(summary=answer.summary.replace(digit, str((int(digit) + 1) % 10), 1)), "summary: differs"),
        ("a caveat that code did not write", altered(caveats=answer.caveats + ["Analysts expect a rally by spring."]), "caveats:"),
        ("a figure typed into the template", altered(template=answer.template + " About 4.75 over Dubai."), "summary: digit"),
    ]
    for label, doctored, expect in cases:
        found = [p for p in verify(doctored, source) if p.startswith(expect)]
        print(f"{'refused  ' if found else 'ACCEPTED '} tampered: {label}")
        failed += not found
    return failed


def main() -> int:
    failed = 0
    for text in TYPED:
        found = slots.template_problems(text, TABLE)
        if not found:
            print(f"ACCEPTED a typed sentence: {text}")
        failed += not found
    if not failed:
        print(f"rejected  all {len(TYPED)} typed sentences of the earlier control")
    for label, template, table in WRONG:
        found = slots.template_problems(template, table)
        print(f"{'rejected ' if found else 'ACCEPTED '} {label}")
        failed += not found
    for template, table in RIGHT:
        found = slots.template_problems(template, table)
        if found:
            print(f"REJECTED a correct template: {template}\n          -> {found}")
        failed += bool(found)
    for template, expected in WRITES:
        got = slots.render(template, TABLE)[0]
        if got != expected:
            print(f"WROTE     {got!r}\n expected {expected!r}")
        failed += got != expected
    for label, template in LIMIT:
        found = slots.template_problems(template, TABLE)
        print(f"{'now caught: move it to WRONG' if found else 'limit    '} {label}")
        failed += bool(found)
    ends = {0.4: "below the 1st percentile", 1.0: "at the 1st percentile", 11.2: "at the 11th percentile", 12.0: "at the 12th percentile",
            13.4: "at the 13th percentile", 21.6: "at the 22nd percentile", 43.0: "at the 43rd percentile", 99.0: "at the 99th percentile",
            99.6: "above the 99th percentile", 100.0: "at the highest of the window, the 100th percentile"}
    for v, expected in ends.items():
        if slots.percentile(v) != expected:
            print(f"WROTE     percentile {v}: {slots.percentile(v)!r}, expected {expected!r}")
            failed += 1
    failed += tampered()
    print(f"{len(TYPED)} typed sentences, {len(WRONG)} wrong templates, {len(RIGHT)} right templates, {len(WRITES)} renderings, "
          f"4 tampered answers, {len(LIMIT)} known limits; {failed} expectation(s) not met")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
