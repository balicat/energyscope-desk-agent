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
# The five-year seasonal reading as engine.seasonal writes it, units and all (the adversary's P11, 23 Nov 2026)
_by_year = {"2021": 434020.0, "2022": 431665.0, "2023": 448054.0, "2024": 430292.0, "2025": 424155.0}
seasonal5 = Reading(key="seasonal:PET.WCESTUS1.W:5", title="US crude stocks: latest against the same time of year, previous 5 years",
                    period=dt.date(2026, 11, 13), units="Thousand Barrels", series_ids=["PET.WCESTUS1.W"],
                    values={"current_value": 417797.0, "seasonal_avg": 433637.2, "lookback_years": 5.0,
                            **{f"history_by_year.{y}": v for y, v in _by_year.items()}},
                    value_units={"current_value": "Thousand Barrels", "seasonal_avg": "Thousand Barrels",
                                 **{f"history_by_year.{y}": "Thousand Barrels" for y in _by_year}},
                    context="Same week (week=46) in each of 5 earlier years: " + ", ".join(f"{y} {v:,.0f}" for y, v in _by_year.items()) + ".",
                    request={"tool": "seasonal", "action": "seasonal", "body": {"series": "PET.WCESTUS1.W", "lookback_years": 5}})
# The settings sweep of 24 Nov 2026: the true sentences sent back most often, with the readings as readings.watch,
# readings.evidence and get_change write them
watch = Reading(key="watch:week", title="What to watch: flags from prices, stocks, the curve and positioning over a week",
                period=dt.date(2026, 11, 23), units="each item in its own units", series_ids=["SHIP.BWET.D", "CFTC.NG.MM_Net"],
                values={"Tanker freight proxy: change": 121.62, "Tanker freight proxy: z-score": 2.13,
                        "Natural gas (NYMEX): fund net percentile": 1.9, "flags": 2.0},
                context=("Flags, in no order of importance: Tanker freight proxy moved +121.62 USD (z-score +2.13, to 2026-11-23); "
                         "funds are stretched short in Natural gas (NYMEX) (net position at the 1.9 percentile of three years, "
                         "report of 2026-11-17)."))
evidence = Reading(key="evidence:crude_tightness", title="Evidence for and against: crude tightness", period=dt.date(2026, 11, 23),
                   units="percent, dollars per barrel, thousand barrels, z-scores (stated on each line)", series_ids=["PET.WCESTUS1.W"],
                   values={"us_stocks_4w_change": 5280.0, "us_stocks_4w_usual_change": 5492.2, "us_stocks_4w_gap_pct": 0.05},
                   context=("US crude stocks over four weeks: a build of 5,280 thousand barrels against a usual build of 5,492 "
                            "for the time of year, a gap of 0.05% of stocks (2026-11-13; tight below -2%, loose above 2%) [neutral]."))
stocks_yoy = SeriesFact(series_id="PET.WCESTUS1.W", name="US ending stocks excluding SPR of crude oil", units="Thousand Barrels",
                        latest_period=dt.date(2026, 11, 13), latest_value=417797.0, lookback_days=365,
                        base_period=dt.date(2025, 11, 7), base_value=427581.0, change_abs=-9784.0, change_pct=-2.288176,
                        also={"million_barrels": 417.797})
# the same evidence line on a week when the usual four weeks are a draw
evidence_draw = evidence.model_copy(update={
    "values": {"us_stocks_4w_change": 5280.0, "us_stocks_4w_usual_change": -5492.2, "us_stocks_4w_gap_pct": 2.56},
    "context": "US crude stocks over four weeks: a build of 5,280 thousand barrels against a usual draw of 5,492 for the time of year."})
imports = SeriesFact(series_id="PET.WCRIMUS2.W", name="US crude imports", units="Thousand Barrels per Day",
                     latest_period=dt.date(2026, 11, 13), latest_value=5576.0, also={"million_barrels_per_day": 5.576})
# a server text whose parameter is a decimal (the adversary's 3c, 24 Nov 2026: x=3.41 used to name 3)
signals_z = Reading(key="signals:z", title="The server's signals, live", period=D, units="as each metric", series_ids=[],
                    values={"metric.crack_z": 3.81}, context="Signal firing: crack_extreme: crack_z=3.81 is above its threshold.",
                    request={"tool": "signals", "action": "derived_signals", "body": {}})
corr = Reading(key="rolling_correlation:PET.RBRTE.D,PET.RWTC.D:3", title="Brent and WTI spot: rolling correlation, last 3 years",
               period=D, units="correlation", series_ids=["PET.RBRTE.D", "PET.RWTC.D"],
               values={"latest": 0.912, "mean": 0.874, "years": 3.0},
               request={"tool": "rolling_correlation", "action": "rolling_correlation", "body": {}})

# The adversary's L1 and L2 (24 Nov 2026): numbers of a reading's keys, ids and titles passed as bare "names", and a
# currency written before a number with a space was not read as money. A percentile reading like the suite's
# henry_hub_percentile, a deferred WTI contract's, and the S&P 500's.
hh_pct = Reading(key="percentile:NG.RNGWHHD.D:5", title="Henry Hub spot against its last 5 years", period=D, units="USD/MMBtu",
                 series_ids=["NG.RNGWHHD.D"], values={"latest": 4.21, "percentile": 65.93, "p5": 2.1, "p25": 2.8,
                                                      "p75": 4.6, "p95": 6.9, "years": 5.0})
wti27 = Reading(key="percentile:NYMEX.WTI.2027-01.D:1", title="WTI futures, a deferred contract, against its last year",
                period=D, units="USD/bbl", series_ids=["NYMEX.WTI.2027-01.D"], values={"latest": 71.2, "percentile": 40.5, "years": 1.0})
spx = Reading(key="percentile:MACRO.GSPC.D:3", title="S&P 500 Index against its last 3 years", period=D, units="points",
              series_ids=["MACRO.GSPC.D"], values={"latest": 6910.39, "percentile": 99.1, "years": 3.0})

# A seasonal reading whose value keys name years (value_in_2021): the years may be written as years, never as quantities
seas_years = Reading(key="seasonal:PET.WCESTUS1.W:5", title="US crude stocks against the same week of earlier years", period=D,
                     units="Thousand Barrels", series_ids=["PET.WCESTUS1.W"],
                     values={"current_value": 417797.0, "seasonal_avg": 433637.2, "lookback_years": 5.0,
                             "value_in_2021": 434020.0, "value_in_2025": 424155.0},
                     request={"tool": "seasonal", "action": "seasonal", "body": {}})

WRONG = [  # (what is wrong, the answer); every one must be rejected
    ("L1: a value key's years written as a quantity", dict(readings=[seas_years], summary="WTI will hit 2021 to 2025 by spring.")),
    ("L1: a value key's year after 'reach'", dict(readings=[seas_years], summary="Brent could reach 2025 next year.")),
    ("L1: a value key's year after 'to'", dict(readings=[seas_years], summary="US crude stocks could fall to 2021.")),
    ("L1: p95's 95 with a currency word", dict(readings=[hh_pct], summary="Henry Hub could hit 95 dollars.")),
    ("L1: a bare 95 taken from the key p95", dict(readings=[hh_pct], summary="Henry Hub will reach 95 within weeks.")),
    ("L1: a bare 25 taken from the key p25", dict(readings=[hh_pct], summary="Henry Hub could drop to 25 next month.")),
    ("L1: a year taken from a series id (NYMEX.WTI.2027-01.D)", dict(readings=[wti27], summary="WTI could reach 2027 by the spring.")),
    ("L1: the 500 of the S&P 500's title, away from its name", dict(readings=[spx], summary="Brent could fall to 500.")),
    ("L2: a percentile written as money, USD and a space before it", dict(readings=[hh_pct], summary="Henry Hub trades at USD 65.93.")),
    ("L2: a percentile written as money, EUR and a space before it", dict(readings=[hh_pct], summary="Henry Hub trades at EUR 65.93.")),
    ("L2: a percentile written as money, $ and a space before it", dict(readings=[hh_pct], summary="Henry Hub trades at $ 65.93.")),
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
    # the adversary's held-out unit cases that passed the first cut (round 4)
    ("a stock in thousand barrels written as barrels (U06: a thousandfold error)",
     dict(facts=[stocks], summary="Crude stocks excluding the SPR were 414,417 barrels.")),
    ("a rate in thousand barrels a day written as a stock (U10)",
     dict(facts=[SeriesFact(series_id="PET.WCRIMUS2.W", name="US crude imports", units="Thousand Barrels per Day",
                            latest_period=dt.date(2026, 11, 13), latest_value=5576.0)],
          summary="Crude imports were 5,576 thousand barrels in storage.")),
    # units glued to the number (the adversary, round 5, finding 17)
    ("a percent written as a rate glued to the number", dict(
        readings=[report.model_copy(update={"values": {**report.values, "Refinery utilisation.value": 95.7},
                                            "value_units": {**report.value_units, "Refinery utilisation.value": "Percent"}})],
        summary="Refinery runs were 95.7mb/d.")),
    ("a price change written as a stock glued to the number", dict(readings=[report], summary="Gasoline stocks were 0.19mb.")),
    ("a stock in thousand barrels written as barrels glued to the number", dict(facts=[stocks], summary="Crude stocks were 414,417bbl.")),
    # round 6 (finding 18): a currency glued in front is money and is tested; unknown glued letters are refused
    ("a price per gallon written per barrel with USD glued in front", dict(readings=[report], summary="Diesel cost USD3.81 a barrel.")),
    ("a price per barrel written per gallon with USD glued in front", dict(facts=[wti], summary="WTI futures were USD88.10/gal.")),
    ("a percent written as a rate in a unit no rule reads", dict(
        readings=[report.model_copy(update={"values": {**report.values, "Refinery utilisation.value": 95.7},
                                            "value_units": {**report.value_units, "Refinery utilisation.value": "Percent"}})],
        summary="Refinery runs were 95.7MMbbl/d.")),
    ("a price change written in a unit no rule reads", dict(readings=[report], summary="Gasoline stocks were 0.19mmb.")),
    ("a percent written as a rate, rescued by an unlabelled copy of the number (U08)",
     dict(readings=[report.model_copy(update={"values": {**report.values, "Refinery utilisation.value": 95.7, "metric.refinery_util": 95.7},
                                              "value_units": {**report.value_units, "Refinery utilisation.value": "Percent"}})],
          summary="Refinery runs were 95.7 million barrels a day.")),
    # round 3 of the adversary
    ("the 8 of a 1.8-sigma move written as a stock change (a digit of a decimal is not a name)",
     dict(readings=[signals_r], summary="US crude stocks fell by 8 million barrels on the week.")),
    ("the 12 of a 12-month curve written as a price (a hyphen term's number, written without its hyphen)",
     dict(readings=[signals_r], summary="Brent rose $12 a barrel.")),
    ("a snapshot metric that rose, said to have fell",
     dict(readings=[signals_r], summary="The opec call qoq change fell by 0.55.")),
    # 24 Nov 2026: a reading's thousand-barrel values may be written in million barrels, and a server text's
    # parameter (week=46) may be quoted. These keep both doors narrow.
    ("a thousand-barrel stock converted to million barrels but written as thousand",
     dict(readings=[seasonal5], summary="US crude stocks stand at about 417.8 thousand barrels.")),
    ("a thousand-barrel stock written with its own digits in million barrels",
     dict(readings=[seasonal5], summary="US crude stocks stand at 417,797 million barrels.")),
    ("a server text's week number given a unit",
     dict(readings=[seasonal5], summary="US crude stocks fell by 46 thousand barrels on the week.")),
    ("a server text's week number given as a percent",
     dict(readings=[seasonal5], summary="US crude stocks are 46 percent below their five-year average.")),
    # 24 Nov 2026, after the sweep: "stretched" takes its side word, a usual change needs no direction word, and a
    # fact's year-ago level and change may be written in million barrels. These keep the three doors narrow.
    ("funds stretched long, where the percentile is low",
     dict(readings=[watch], summary="Funds are stretched long in natural gas, at the 1.9 percentile of three years.")),
    ("a usual build called a draw",
     dict(readings=[evidence], summary="US crude stocks built 5,280 thousand barrels over four weeks, against a usual draw of 5,492.")),
    ("a year-ago stock converted to million barrels but written as thousand",
     dict(facts=[stocks_yoy], summary="US crude stocks were 427.58 thousand barrels a year earlier.")),
    ("a fall over the year, converted to million barrels, called a rise",
     dict(facts=[stocks_yoy], summary="US crude stocks were 417,797 thousand barrels, down 2.29% on the year, though up 9.8 million "
                                      "barrels since the base week.")),
    ("a usual draw written bare beside a build, so the reader carries 'build' over",
     dict(readings=[evidence_draw], summary="US crude stocks built 5,280 thousand barrels over four weeks, against a usual 5,492.")),
    # the adversary's verdict on 78e1c12 (3a): in EIA's usage M is a thousand, so each of these says 417.8 thousand
    ("a converted figure in Mbbl", dict(readings=[seasonal5], summary="US crude stocks stand at about 417.8 Mbbl.")),
    ("a converted figure in mbbl, a unit word not read", dict(readings=[seasonal5], summary="US crude stocks stand at about 417.8 mbbl.")),
    ("a converted figure in kbbl", dict(readings=[seasonal5], summary="US crude stocks stand at about 417.8 kbbl.")),
    ("a converted figure in Mb", dict(readings=[seasonal5], summary="US crude stocks stand at about 417.8 Mb.")),
    ("a converted figure glued to Mb", dict(readings=[seasonal5], summary="US crude stocks stand at about 417.8Mb.")),
    ("a converted figure in M barrels", dict(readings=[seasonal5], summary="US crude stocks stand at about 417.8 M barrels.")),
    ("a fact's converted year-ago level in Mbbl", dict(facts=[stocks_yoy], summary="US crude stocks were 427.6 Mbbl a year earlier.")),
    ("a converted figure written bare beside a thousand-barrel one",
     dict(facts=[stocks_yoy], summary="US crude stocks are 417,797 thousand barrels, against 427.6 a year earlier.")),
    # (3b): a server text's week=46 is a phrase, never a quantity
    ("week=46 as a count of weeks", dict(readings=[seasonal5], summary="US crude stocks have fallen for 46 weeks.")),
    ("week=46 as a count of times", dict(readings=[seasonal5], summary="US crude stocks fell 46 times in a row.")),
    ("week=46 as a hyphenated window", dict(readings=[seasonal5], summary="US crude stocks are at a 46-week low.")),
    ("week=46 as a gap to the average", dict(readings=[seasonal5], summary="US crude stocks are 46 below their five-year average.")),
    ("week=46 as a rank", dict(readings=[seasonal5], summary="US crude stocks rank 46th against the last five years.")),
    ("week=46 as a change, beside the phrase", dict(readings=[seasonal5], summary="US crude stocks rose 46 in week 46.")),
    # (3c): a decimal parameter names nothing
    ("the whole part of a decimal parameter, as a count", dict(readings=[signals_z], summary="The crack signal has fired 3 times.")),
    # the adversary's round 2 on aeddce6: "stretched short" must not excuse a plain high word, and week=46 is a week
    # of the year, not a count of weeks
    ("a low percentile called high, beside 'stretched short'",
     dict(readings=[watch], summary="Funds are high and stretched short in natural gas at the 1.9 percentile.")),
    ("a low percentile called elevated, beside 'stretched short'",
     dict(readings=[funds], summary="Managed money in WTI is stretched short and elevated, at the 6.8th percentile.")),
    ("a high percentile called stretched short", dict(readings=[freight], summary="Tanker freight is stretched short, at percentile 96 of 3 years.")),
    ("week=46 as the 46th week of a decline", dict(readings=[seasonal5], summary="US crude stocks are in their 46th week of decline.")),
    ("week=46 as week 46 of a decline", dict(readings=[seasonal5], summary="US crude stocks are in week 46 of their decline.")),
]

RIGHT = [  # correct prose that the rules must not reject
    # L1 and L2 (24 Nov 2026): a name's number beside its own name, a percentile point as its percentile, a currency
    # written before a true price with a space
    dict(readings=[hh_pct], summary="Henry Hub's 95th percentile over 5 years is 6.90, and its 5th percentile 2.10."),
    dict(readings=[spx], summary="The S&P 500 is at the 99.1 percentile of 3 years."),
    dict(facts=[brent], summary="Brent futures settled at USD 93.07 a barrel on 2026-11-17."),
    dict(facts=[brent], summary="Brent futures settled at $ 93.07 a barrel on 2026-11-17."),
    dict(readings=[seas_years], summary="The comparison uses five earlier years (2021 to 2025)."),
    dict(readings=[seas_years], summary="The comparison uses the same week in 2021 to 2025."),
    dict(readings=[seas_years], summary="Stocks are below the 2021-2025 range, at 417,797 thousand barrels."),
    dict(readings=[seas_years], summary="Stocks were 424,155 thousand barrels in 2025 and 434,020 in 2021."),
    # the adversary's P11 (23 Nov 2026): both were refused until 24 Nov
    dict(readings=[seasonal5], summary="US crude stocks stand at about 417.8 million barrels, below the five-year average for "
                                       "the week of 433,637.2 thousand barrels."),
    dict(readings=[seasonal5], summary=seasonal5.context),
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
    dict(facts=[SeriesFact(series_id="PET.WCRIMUS2.W", name="US crude imports", units="Thousand Barrels per Day",
                           latest_period=dt.date(2026, 11, 13), latest_value=5576.0)],
         summary="Crude imports were 5,576 thousand barrels a day, or 5,576 thousand barrels daily."),
    dict(facts=[SeriesFact(series_id="PET.WCRIMUS2.W", name="US crude imports", units="Thousand Barrels per Day",
                           latest_period=dt.date(2026, 11, 13), latest_value=5576.0)], summary="Crude imports were 5,576kb/d."),
    dict(readings=[report], summary="Total gasoline stocks are 215.9mb and regular gasoline is $3.81/gal."),
    dict(facts=[wti], summary="WTI futures were USD88.10 a barrel, and the M1 contract leads the curve."),
    # three true sentences the live gate refused on 21 Nov 2026 (e0637c8)
    dict(readings=[signals_r.model_copy(update={"units": "as each metric: 12-month curve, M12-M1 ($/bbl; negative = backwardation)"})],
         summary="The 12-month curve spread is -15.26 dollars per barrel, below the -10 threshold."),
    dict(readings=[funds], summary="Managed money is net long 151,200 contracts, at the 6.8th percentile of its three-year range."),
    dict(readings=[Reading(key="stats:PET.RWTC.D:3", title="WTI spot: descriptive statistics, last 3 years", period=D,
                           units="Dollars per Barrel", series_ids=["PET.RWTC.D"], values={"count": 748.0, "mean": 75.930294},
                           value_units={"mean": "Dollars per Barrel"}, request={"tool": "stats", "action": "stats", "body": {}})],
         summary="Over 748 daily values, WTI averaged 75.93 dollars a barrel."),
    # a percent named pct_... (the live gate refused it, 21 Nov 2026)
    dict(readings=[seasonal3.model_copy(update={"values": {**seasonal3.values, "pct_vs_avg": -3.652869},
                                                "value_units": {"current_value": "Thousand Barrels", "seasonal_avg": "Thousand Barrels"}})],
         summary="US crude stocks are 417,797 thousand barrels, 3.65 percent below the three-year average of 434,167 thousand barrels."),
    dict(facts=[wti_up], summary="WTI spot rose 1.20 dollars a barrel, or 1.38%, to $88.10 per barrel."),
    dict(readings=[funds], summary="Managed money is net long 151,200 contracts, at the 6.8th percentile."),
    dict(readings=[signals_r], summary="The 12-month curve, M12 minus M1, is -15.26, below the -10 threshold; the OPEC call QoQ change is 0.55."),
    # the settings sweep of 24 Nov 2026: each was sent back in most runs, and is true
    dict(readings=[watch], summary="Fund positioning in NYMEX natural gas is stretched short, with net at the 1.9 percentile of "
                                   "three years (report of 2026-11-17)."),
    dict(readings=[watch], summary="Natural gas fund positioning is stretched short, at the 1.9 percentile of three years."),
    dict(readings=[watch], summary=watch.context),
    dict(readings=[evidence], summary="Against this, the four-week US stock build of 5,280 thousand barrels was close to its usual "
                                      "5,492 (neutral)."),
    dict(readings=[evidence], summary="Cushing stocks and the four-week US stock build (5,280 thousand barrels against a usual 5,492) "
                                      "are neutral."),
    dict(readings=[evidence], summary=evidence.context),
    dict(facts=[stocks_yoy], summary="US commercial crude stocks were 417,797 thousand barrels on 2026-11-13, down from 427.58 million "
                                     "barrels on 2025-11-07, a fall of 9.8 million barrels (-2.29%)."),
    dict(facts=[stocks_yoy], summary="That is 417.8 million barrels now, against 427.6 million a year earlier, down 9.78 million."),
    # units as EIA and IEA write them: MMbbl a million, Mbbl a thousand, mb/d a million a day
    dict(readings=[seasonal5], summary="US crude stocks stand at about 417.8 MMbbl."),
    dict(facts=[stocks_yoy], summary="US crude stocks are 417,797 Mbbl, against 427,581 Mbbl a year earlier."),
    dict(facts=[imports], summary="Crude imports were 5.576 mb/d, or 5,576 thousand barrels a day."),
    # a server text's parameter, as its phrase
    dict(readings=[seasonal5], summary="In week 46, US crude stocks were 417,797 thousand barrels."),
    dict(readings=[seasonal5], summary="In the 46th week of the year, US crude stocks were 417,797 thousand barrels."),
    # the adversary's B6 (refused by 1b631ca): a week of each year, not a count of weeks
    dict(readings=[seasonal5], summary="In week 46 of each of the last five years US crude stocks were above 417,797 thousand barrels."),
    dict(readings=[seasonal5], summary="In the 46th week of each year, US crude stocks averaged 433,637.2 thousand barrels."),
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
    # The send-back names the uncited reading that holds the summary's numbers (24 Nov 2026, the adversary on
    # brent_wti_corr): the right one of three, and none when no reading holds them.
    from es_agent.agent import uncited_holders
    pool = {r.key: r for r in (seasonal3, seasonal5, funds)}
    keys, left = uncited_holders(DeskAnswer(facts=[], summary="US crude stocks are 417,797 thousand barrels, below the "
                                                               "five-year average of 433,637.2."), pool)
    ok = keys == [seasonal5.key] and not left
    print(f"{'named    ' if ok else 'NOT NAMED'} the uncited reading that holds the numbers: {keys}, left {left}")
    failed += not ok
    keys, left = uncited_holders(DeskAnswer(facts=[], summary="US crude stocks are 399,999 thousand barrels."), pool)
    ok = not keys and bool(left)
    print(f"{'none     ' if ok else 'WRONGLY NAMED'} for a number no reading holds: {keys}, left {left}")
    failed += not ok
    # Only precise numbers name a reading (the adversary's 1a, 24 Nov 2026): an invented short count must not be
    # traced to rolling_correlation's years=3, while a correlation to two decimals still names it.
    pool[corr.key] = corr
    keys, left = uncited_holders(DeskAnswer(facts=[], summary="Brent and WTI decoupled on 3 occasions in the last three years."), pool)
    ok = not keys and bool(left)
    print(f"{'none     ' if ok else 'WRONGLY NAMED'} for an invented short count: {keys}, left {left}")
    failed += not ok
    keys, left = uncited_holders(DeskAnswer(facts=[], summary="Brent and WTI spot have a correlation of 0.91 over three years."), pool)
    ok = keys == [corr.key] and not left
    print(f"{'named    ' if ok else 'NOT NAMED'} the correlation reading on a two-decimal value: {keys}, left {left}")
    failed += not ok
    # precision is the value's, not the written zeros' (the adversary's E1): an invented z-score of 2.00 must not name
    # the signals reading for its threshold of 2.0
    thresholds = Reading(key="signals:thresholds", title="The server's signals, live", period=D, units="as each metric",
                         series_ids=[], values={"opec_production_gap.threshold": 2.0, "metric.brent_wti_z": -0.45},
                         request={"tool": "signals", "action": "derived_signals", "body": {}})
    keys, left = uncited_holders(DeskAnswer(facts=[], summary="The Brent-WTI spread z-score is 2.00."), {**pool, thresholds.key: thresholds})
    ok = not keys and bool(left)
    print(f"{'none     ' if ok else 'WRONGLY NAMED'} for a whole number written with zeros: {keys}, left {left}")
    failed += not ok
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
