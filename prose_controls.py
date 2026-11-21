"""Control for the prose checks: answers whose tables are true and whose sentences are wrong.

    python prose_controls.py        # exit 1 if any expectation below is not met

The eval suite's control run plants a wrong number in the facts. This plants errors in the
wording, where the tables cannot help: a wrong date, a flipped sign, a number in a caveat. Each
case says what must happen. No model, no data, no cost; it runs in CI and in the release gate.

The first eleven wrong answers came from an adversarial review of the live service on 18 Nov 2026
(a second Claude session given the job of breaking it), and more from its second, held-out set.
Four kinds are still accepted and are kept here marked LIMIT, so the gap stays visible: the checks
cannot tell that two true values or dates have been attached to the wrong nouns, or judge a claim
made in words alone.
"""

from __future__ import annotations

import datetime as dt
import json
import sys

from es_agent import metrics
from es_agent.models import DeskAnswer, Reading, SeriesFact, Spread

D = dt.date(2026, 11, 17)
brent = SeriesFact(series_id="ICE.BRENT.M1.D", name="Brent futures M1", units="USD/bbl", latest_period=D, latest_value=93.07)
wti = SeriesFact(series_id="NYMEX.WTI.M1.D", name="WTI futures M1", units="USD/bbl", latest_period=D, latest_value=88.10)
wti_up = SeriesFact(series_id="PET.RWTC.D", name="WTI spot", units="USD/bbl", latest_period=D, latest_value=88.10,
                    lookback_days=7, base_period=dt.date(2026, 11, 10), base_value=86.90, change_abs=1.20, change_pct=1.380898)
stocks = SeriesFact(series_id="PET.WCESTUS1.W", name="US ending stocks excluding SPR of crude oil", units="Thousand Barrels",
                    latest_period=dt.date(2026, 11, 13), latest_value=414417.0)
margin = SeriesFact(series_id="X.GAL.D", name="A margin", units="USD/gal", latest_period=D, latest_value=0.02)
freight = Reading(key="percentile:SHIP.BWET.D:3", title="Tanker freight proxy against its last 3 years", period=D, units="USD",
                  series_ids=["SHIP.BWET.D"], values={"latest": 31.4, "percentile": 96.0, "years": 3, "spell_days": 110},
                  context="It has been above the 90th percentile line (25.10) since 2026-07-30, 110 days, allowing for brief dips back.")
funds = Reading(key="positioning:wti", title="WTI crude (NYMEX): managed-money positioning", period=dt.date(2026, 11, 10),
                units="contracts", series_ids=["CFTC.WTI.MM_Net"],
                values={"managed_money_net": 151200.0, "net_change_on_week": 12000.0, "net_percentile": 6.8, "percentile_weeks": 156},
                # as readings.default_units gives them when a tool keeps the reading
                value_units={"managed_money_net": "contracts", "net_change_on_week": "contracts"})
gap = Spread(series_a="PET.RBRTE.D", name_a="Brent spot", series_b="PET.RWTC.D", name_b="WTI spot", units="USD/bbl",
             period=dt.date(2026, 11, 11), value_a=87.48, value_b=88.10, spread=-0.62)
brent_curve = Reading(key="curve:brent", title="Brent futures curve", period=D, units="USD/bbl",
                    series_ids=["ICE.BRENT.M1.D", "ICE.BRENT.M12.D"],
                    values={"M1": 93.07, "M12": 77.26, "M1_minus_M2": 1.41, "M1_minus_M12": 15.81, "M1_minus_M12_a_week_earlier": 13.60},
                    note="backwardation (front above back)",
                    context="M1 minus M12 was 13.60 on 2026-11-10 and is 15.81 now: the curve has steepened over the week.")
fut = Spread(series_a="ICE.BRENT.2027-01.D", name_a="Brent 2027-01", series_b="NYMEX.WTI.2027-01.D", name_b="WTI 2027-01",
             units="USD/bbl", period=D, value_a=93.07, value_b=84.65, spread=8.42,
             extras={"percentile": 96.4, "percentile_years": 3, "spell_days": 70, "days_since_previous_spell": 117},
             context="The spread has been above the 90th percentile line (6.69) since 2026-09-08, 70 days, allowing for brief dips back.")
curve = Reading(key="evidence:x", title="Curves", period=D, units="USD/bbl", series_ids=["ICE.BRENT.M1.D"],
                values={"brent_M1_minus_M12": 14.55, "us_stocks_vs_5y_pct": -4.47})

# A reading the EnergyScope server computed (21 Nov 2026): its text gives no numbers; its values do.
report = Reading(key="report:eia_weekly", title="US weekly petroleum, standing report as of 2026-11-17", period=D,
                 units="Dollars per Gallon; Million Barrels; Thousand Barrels", series_ids=["PET.WGTSTUS1.W"],
                 values={"Total gasoline.value": 215949.0, "Total gasoline.value_in_million_barrels": 215.949,
                         "Regular gasoline.wow": -0.19, "Regular gasoline.value": 3.81},
                 context="Lede: Regular gasoline fell by 0.19, to 3.81 Dollars per Gallon, a 2.2-sigma move.",
                 request={"tool": "report", "action": "report", "body": {"preset": "eia_weekly"}},
                 # as engine._report writes them: each row in its own unit, the shown figures in theirs
                 value_units={"Total gasoline.value": "Thousand Barrels", "Total gasoline.value_in_million_barrels": "Million Barrels",
                              "Regular gasoline.wow": "Dollars per Gallon", "Regular gasoline.value": "Dollars per Gallon"})
# Round 3 of the adversary: hyphenated terms of a server text, and a snapshot metric that is itself a change
signals_r = Reading(key="signals:live", title="The server's signals and contradictions, live", period=D, units="as each metric",
                    series_ids=[], values={"metric.opec_call_qoq_change": 0.546, "metric.m1_m12": -15.26, "steep_backwardation.threshold": -10.0},
                    context=("Signal firing: steep_backwardation (elevated): 12-month curve, M12-M1 of -15.26 is below the -10 "
                             "threshold. Lede: crude imports moved 1.8-sigma."),
                    request={"tool": "signals", "action": "derived_signals", "body": {}})
seasonal3 = Reading(key="seasonal:PET.WCESTUS1.W:3", title="US crude stocks: latest against the same time of year, previous 3 years",
                    period=dt.date(2026, 11, 13), units="Thousand Barrels", series_ids=["PET.WCESTUS1.W"],
                    values={"current_value": 417797.0, "seasonal_avg": 434167.0, "lookback_years": 3.0},
                    context="Same week (week=46) in each of 3 earlier years.",
                    request={"tool": "seasonal", "action": "seasonal", "body": {"series": "PET.WCESTUS1.W", "lookback_years": 3}})

WRONG = [  # (what is wrong, the answer); every one must be rejected
    ("a date that differs from the code-written history sentence",
     dict(readings=[freight], summary="Freight is at the 96th percentile and has been above the 90th percentile line since 2026-01-05, 110 days.")),
    ("an invented year",
     dict(readings=[freight], summary="Freight is at the 96th percentile of 3 years, the highest since 2014.")),
    ("an invented quantity written with a thousands separator, which used to read as a year",
     dict(facts=[stocks], summary="US crude stocks are 414,417 thousand barrels, a build of 2,000 thousand barrels on the week.")),
    ("an invented price in the range of years",
     dict(facts=[brent], summary="Brent is at 93.07 USD/bbl; gasoil is near 2050 dollars per tonne.")),
    ("a positioning change given the opposite direction",
     dict(readings=[funds], summary="Funds cut their net long in WTI by 12,000 contracts to 151,200, percentile 6.8 over 156 weeks.")),
    ("a spread with its sign flipped",
     dict(spreads=[gap], summary="Brent spot was 0.62 USD/bbl above WTI spot on 2026-11-11: 87.48 against 88.10.")),
    ("a percentage quoted as dollars, and a count of days quoted as a price move",
     dict(facts=[wti_up], summary="WTI rose 1.38 USD/bbl on the week, and is up 7 dollars on the month.")),
    ("a fabricated number in a caveat",
     dict(facts=[brent], summary="Brent futures are at 93.07 USD/bbl.",
          caveats=["Brent was about 4.75 USD/bbl above Dubai and 31% above its level a year ago."])),
    ("a small value off by half",
     dict(facts=[margin], summary="The margin is 0.03 USD/gal.")),
    ("a fall claimed for a rise, with a level word elsewhere in the sentence",
     dict(facts=[wti_up], summary="WTI fell 1.20 USD/bbl on the week to 88.10, still above 86.90.")),
    ("a fall claimed for a rise, with 'more' elsewhere",
     dict(facts=[wti_up], summary="WTI fell 1.20 USD/bbl on the week to 88.10, more than Brent did.")),
    ("a fall claimed for a rise, with a build mentioned",
     dict(facts=[wti_up], summary="WTI dropped 1.20 USD/bbl on the week to 88.10 as stocks built.")),
    ("a date written in words",
     dict(readings=[freight], summary="Freight is at the 96th percentile and has been high since 30 July.")),
    ("a quarter",
     dict(readings=[freight], summary="Freight is at the 96th percentile, its highest since Q1.")),
    ("a count of lines that is not a count",
     dict(readings=[freight], summary="Freight is at the 96th percentile after 31 days above the line.")),
    ("a curve gap pointing the wrong way",
     dict(readings=[curve], summary="Brent M1 is 14.55 below M12.")),
    ("stocks on the wrong side of their average",
     dict(readings=[curve], summary="US crude stocks are 4.47% above the five-year average.")),
    ("a verb that is on no list (slid), for a rise",
     dict(facts=[wti_up], summary="WTI slid 1.20 USD/bbl on the week to 88.10.")),
    ("another unlisted verb, on the percentage",
     dict(facts=[wti_up], summary="WTI tumbled 1.38% on the week.")),
    ("'unchanged' for a rise",
     dict(facts=[wti_up], summary="WTI was unchanged on the week at 88.10 USD/bbl.")),
    ("a premium given to the wrong side",
     dict(spreads=[fut], summary="WTI trades at a premium of 8.42 USD/bbl to Brent: 84.65 against 93.07.")),
    ("a curve's shape denied",
     dict(readings=[brent_curve], summary="The Brent curve is not in backwardation: M1 is 93.07 and M12 is 77.26.")),
    ("the wrong shape, with the right word used about another market",
     dict(readings=[brent_curve], summary="The Brent curve is in contango, M1 93.07 against M12 77.26, unlike the backwardation in WTI.")),
    ("flattened where the reading says steepened",
     dict(readings=[brent_curve], summary="The Brent curve is in backwardation and has flattened over the week.")),
    ("a high percentile called low",
     dict(readings=[freight], summary="Tanker freight is at 31.40, percentile 96 of 3 years, which is near the low end of its range.")),
    ("a fabricated number glued to a currency code",
     dict(facts=[brent], summary="Brent futures settled at USD97.72 a barrel.")),
    ("a fabricated number behind an abbreviation",
     dict(facts=[brent], summary="Brent futures settled at c.97.72 a barrel.")),
    ("a number spelled out",
     dict(facts=[brent], summary="Brent futures are near ninety-eight dollars a barrel.")),
    ("a true number with an invented scale",
     dict(facts=[brent], summary="Brent futures are at 93.07 million dollars.")),
    ("a true number in the wrong scale",
     dict(facts=[stocks], summary="US crude stocks are 414,417 million barrels.")),
    ("a true number in the wrong unit",
     dict(facts=[brent], summary="Brent is 93.07 dollars per tonne.")),
    ("a true value given today's date",
     dict(facts=[brent], summary="Brent futures settled at 93.07 USD/bbl on 2026-11-18.")),
    ("a bare year that is the year of a returned date",
     dict(readings=[freight], summary="Freight is at 31.40, its highest level since 2026.")),
    ("a wrong date in a caveat",
     dict(facts=[brent], summary="Brent futures are at 93.07 USD/bbl.", caveats=["The last report was released on 2026-10-02."])),
    ("a price misquoted by 5%",
     dict(facts=[brent], summary="Brent futures are at 97.72 USD/bbl.")),
    ("falling words only, when every change is a rise",
     dict(facts=[wti_up], summary="WTI fell 1.20 USD/bbl on the week to 88.10.")),
    # the adversary, 21 Nov 2026
    ("a number from a reading's text given a unit no cited series is in (the text's numbers took no unit test)",
     dict(readings=[freight], summary="Freight is at the 96th percentile, above its line of 25.10 million barrels.")),
    ("a ten-year average no reading computed", dict(facts=[stocks],
     summary="US crude stocks are 414,417 thousand barrels, a record high, roughly double their ten-year average.")),
    ("a three-year seasonal average called five-year", dict(readings=[seasonal3],
     summary="US crude stocks are 417,797 thousand barrels against a five-year average of 434,167.")),
    ("a three-year seasonal average called ten-year", dict(readings=[seasonal3],
     summary="Stocks of 417,797 thousand barrels are below the ten-year average of 434,167.")),
    ("a number that stands only in a server reading's text", dict(readings=[report],
     summary="Regular gasoline moved 2.2 sigma to 3.81 dollars per gallon.")),
    # A true number written with another true number's unit (David, 21 Nov 2026: "we should try to fix this").
    # Until then each was true somewhere in the answer and the sentence passed; a number now matches a value in the
    # unit it is written with.
    ("a report's price change written as a stock in million barrels",
     dict(readings=[report], summary="Gasoline stocks were 0.19 million barrels on the week.")),
    ("a stock written in dollars a gallon", dict(readings=[report], summary="Gasoline cost 215.9 dollars a gallon.")),
    ("a stock in thousand barrels written as million barrels", dict(facts=[stocks], summary="US crude stocks are 414,417 million barrels.")),
    ("a price written in thousand barrels", dict(facts=[wti_up], summary="WTI spot is 88.10 thousand barrels.")),
    ("a fund position in contracts written in dollars", dict(readings=[funds], summary="Managed money is net long $151,200.")),
    ("a percent written for a price", dict(facts=[wti], summary="WTI futures are at 88.10%.")),
    # round 3 of the adversary
    ("the 8 of a 1.8-sigma move written as a stock change (a digit of a decimal is not a name)",
     dict(readings=[signals_r], summary="US crude stocks fell by 8 million barrels on the week.")),
    ("the 12 of a 12-month curve written as a price (a hyphen term's number, written without its hyphen)",
     dict(readings=[signals_r], summary="Brent rose $12 a barrel.")),
    ("a snapshot metric that rose, said to have fell",
     dict(readings=[signals_r], summary="The opec call qoq change fell by 0.55.")),
]

RIGHT = [  # correct prose that the rules must not reject
    dict(facts=[wti_up], summary="WTI rose 1.20 USD/bbl (1.38%) over 7 days to 88.10 on 2026-11-17, from 86.90 on 2026-11-10."),
    dict(facts=[wti_up], summary="WTI was 88.10 USD/bbl on 2026-11-17, up 1.20 from 86.90, still below Brent.", caveats=["One week of data only."]),
    dict(spreads=[gap], summary="Brent spot was 0.62 USD/bbl below WTI spot on 2026-11-11: 87.48 against 88.10."),
    dict(spreads=[gap], summary="WTI spot was 0.62 USD/bbl above Brent spot on 2026-11-11."),
    dict(readings=[funds], summary="Funds added 12,000 contracts on the week, taking their net long to 151,200, percentile 6.8 of 156 weeks."),
    dict(readings=[freight], summary="Freight is at the 96th percentile of 3 years and has been above the 90th percentile line since 2026-07-30, 110 days."),
    dict(readings=[curve], summary="Brent M1 is 14.55 above M12, and US crude stocks are 4.47% below the five-year average."),
    dict(readings=[curve], summary="M12 is 14.55 below M1 on the Brent curve."),
    dict(facts=[stocks], summary="US crude stocks were 414,417 thousand barrels on 2026-11-13."),
    dict(facts=[wti_up], summary="The change over 7 days was +1.20 USD/bbl, to 88.10."),
    dict(facts=[stocks, brent], summary="No spread is given: one is a price in dollars per barrel and the other is reported in thousand barrels."),
    dict(spreads=[fut], summary="Brent trades at a premium of 8.42 USD/bbl to WTI for 2027-01 delivery: 93.07 against 84.65."),
    dict(spreads=[fut], summary="The spread is 8.42 USD/bbl, percentile 96.4 of 3 years; the previous spell above the line ended 117 days earlier."),
    dict(readings=[brent_curve], summary="The Brent curve is in backwardation, not contango: M1 93.07 against M12 77.26, and it has steepened over the week."),
    dict(readings=[freight], summary="Tanker freight is at 31.40, percentile 96 of 3 years, near the high end of its range."),
    dict(readings=[report], summary="Regular gasoline fell 0.19 to 3.81 dollars per gallon; total gasoline stocks are 215.9 million barrels."),
    dict(readings=[seasonal3], summary="US crude stocks are 417,797 thousand barrels against a three-year average of 434,167."),
    dict(readings=[seasonal3], summary="Over 36 months of the same week, the average was 434,167 thousand barrels."),
    # the unit rule must let each number keep its own unit
    dict(facts=[stocks], summary="US crude stocks are 414,417 thousand barrels."),
    dict(facts=[wti_up], summary="WTI spot rose 1.20 dollars a barrel, or 1.38%, to $88.10 per barrel."),
    dict(readings=[funds], summary="Managed money is net long 151,200 contracts, at the 6.8th percentile."),
    dict(readings=[signals_r], summary="The 12-month curve, M12 minus M1, is -15.26, below the -10 threshold; the OPEC call QoQ change is 0.55."),
]

LIMIT = [  # wrong, and still accepted: what the checks cannot see
    ("two true values attached to the wrong nouns",
     dict(facts=[brent, wti], summary="WTI futures are at 93.07 USD/bbl and Brent futures at 88.10.")),
    # (until 21 Nov 2026 this case also said "their ten-year average"; the window rule now rejects that phrase, so it
    # is a wrong answer below and the limit keeps the claims that stay in words alone)
    ("claims made in words alone",
     dict(facts=[stocks], summary="US crude stocks are 414,417 thousand barrels, a record high, roughly double their usual level.")),
    ("a change claimed in words where no earlier value was returned",
     dict(spreads=[fut], summary="The Brent-WTI spread for the same delivery month is 8.42 USD/bbl and has narrowed sharply.")),
    ("two true dates attached to the wrong events",
     dict(readings=[Reading(key="percentile:X:3", title="Freight", period=D, units="USD", series_ids=["SHIP.BWET.D"],
                            values={"latest": 31.4, "percentile": 96.0},
                            context="Above the line since 2026-07-30; the previous spell ended 2024-02-12.")],
          summary="Freight is at percentile 96, above the line since 2024-02-12; the previous spell ended 2026-07-30.")),
    # windows in words the rule does not read (the adversary, round 2): no number in them, or one the answer has
    ("a three-year average called the average of the past decade",
     dict(readings=[seasonal3], summary="Stocks of 417,797 thousand barrels are below the average of the past decade, 434,167.")),
    ("with a three-year and a five-year reading cited, the five-year window given to the three-year figure",
     dict(readings=[seasonal3, seasonal3.model_copy(update={"key": "seasonal:PET.WCESTUS1.W:5",
                                                            "values": {"current_value": 417797.0, "seasonal_avg": 433637.2, "lookback_years": 5.0}})],
          summary="Stocks of 417,797 thousand barrels are below their five-year average of 434,167.")),
    ("stocks including the SPR, where the series excludes it",
     dict(facts=[stocks], summary="US crude stocks including the SPR are 414,417 thousand barrels.")),
]


def problems(kw: dict) -> list[str]:
    a = DeskAnswer(**{"facts": [], **kw})
    a.summary = metrics.tidy(a.summary)
    return metrics.untraceable_numbers(a) + metrics.direction_problems(a)


def main() -> int:
    failed = 0
    for label, kw in WRONG:
        found = problems(kw)
        print(f"{'rejected ' if found else 'ACCEPTED '} {label}")
        failed += not found
    for kw in RIGHT:
        found = problems(kw)
        if found:
            print(f"REJECTED a correct answer: {kw['summary']}\n          -> {found}")
        failed += bool(found)
    for label, kw in LIMIT:
        found = problems(kw)
        print(f"{'now caught: move it to WRONG' if found else 'limit    '} {label}")
        failed += bool(found)
    with open("results/golden.json", encoding="utf-8") as f:
        golden = json.load(f)
    for name, body in golden.items():
        a = DeskAnswer(**body)
        found = metrics.untraceable_numbers(a) + metrics.direction_problems(a)
        if found:
            print(f"REJECTED the recorded answer {name}: {found}")
        failed += bool(found)
    print(f"{len(WRONG)} wrong answers, {len(RIGHT)} right answers, {len(golden)} recorded answers, {len(LIMIT)} known limits; "
          f"{failed} expectation(s) not met")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
