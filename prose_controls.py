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
# The adversary's three remaining items (242042f1, 24 Nov 2026): a window or count of the data (years 3, observations
# 747) passed as a market figure; the euro and pound signs were not read as money; a written currency was not checked
# against the value's own (EUR on a dollar price).
hh_obs = Reading(key="percentile:NG.RNGWHHD.D:3", title="Henry Hub spot against its last 3 years", period=D, units="USD/MMBtu",
                 series_ids=["NG.RNGWHHD.D"], values={"latest": 4.21, "percentile": 65.93, "years": 3.0, "observations": 747.0})
hh_fact = SeriesFact(series_id="NG.RNGWHHD.D", name="Henry Hub natural gas spot", units="Dollars per Million Btu",
                     latest_period=D, latest_value=3.10)
power_eur = SeriesFact(series_id="ELEC.DE.D", name="German day-ahead power", units="EUR/MWh", latest_period=D, latest_value=95.40)

# A seasonal reading whose value keys name years (value_in_2021): the years may be written as years, never as quantities
seas_years = Reading(key="seasonal:PET.WCESTUS1.W:5", title="US crude stocks against the same week of earlier years", period=D,
                     units="Thousand Barrels", series_ids=["PET.WCESTUS1.W"],
                     values={"current_value": 417797.0, "seasonal_avg": 433637.2, "lookback_years": 5.0,
                             "value_in_2021": 434020.0, "value_in_2025": 424155.0},
                     request={"tool": "seasonal", "action": "seasonal", "body": {}})

# The suite's own tool results (results/golden.json, the frozen data): an answer with the facts, spreads and readings
# of the named recorded answers, and a summary of its own
with open("results/golden.json", encoding="utf-8") as _f:
    _GOLDEN = json.load(_f)


def gold(*names: str, summary: str) -> dict:
    return {part: [x for n in names for x in _GOLDEN[n].get(part, [])] for part in ("facts", "spreads", "readings")} | {
        "summary": summary}


# live-fixes-2b (25 Nov 2026): B, text read as it is shown (the adversary's B, reproduced on de8726a), ported from
# live-fixes-2 in its narrow form. Each WRONG case names the reason it must be refused for, and each was accepted by
# d029c9c (the released checker). A (a percentile written as a place) was dropped from this branch: its wrong cases
# are LIMIT entries below, accepted by both trees.
# A server percentile reading as the suite's henry_hub_percentile has it
hh_srv = Reading(key="percentile:NG.RNGWHHD.D:3", title="Henry Hub Natural Gas Spot Price, Daily: latest against its last 3 years",
                 period=D, units="Dollars per Million Btu", series_ids=["NG.RNGWHHD.D"],
                 values={"target_value": 3.1, "percentile": 65.930388, "max": 30.72, "median": 2.9, "p5": 1.58, "p10": 1.83,
                         "p25": 2.44, "p75": 3.22, "p90": 3.9, "p95": 4.364, "observations": 747.0, "years": 3.0},
                 context="It is inside its usual range, between the 10th and 90th percentile lines (1.83 and 3.90) of the window.",
                 request={"tool": "percentile", "action": "percentile", "body": {}})
# Live item 1 (dropped from this branch on 25 Nov 2026, held on the lab branch): a reading's value whose key names a
# change by its period (cushing_7d_pct, eu_oil_imports_3m_pct, opec_call_qoq, opec_world_demand_revision, the eia_weekly
# report's wow and yoy, and mom, dod, chg, yoy_pct, an N-week percent). d029c9c reads no side for these keys, and
# neither does this branch: one reading per shape, for the right controls and the known limits below
period_sig = Reading(key="signals:periods", title="The server's signals, live", period=D,
                     units="as each metric: million barrel per day; percent", series_ids=[],
                     values={"metric.eu_oil_imports_3m_pct": -12.3, "metric.opec_call_qoq": -0.55,
                             "metric.opec_world_demand_revision": 0.13, "metric.henry_hub_52w_pct": 18.5},
                     value_units={"metric.opec_call_qoq": "million barrel per day",
                                  "metric.opec_world_demand_revision": "million barrel per day"},
                     request={"tool": "signals", "action": "derived_signals", "body": {}})
period_rep = Reading(key="report:periods", title="A weekly report", period=D,
                     units="Thousand Barrels per Day; Dollars per Barrel; Percent", series_ids=[],
                     values={"Gasoline product supplied.mom": -85.0, "WTI, Cushing.dod": 0.42, "wti_price_chg": 1.37,
                             "US crude stocks.yoy_pct": -2.29},
                     value_units={"Gasoline product supplied.mom": "Thousand Barrels per Day",
                                  "WTI, Cushing.dod": "Dollars per Barrel", "wti_price_chg": "Dollars per Barrel"},
                     request={"tool": "report", "action": "report", "body": {}})
# Live item 3 (25 Nov 2026): a change's base value from far back. get_change on the frozen data at a lookback of 6717
# days gives WTI's 139.69 of 2008-06-27; wti_far44 is the adversary's figure (44.60 at the end of 2008)
wti_far = SeriesFact(series_id="PET.RWTC.D", name="Cushing, OK WTI Spot Price FOB, Daily", units="Dollars per Barrel",
                     latest_period=D, latest_value=89.53, lookback_days=6717, base_period=dt.date(2008, 6, 27),
                     base_value=139.69, change_abs=-50.16, change_pct=-35.908082)
wti_far44 = SeriesFact(series_id="PET.RWTC.D", name="Cushing, OK WTI Spot Price FOB, Daily", units="Dollars per Barrel",
                       latest_period=D, latest_value=89.53, lookback_days=6530, base_period=dt.date(2008, 12, 31),
                       base_value=44.60, change_abs=44.93, change_pct=100.73991)
_BASE = "a base value"
FIXES_LF2B = [  # (what is wrong, the answer, the reason it must be refused for)
    # B: a raised, lowered, circled or full-width character is read as what it shows
    ("B: a price in raised digits", dict(facts=[wti_up], summary="WTI will reach $¹⁵⁰ by spring."), "150"),
    ("B: a price in lowered digits", dict(facts=[brent], summary="Brent could fall to $₈₀."), "80"),
    ("B: a percent in raised digits", dict(facts=[wti_up], summary="WTI is up ¹⁴% on the week."), "14"),
    ("B: a price in circled digits", dict(facts=[wti_up], summary="WTI could reach $①⑤⓪ by spring."), "150"),
    ("B: a unit in full-width letters", dict(facts=[wti_up], summary="WTI rose 1.20 ｍｉｌｌｉｏｎ ｂａｒｒｅｌｓ on the week."),
     "million barrel"),
    ("B: a level word in full-width letters, pointing the wrong way",
     dict(spreads=[gap], summary="Brent spot was 0.62 USD/bbl ａｂｏｖｅ WTI spot on 2026-11-11."), "points the wrong way"),
    ("B: a fraction sign", dict(facts=[wti_up], summary="WTI rose ½ a dollar on the week."), "as a decimal"),
    ("B: a footnote mark glued to a word", dict(facts=[brent], summary="Brent² futures are at 93.07 USD/bbl."), "footnote"),
    ("B: a footnote mark at the end of a sentence", dict(facts=[brent], summary="Brent futures are at 93.07 USD/bbl, the latest "
                                                                               "settlement³."), "footnote"),
    ("B: a footnote mark after a full stop", dict(facts=[brent], summary="Brent futures are at 93.07 USD/bbl.¹"), "footnote"),
    ("B: a footnote mark after a percent sign", gold("wti_30d", summary="WTI fell 17.26%¹ over 30 days."), "footnote"),
    # a lowered digit after a currency code or a plain word is a number, not a formula's index (the reviewer of 6f63817)
    ("B: a price in lowered digits after a currency code", gold("wti_30d", summary="WTI could fall to USD₈₀."), "footnote"),
    ("B: a price in lowered digits glued to a plain word", gold("wti_30d", summary="WTI could fall to₈₀ dollars."), "footnote"),
    ("B: a direction control character", dict(facts=[brent], summary="Brent futures are at 93.07 USD/bbl\u202e."), "direction control"),
    ("B: a window in a ligature ('ﬁve-year' for a three-year average)",
     dict(readings=[seasonal3], summary="US crude stocks are 417,797 thousand barrels against a ﬁve-year average of 434,167."),
     "window of 5 years"),
    ("B: a month name in full-width letters", dict(readings=[freight], summary="Freight is at the 96th percentile, its highest "
                                                                              "since Ｊｕｌｙ."), "write dates"),
    ("B: a date in raised digits that no tool returned", gold("wti_30d", summary="WTI was 89.53 dollars on ²⁰²⁶-¹¹-¹⁸."),
     "2026-11-18"),
    # live item 3: a change's base value written beside another value's date (d029c9c traced the number and the date
    # each on its own); the sandbox reviewer's break cases among them
    ("3: the base value beside the latest date, in another clause",
     dict(facts=[wti_far44], summary="As of 2026-11-17, WTI spot was $44.60 a barrel."), _BASE),
    ("3: ... in the same clause", dict(facts=[wti_far44], summary="WTI spot was $44.60 a barrel on 2026-11-17."), _BASE),
    ("3: ... after a comma", dict(facts=[wti_far44], summary="WTI spot was $44.60 a barrel, on 2026-11-17."), _BASE),
    ("3: ... with 'from' before the date", dict(facts=[wti_far44], summary="WTI spot, from the 2026-11-17 data, was $44.60 a barrel."),
     _BASE),
    ("3: ... with USD glued to the number", dict(facts=[wti_far44], summary="WTI spot was USD44.60 a barrel on 2026-11-17."), _BASE),
    ("3: ... with a hyphen after the date", dict(facts=[wti_far44], summary="WTI's 2026-11-17-dated spot price was $44.60 a barrel."),
     _BASE),
    ("3: the frozen data's own 6717-day base", dict(facts=[wti_far], summary="As of 2026-11-17, WTI spot was $139.69 a barrel."), _BASE),
    ("3: ... in brackets after its number", dict(facts=[wti_far], summary="WTI spot: $139.69 (2026-11-17)."), _BASE),
    ("3: a 30-day base given the latest date", gold("wti_30d", summary="As of 2026-11-17, WTI spot was $108.21 a barrel."), _BASE),
    ("3: a year-ago base in code's million barrels, given the latest date",
     gold("us_crude_yoy", summary="US crude stocks were 427.58 million barrels on 2026-11-13."), _BASE),
    ("3: ... as the 'spot price', the plain dated level", dict(facts=[wti_far], summary="As of 2026-11-17, WTI spot price was $139.69 "
                                                                                       "a barrel."), _BASE),
    ("3: ... 'settled at' with the latest date (the review of 89ab3ad)",
     dict(facts=[wti_far], summary="WTI spot settled at $139.69 on 2026-11-17."), _BASE),
]

# The review of 89ab3ad's evidence (25 Nov 2026): true, accepted by d029c9c, refused by 89ab3ad. Item 1 read a direction
# word as the side of another series' change ("rose by more than the 3.17 million barrel SPR draw": "rose" is
# crude's); item 2 read a spread's number compared with another figure as one series compared with the other ("The
# spot spread of 3.41 dollars is lower than the WTI spot premium of 4.88 dollars"). Both items were dropped from this
# branch; these are right controls, each also kept as a caveat (main), and the true sentences of item 3 the review
# wrote beside them.
RIGHT_89AB3AD = [
    gold("eia_weekly_brief", summary="Commercial crude stocks rose by more than the 3.17 million barrel SPR draw."),
    gold("eia_weekly_brief", summary="Crude stocks rose by more than the 3.17 million barrel SPR draw."),
    gold("eia_weekly_brief", summary="Commercial crude stocks rose more than the 3.17 million barrels the SPR lost."),
    gold("eia_weekly_brief", summary="Commercial crude rose more than the 3.17 million barrel SPR release."),
    gold("eia_weekly_brief", summary="US crude stocks rose more than the 3.17 million barrel SPR draw this week."),
    gold("eia_weekly_brief", summary="Crude stocks rose by more than the 3.17 million barrel SPR draw, so total stocks rose too."),
    gold("eia_weekly_brief", summary="Commercial crude climbed by more than the 3.17 million barrel fall in the SPR."),
    gold("eia_weekly_brief", summary="Commercial crude stocks gained more than the 3.17 million barrels drained from the SPR."),
    gold("eia_weekly_brief", summary="Commercial crude added more than the 3.17 million barrels the SPR lost."),
    gold("eia_weekly_brief", summary="Crude stocks built by more than the 3.17 million barrel SPR draw."),
    gold("eia_weekly_brief", summary="Gasoline stocks rose more than the 1.21 million barrel Cushing draw."),
    gold("eia_weekly_brief", summary="Gasoline stocks rose by more than the 1.21 million barrel draw in Cushing on the week."),
    gold("eia_weekly_brief", summary="Distillate stocks rose less than the 3.17 million barrel SPR draw."),
    gold("eia_weekly_brief", summary="The SPR fell more than the 1.57 million barrel distillate build."),
    gold("eia_weekly_brief", summary="Cushing stocks fell less than the 3.38 million barrel crude build."),
    gold("eia_weekly_brief", summary="Commercial crude stocks rose by over the 3.17 million barrels the SPR lost."),
    gold("eia_weekly_brief", summary="SPR releases added 3.17 million barrels to the market on the week."),
    gold("eia_weekly_brief", summary="Crude stocks rose by more than the SPR's 3.17 million barrel draw."),
    gold("futures_spread", summary="The spot spread of 3.41 dollars is lower than the WTI spot premium to its future, 4.88 dollars."),
    gold("futures_spread", summary="The spot spread of 3.41 dollars is lower than the WTI spot-futures gap of 4.88 dollars."),
    gold("futures_spread", summary="The spot gap of 3.41 dollars is less than the WTI spot premium of 4.88 to its future."),
    gold("futures_spread", summary="The spot spread of 3.41 dollars is lower than the WTI futures discount of 4.88 to spot."),
    gold("futures_spread", summary="Brent's spot lead of 3.41 dollars is lower than the WTI spot premium of 4.88 dollars to its "
                                   "future."),
    gold("arb_us_europe", summary="The spot spread of 3.41 dollars is lower than the WTI spot premium of 4.88 dollars to its "
                                  "future."),
    dict(facts=[wti_far], summary="WTI spot price as of 2008-06-27: 139.69."),
    dict(facts=[wti_far], summary="As of 2026-11-17, WTI spot was $89.53 a barrel, against $139.69 a barrel on 2008-06-27."),
    dict(facts=[wti_far], summary="WTI spot (2026-11-17): 89.53. WTI spot (2008-06-27): 139.69."),
]

# The review of bb2c261's evidence (25 Nov 2026), and the builder's sentences beside it: true, accepted by d029c9c,
# refused by bb2c261. Item 1: a period change looked back on (the side word after a past tense describes the earlier
# level), supposed, asked or corrected; item 2: a comparative denied, asked, supposed or corrected; item 3: a base
# value in a premise corrected, or placed in another time by a word no list holds.
RIGHT_BB2C261 = [
    gold("eia_weekly_brief", summary="Brent's year-ago price was 28.08 dollars lower."),
    gold("eia_weekly_brief", summary="A year ago, Brent was 28.08 dollars lower."),
    gold("eia_weekly_brief", summary="Year-ago Cushing stocks were 4.33 million barrels lower."),
    gold("eia_weekly_brief", summary="Cushing stocks were 1.21 million barrels higher a week ago."),
    gold("eia_weekly_brief", summary="Last week, Cushing stocks stood 1.21 million barrels higher."),
    gold("eia_weekly_brief", summary="Week-ago Cushing stocks were 1.21 million barrels higher."),
    gold("eia_weekly_brief", summary="A year ago, US crude stocks were 6.36 million barrels higher."),
    gold("eia_weekly_brief", summary="Gasoline stocks rose 5.19 million barrels; a week ago they were 5.19 million barrels lower."),
    gold("eia_weekly_brief", summary="Last week's Cushing stocks were 1.21 million barrels higher than this week's."),
    gold("eia_weekly_brief", summary="Cushing stocks would have to rise 1.21 million barrels to get back to last week's level."),
    gold("eia_weekly_brief", summary="To get back to last week's level, Cushing stocks would need to rise 1,209 thousand barrels."),
    gold("regime_signals", summary="The claim that Cushing stocks rose 4.05% on the week is wrong; they fell 4.05%."),
    gold("regime_signals", summary="You suggest Cushing stocks rose 4.05% this week; the data show they fell 4.05%."),
    gold("regime_signals", summary="Did Cushing stocks rise 4.05% on the week? No: they fell 4.05%."),
    gold("eia_weekly_brief", summary="Is Cushing up 1.21 million barrels on the week? No: it is down 1.21 million."),
    gold("regime_signals", summary="Cushing stocks rose 4.05% on the week. In fact they fell 4.05%."),
    gold("regime_signals", summary="Undoing the week's draw takes a rise of 4.05%."),
    gold("regime_signals", summary="Cushing stocks ended up 4.05% lower on the week."),
    gold("regime_signals", summary="Cushing's weekly change has been as large as +4.05% this year."),
    gold("regime_signals", summary="Cushing stocks swung from +4.05% to -4.05% over two weeks."),
    gold("brent_wti_spread", summary="Brent is not 3.41 dollars cheaper than WTI."),
    gold("brent_wti_spread", summary="WTI isn't 3.41 dollars dearer than Brent."),
    gold("brent_wti_spread", summary="No, WTI is not 3.41 dollars higher than Brent."),
    gold("brent_wti_spread", summary="Contrary to the question, WTI is not 3.41 dollars dearer than Brent."),
    gold("brent_wti_spread", summary="WTI is not $3.41 dearer than Brent; it is $3.41 cheaper."),
    gold("brent_wti_spread", summary="Brent is not 3.41 dollars cheaper than WTI, it is 3.41 dollars dearer."),
    gold("brent_wti_spread", summary="The claim that WTI is 3.41 dollars dearer than Brent is wrong: Brent is the dearer."),
    gold("brent_wti_spread", summary="Is WTI 3.41 dollars dearer than Brent? No: Brent is 3.41 dollars dearer than WTI."),
    gold("brent_wti_spread", summary="If WTI were 3.41 dollars dearer than Brent, the arbitrage would run the other way."),
    gold("futures_spread", summary="Brent futures are not 8.94 dollars cheaper than WTI futures."),
    gold("futures_spread", summary="WTI futures are not 8.94 dollars higher than Brent futures."),
    gold("brent_wti_spread", summary="WTI is 3.41 dollars dearer than Brent. In fact, Brent is."),
    gold("brent_wti_spread", summary="WTI is 3.41 dollars higher than Brent was a year ago, by one account."),
    dict(facts=[wti_far], summary="It is false that WTI was $139.69 on 2026-11-17: it was 89.53 dollars."),
    dict(facts=[wti_far], summary="The claim that WTI was $139.69 on 2026-11-17 is wrong; that was its price on 2008-06-27."),
    dict(facts=[wti_far], summary="You suggest WTI spot was $139.69 a barrel on 2026-11-17; the data put it at 89.53."),
    dict(facts=[wti_far], summary="As of 2026-11-17, WTI's pre-crisis price was 139.69."),
    dict(facts=[wti_far], summary="WTI spot was $139.69 a barrel at the far end of the window that ends on 2026-11-17."),
    dict(facts=[wti_far], summary="WTI's spot price on 2008-06-27, as of 2026-11-17, was $139.69."),
]

FIXES_LF2B_RIGHT = [  # true sentences in the shapes B reads, and beside them
    # A is not in this branch (moved to the lab branch): true sentences in its shapes, accepted as on d029c9c
    dict(readings=[hh_pct], summary="Henry Hub sits at the 66th percentile of its last 5 years."),
    dict(readings=[hh_pct], summary="Henry Hub is at the 65.9th percentile, between its 25th and 75th percentiles (2.80 and 4.60)."),
    dict(readings=[hh_srv], summary="Henry Hub at 3.10 sits at the 65.93 percentile, inside its usual range (between the 10th and "
                                    "90th percentile lines of 1.83 and 3.90)."),
    dict(readings=[funds], summary="Managed money ranks at the 6.8th percentile of 156 weeks."),
    dict(readings=[freight], summary="Freight is now at the 96th percentile of 3 years, above its 90th percentile line."),
    dict(readings=[hh_pct], summary="Henry Hub sits at the 66ᵗʰ percentile."),
    dict(readings=[hh_pct], summary="For Henry Hub to sit at the 95th percentile it would have to reach 6.90."),
    dict(readings=[hh_pct], summary="Henry Hub is not at its 95th percentile."),
    dict(readings=[hh_pct], summary="Henry Hub never sits at the 95th percentile for long."),
    dict(readings=[freight], summary="Freight is in the 90th percentile or above."),
    dict(readings=[hh_pct], summary="If Henry Hub rose to 6.90 it would sit at the 95th percentile."),
    gold("henry_hub_percentile", summary="The 95th percentile of the window is 4.36."),
    gold("henry_hub_percentile", summary="The 90th percentile, at 3.90, is the line to watch."),
    gold("henry_hub_percentile", summary="Henry Hub is well short of its 95th percentile."),
    gold("henry_hub_percentile", summary="Henry Hub is nowhere near its 95th percentile."),
    gold("henry_hub_percentile", summary="Henry Hub would have to climb to its 95th percentile of 4.36 before it looked expensive."),
    gold("freight_history", summary="Freight has not fallen below its 90th percentile line (268.00) since 2026-07-31, 112 days."),
    # ... and the review of 906e707's (25 Nov 2026): a point's value as the subject, a premise corrected after the
    # placement, the past, a question, another point named, a subject that is no one value
    gold("henry_hub_percentile", summary="A price of 4.36 is at the 95th percentile of the three-year window."),
    gold("henry_hub_percentile", summary="Henry Hub's upper tail starts at 4.36, which is at the 95th percentile."),
    gold("henry_hub_percentile", summary="The 90th percentile is 3.90. A price there is at the 90th percentile."),
    gold("futures_crack", summary="Today's 41.13 crack is in the 88th percentile, while 44.98 is at the 90th percentile."),
    gold("wti_positioning", summary="Net length of 15,814 contracts is in the 10th percentile, and 191,531 contracts is at the "
                                    "90th percentile."),
    gold("henry_hub_percentile", summary="The premise that Henry Hub is at its 95th percentile does not hold: it sits at the 66th."),
    gold("henry_hub_percentile", summary="You suggest Henry Hub is at the 95th percentile; the data puts it at the 66th."),
    gold("henry_hub_percentile", summary="The visitor's figure, that Henry Hub is in the 95th percentile, does not match the data: "
                                         "it is in the 66th percentile."),
    gold("freight_history", summary="Freight was in the 90th percentile on 2026-07-31 and is in the 96th now."),
    gold("henry_hub_percentile", summary="Henry Hub was at the 95th percentile? No: it is at the 66th percentile."),
    gold("henry_hub_percentile", summary="The upper quartile is at the 75th percentile."),
    gold("henry_hub_percentile", summary="A stretched market is in the 90th percentile."),
    # B: read as shown, and the glyphs that keep their own meaning
    dict(facts=[wti_up], summary="WTI spot is at $⁸⁸.¹⁰ after rising ¹.²⁰ on the week."),
    dict(facts=[wti], summary="WTI futures are at ８８.１０ USD/bbl."),
    dict(spreads=[gap], summary="Brent spot was 0.62 USD/bbl ｂｅｌｏｗ WTI spot on 2026-11-11."),
    dict(facts=[wti], summary="WTI futures are at 88.1\u200b0 USD/bbl."),
    dict(facts=[power_eur], summary="German day-ahead power was €95.40 per MWh, a price that includes the cost of CO₂ allowances."),
    dict(facts=[power_eur], summary="German day-ahead power was €95.40 per MWh; no carbon price in tCO₂e or CO₂eq is cited."),
    dict(facts=[hh_fact], summary="Henry Hub is at $3.10 per million Btu; no series here is quoted per m³, per ㎡, in °C or in ‰."),
    # notation is kept as written, as d029c9c read it (the review of 906e707): a lowered digit after a letter, a raised
    # digit after a single letter
    gold("wti_30d", summary="No R² is computed here; WTI fell 17.26% over 30 days."),
    gold("wti_30d", summary="Propane (C₃) and condensate (C₅+) are not covered; WTI fell 17.26% over 30 days."),
    gold("wti_30d", summary="Emissions in MTCO₂e or lbCO₂ are not covered; WTI fell 17.26% over 30 days."),
    gold("wti_30d", summary="WTI fell 17.26% over 30 days; the variance σ² is not shown, nor gas in Gm³."),
    # ... and a lowered digit after a chemical symbol that looks like a plain word, or after one letter (an index)
    gold("wti_30d", summary="WTI fell 17.26% over 30 days; As₂O₃, In₂O₃, Na₂CO₃ and H₂SO₄ are not energy series."),
    gold("wti_30d", summary="WTI fell 17.26% over 30 days; no regression on x₁ or log₁₀ of the price is run."),
    # the ellipsis stays one character: NFKC writes it as three full stops, which ended the sentence before the number
    # and took the change's verb from it (the reviewer of live-fixes-2, 25 Nov 2026)
    gold("wti_30d", summary="WTI fell… 17.26% over 30 days, to 89.53 dollars."),
    gold("wti_30d", summary="WTI fell 17.26%… over 30 days, to 89.53 dollars."),
    gold("wti_30d", summary="WTI fell 17.26% over 30 days – to 89.53\u202fdollars, a change of −18.68 dollars."),
    # live item 1 (dropped from this branch): true sentences about changes named by their period, accepted as on d029c9c
    gold("regime_signals", summary="Cushing stocks fell 4.0% on the week."),
    gold("regime_signals", summary="Cushing stocks are down 4% on the week, and 4.05% lower than a week ago."),
    gold("regime_signals", summary="Cushing's 7-day change is -4.05%."),
    gold("regime_signals", summary="Cushing stocks have given up 4.05% over the week."),
    gold("regime_signals", summary="Cushing stocks did not rise; they fell 4.05% over the week."),
    gold("regime_signals", summary="Cushing stocks are not up 4.05% on the week; they are down 4.05%."),
    gold("regime_signals", summary="As refinery runs rose, Cushing stocks fell 4.05% on the week."),
    gold("regime_signals", summary="Even after crude stocks rose, Cushing is 4.05% lower on the week."),
    gold("regime_signals", summary="Rising runs took 4.05% off Cushing stocks on the week."),
    gold("regime_signals", summary="Higher refinery runs pulled Cushing stocks 4.05% lower on the week."),
    gold("regime_signals", summary="Cushing stocks posted a 4.05% weekly draw."),
    gold("regime_signals", summary="Cushing stocks fell more than 4% on the week."),
    gold("eia_weekly_brief", summary="Cushing stocks drew 1.21 million barrels on the week, while crude stocks rose 3.38 million."),
    gold("eia_weekly_brief", summary="US crude stocks rose 3.38 million barrels, gasoline 5.19 million and distillate 1.57 million."),
    gold("eia_weekly_brief", summary="Crude oil stocks were 417,797 thousand barrels, up 3,380 on the week and down 6,358 on the year."),
    gold("eia_weekly_brief", summary="Crude imports fell 1,122 thousand barrels per day on the week, and production rose 19 thousand "
                                     "barrels per day."),
    gold("eia_weekly_brief", summary="Brent rose 28.08 dollars on the year to 92.94, while WTI is 28.02 dollars higher than a year ago."),
    gold("eia_weekly_brief", summary="Regular gasoline gave up 0.19 dollars a gallon on the week."),
    dict(readings=[period_sig], summary="EU oil imports fell 12.3% over three months; OPEC revised its demand view up by 0.13 "
                                        "million barrels a day."),
    dict(readings=[period_rep], summary="US gasoline demand fell 85 thousand barrels per day on the month, and WTI rose 0.42 dollars "
                                        "on the day."),
    # live item 2 (dropped from this branch): comparatives on the right side, and beside them, accepted as on d029c9c
    gold("brent_wti_spread", summary="Brent is $3.41 a barrel dearer than WTI."),
    gold("brent_wti_spread", summary="WTI is $3.41 cheaper than Brent."),
    gold("brent_wti_spread", summary="WTI is 3.41 dollars a barrel less expensive than Brent, and Brent trades 3.41 dollars higher "
                                     "than WTI."),
    gold("brent_wti_spread", summary="WTI at 89.53 is 3.41 dollars cheaper than Brent at 92.94."),
    gold("brent_wti_spread", summary="Brent's 3.41 lower-than-usual premium over WTI is at the 34th percentile."),
    gold("brent_wti_spread", summary="Brent's 3.41 lower-than-usual spread to WTI sits at the 34th percentile."),
    gold("brent_wti_spread", summary="The spread of 3.41 dollars is lower than Brent's usual premium over WTI."),
    gold("brent_wti_spread", summary="The Brent-WTI spread of 3.41 dollars is lower than its 90th percentile of 9.71."),
    gold("brent_wti_spread", "wti_30d", summary="The Brent-WTI spread of 3.41 dollars is lower than WTI's 30-day fall of 18.68 "
                                                "dollars."),
    gold("brent_wti_spread", summary="The spread of 3.41 dollars leaves WTI cheaper than Brent."),
    gold("brent_wti_spread", summary="Brent's premium over WTI narrowed to 3.41 dollars, lower than a year ago."),
    gold("brent_wti_spread", summary="WTI is lower than Brent by 3.41 dollars."),
    gold("futures_spread", summary="WTI futures are 8.94 dollars lower than Brent futures for 2027-01 delivery."),
    # live item 3: a base value with its own date, with none, or written as where a move started
    dict(facts=[wti_far], summary="WTI spot was $139.69 a barrel on 2008-06-27."),
    dict(facts=[wti_far], summary="WTI spot was $89.53 a barrel on 2026-11-17, down 50.16 (35.91%) from $139.69 on 2008-06-27, "
                                  "6717 days earlier."),
    dict(facts=[wti_far], summary="As of 2026-11-17, WTI had fallen from 139.69 to 89.53."),
    dict(facts=[wti_far], summary="WTI is 89.53 on 2026-11-17, compared with 139.69 on 2008-06-27."),
    dict(facts=[wti_far], summary="WTI was 139.69, and on 2026-11-17 it was 89.53."),
    dict(facts=[wti_far], summary="WTI's 2008-06-27 price was 139.69 and its 2026-11-17 price 89.53."),
    dict(facts=[wti_far], summary="As of 2026-11-17, the starting level was 139.69."),
    dict(facts=[wti_far44], summary="WTI spot was $44.60 a barrel."),
    gold("wti_30d", summary="As of 2026-11-17, WTI was 89.53, and 30 days earlier it was 108.21."),
    gold("wti_30d", summary="As of 2026-11-17, WTI was 108.21 last month and 89.53 now."),
    gold("cushing_4w", summary="Cushing stocks fell to 26,147 thousand barrels on 2026-11-13 (27,594)."),
    gold("us_crude_yoy", summary="US crude stocks were 427.58 million barrels on 2025-11-07 and 417.8 million on 2026-11-13."),
    dict(facts=[wti_far], summary="Eighteen years before 2026-11-17, WTI was 139.69."),
    gold("us_crude_yoy", summary="A year before 2026-11-13, US crude stocks were 427,581 thousand barrels."),
    # the review of bb2c261 (25 Nov 2026): true sentences each live rule refused there, accepted by d029c9c; item 3
    # now judges only a plain statement (es_agent/prose.py _plainly_stated), and items 1 and 2 were dropped. Each is
    # also kept as a caveat (main).
    *RIGHT_BB2C261,
    # the review of 89ab3ad (25 Nov 2026), the same way
    *RIGHT_89AB3AD,
]

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
    ("LF1: the seasonal window of 5 years written as a market figure",
     dict(readings=[seasonal5], summary="US crude stocks could fall 5 next week.")),
    ("LF1: the percentile window of 3 years written as a market figure",
     dict(readings=[hh_obs], summary="Henry Hub could fall 3 next week.")),
    ("LF1: the count of 747 observations written as a price", dict(readings=[hh_obs], summary="Henry Hub could reach 747 by summer.")),
    ("LF1: a count of observations given the noun points, read as an index level",
     dict(readings=[hh_obs], summary="Henry Hub could fall 747 points.")),
    ("LF2: a percentile written as money, the euro sign and a space", dict(readings=[hh_pct], summary="Henry Hub trades at € 65.93.")),
    ("LF2: a percentile written as money, the pound sign glued", dict(readings=[hh_pct], summary="Henry Hub trades at £65.93.")),
    ("LF2: a dollar price written in euros", dict(facts=[hh_fact], summary="Henry Hub is at EUR 3.10 per million Btu.")),
    ("LF2: a dollar price written with the euro sign", dict(facts=[hh_fact], summary="Henry Hub is at €3.10 per million Btu.")),
    ("LF2: a dollar price written in Canadian dollars", dict(facts=[hh_fact], summary="Henry Hub is at C$ 3.10 per million Btu.")),
    ("LF2: a dollar price written in pounds", dict(facts=[brent], summary="Brent futures settled at £93.07 a barrel on 2026-11-17.")),
    ("LF2: a euro price written in dollars", dict(facts=[power_eur], summary="German day-ahead power was $95.40 per MWh.")),
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
    # the adversary's three remaining items (242042f1): a window with its noun, each currency where it is the value's own
    dict(readings=[seasonal5], summary="US crude stocks are below their average for the week over the last 5 years."),
    dict(readings=[hh_obs], summary="Henry Hub is at the 65.93 percentile of 747 observations over 3 years."),
    dict(readings=[hh_obs], summary="Henry Hub is at the 65.93 percentile of 747 data points over 3 years."),
    dict(readings=[hh_obs], summary="Over a 3-year window Henry Hub sits at the 65.93 percentile."),
    dict(facts=[hh_fact], summary="Henry Hub is at USD 3.10 per million Btu."),
    dict(facts=[hh_fact], summary="Henry Hub is at $3.10 per million Btu."),
    dict(facts=[power_eur], summary="German day-ahead power was €95.40 per MWh."),
    dict(facts=[power_eur], summary="German day-ahead power was EUR 95.40 per MWh."),
    dict(facts=[power_eur], summary="German day-ahead power was 95.40 euros per MWh."),
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
    # live-fixes-2b (25 Nov 2026) ships B. A (a percentile written as a place), C and D moved to the lab branch: tying a
    # number or an ordinal to the right noun is one family of work. Kept visible here, accepted by both trees: A's wrong
    # cases as live-fixes-2b had them (6f63817), and its wider wordings
    ("A, moved to the lab branch: the 95th taken from the key p95 as a rank",
     dict(readings=[hh_pct], summary="Henry Hub sits at the 95th percentile.")),
    ("A, moved to the lab branch: the 5th taken from the key p5 as a rank",
     dict(readings=[hh_pct], summary="Henry Hub sits at the 5th percentile.")),
    ("A, moved to the lab branch: the 25th taken from the key p25, with the window after it (a window is no value of the point)",
     dict(readings=[hh_pct], summary="Henry Hub sits at the 25th percentile of its 5-year range.")),
    ("A, moved to the lab branch: is in the 75th, from the key p75",
     dict(readings=[hh_pct], summary="Henry Hub is in the 75th percentile.")),
    ("A, moved to the lab branch: is at its 95th",
     dict(readings=[hh_pct], summary="Henry Hub is at its 95th percentile.")),
    ("A, moved to the lab branch: trades at the 95th",
     dict(readings=[hh_pct], summary="Henry Hub trades at the 95th percentile of its window.")),
    ("A, moved to the lab branch: a rank matched against a price (4.21 rounds to the 4th)",
     dict(readings=[hh_pct], summary="Henry Hub is at the 4th percentile of 5 years.")),
    ("A, moved to the lab branch: a rank written 'the N percentile', matched against a price",
     dict(readings=[hh_pct], summary="Henry Hub is at the 4.21 percentile.")),
    ("A, moved to the lab branch: placed at a point, with the latest value after it (not the point's)",
     dict(readings=[hh_pct], summary="Henry Hub sits at the 95th percentile, at 4.21.")),
    ("A, moved to the lab branch: in raised digits",
     dict(readings=[hh_pct], summary="Henry Hub sits at the ⁹⁵th percentile.")),
    ("A, moved to the lab branch: freight placed at its 95th (it is at the 96.02nd)",
     gold("freight_history", summary="Freight sits at the 95th percentile.")),
    ("A, moved to the lab branch: the crack placed at its 90th (it is at the 87.7th)",
     gold("futures_crack", summary="The crack sits at the 90th percentile.")),
    ("A, moved to the lab branch: funds placed at the 90th (they are at the 10.3rd)",
     gold("wti_positioning", summary="Managed money is at the 90th percentile.")),
    ("A, moved to the lab branch: is currently trading at the 95th",
     dict(readings=[hh_pct], summary="Henry Hub is currently trading at the 95th percentile.")),
    ("A, moved to the lab branch: the latest value in the sentence, the rank wrong",
     gold("henry_hub_percentile", summary="Henry Hub, at 3.10, sits at the 95th percentile.")),
    ("A, moved to the lab branch: the latest value in the subject, with its date (the reading's own), and a point named after it",
     gold("henry_hub_percentile", summary="Henry Hub spot gas at 3.10 dollars on 2026-11-17 sits at the 95th percentile of its "
                                          "last three years, above its 90th percentile line of 3.90.")),
    ("A, moved to the lab branch: a spread's latest value in the subject (it is at the 33.9th)",
     gold("brent_wti_spread", summary="The Brent-WTI spread of 3.41 dollars is at the 90th percentile.")),
    ("A, moved to the lab branch: 'That' pointing at the latest value",
     gold("crack_321", summary="The 3-2-1 crack was 34.85 dollars. That sits at the 90th percentile of the last three years.")),
    ("A, moved to the lab branch: a rank claimed in a wider wording", dict(readings=[hh_pct],
     summary="Henry Hub is trading at a 95th-percentile level.")),
    ("A, moved to the lab branch: placed on a point's line", dict(readings=[hh_pct], summary="Henry Hub sits on its 95th percentile line.")),
    ("A, moved to the lab branch: a point's ordinal alone, placed", dict(readings=[hh_pct], summary="Henry Hub sits at the 95th.")),
    ("A, moved to the lab branch: placed at a point named with its own value", dict(readings=[hh_pct],
     summary="Henry Hub sits at its 95th percentile of 6.90.")),
    ("A, moved to the lab branch: placed in the past", dict(readings=[hh_pct],
     summary="Henry Hub was at the 95th percentile last week.")),
    ("A, moved to the lab branch: a number in the subject that is not the latest value (here the week's change)",
     gold("wti_positioning", summary="The net position fell by 9,900 contracts on the week and sits at the 90th percentile.")),
    ("C, dropped from this branch: a rounded change given the wrong side",
     gold("wti_30d", "us_rigs_yoy", summary="WTI rose 17%; rigs fell 11%.")),
    ("D, moved to the lab branch: a 30-day change called the week's", gold("wti_30d", summary="WTI fell 17.26% over the week.")),
    # live items 1 and 2 were dropped from this branch on 25 Nov 2026 (the review of 89ab3ad: after two rounds each
    # still refused true sentences) and are held on the lab branch with A, C and D. Their wrong cases, accepted by both
    # trees: the side of a change named by its period (the Cushing 7-day case) and the side of a spread written with a
    # comparative (cheaper, dearer, higher, lower than the other series)
    ("live 1, dropped from this branch: the signals' 7-day percent, rounded to one decimal",
     gold("regime_signals", summary="Cushing stocks rose 4.0% on the week.")),
    ("live 1, dropped from this branch: the 7-day percent as returned",
     gold("regime_signals", summary="Cushing stocks rose 4.05% over the week.")),
    ("live 1, dropped from this branch: the 7-day percent rounded to a whole number, with its sign word before it",
     gold("regime_signals", summary="Cushing stocks are up 4% on the week.")),
    ("live 1, dropped from this branch: the 7-day percent with the side word after it",
     gold("regime_signals", summary="Cushing inventories are 4.05% higher than a week ago.")),
    ("live 1, dropped from this branch: the report's wow, in its own unit",
     gold("eia_weekly_brief", summary="Cushing stocks rose 1,209 thousand barrels on the week.")),
    ("live 1, dropped from this branch: the report's wow in million barrels",
     gold("eia_weekly_brief", summary="Cushing stocks built 1.21 million barrels on the week.")),
    ("live 1, dropped from this branch: the report's metric.crude_stock_wow",
     gold("eia_weekly_brief", summary="US crude stocks fell 3.38 million barrels on the week.")),
    ("live 1, dropped from this branch: the report's yoy, the side word after it",
     gold("eia_weekly_brief", summary="Crude stocks are 6,358 thousand barrels higher than a year ago.")),
    ("live 1, dropped from this branch: the report's yoy of a price",
     gold("eia_weekly_brief", summary="Brent is down 28.08 dollars on the year.")),
    ("live 1, dropped from this branch: a 3-month percent",
     dict(readings=[period_sig], summary="EU oil imports rose 12.3% over three months.")),
    ("live 1, dropped from this branch: a qoq with no 'change' in its key",
     dict(readings=[period_sig], summary="The call on OPEC crude rose 0.55 million barrels a day on the quarter.")),
    ("live 1, dropped from this branch: a revision",
     dict(readings=[period_sig], summary="OPEC revised its world demand estimate down by 0.13 million barrels a day.")),
    ("live 1, dropped from this branch: an N-week percent",
     dict(readings=[period_sig], summary="Henry Hub is down 18.5%.")),
    ("live 1, dropped from this branch: a mom",
     dict(readings=[period_rep], summary="US gasoline demand rose 85 thousand barrels per day on the month.")),
    ("live 1, dropped from this branch: a dod",
     dict(readings=[period_rep], summary="WTI fell 0.42 dollars on the day.")),
    ("live 1, dropped from this branch: a chg",
     dict(readings=[period_rep], summary="WTI fell 1.37 dollars.")),
    ("live 1, dropped from this branch: a yoy_pct",
     dict(readings=[period_rep], summary="US crude stocks are up 2.29% on the year.")),
    ("live 1, dropped from this branch: the side word after a long unit, in the present tense, with the change's own period",
     gold("eia_weekly_brief", summary="Crude imports are 1,122 thousand barrels per day higher on the week.")),
    ("live 1, dropped from this branch: a wrong side before a sentence that opens with 'No' and takes nothing back",
     gold("regime_signals", summary="Cushing stocks rose 4.0% on the week. No other hub built as much.")),
    ("live 2, dropped from this branch: 'lower than' with the spread's first series as subject",
     gold("brent_wti_spread", summary="Brent is $3.41 a barrel lower than WTI.")),
    ("live 2, dropped from this branch: 'dearer than' with the second series as subject",
     gold("brent_wti_spread", summary="WTI is $3.41 a barrel dearer than Brent.")),
    ("live 2, dropped from this branch: 'cheaper than'",
     gold("brent_wti_spread", summary="Brent is 3.41 dollars cheaper than WTI.")),
    ("live 2, dropped from this branch: 'higher than'",
     gold("brent_wti_spread", summary="WTI is 3.41 dollars higher than Brent.")),
    ("live 2, dropped from this branch: 'less than'",
     gold("brent_wti_spread", summary="Brent trades 3.41 dollars less than WTI.")),
    ("live 2, dropped from this branch: 'more expensive than'",
     gold("brent_wti_spread", summary="WTI is $3.41 more expensive than Brent.")),
    ("live 2, dropped from this branch: 'less expensive than'",
     gold("brent_wti_spread", summary="Brent is 3.41 dollars a barrel less expensive than WTI.")),
    ("live 2, dropped from this branch: a reading's a_minus_b gap (futures)",
     gold("futures_spread", summary="Brent futures are 8.94 dollars cheaper than WTI futures.")),
    ("live 2, dropped from this branch: the other series named after a verb",
     gold("brent_wti_spread", summary="The gap leaves WTI 3.41 dollars dearer than Brent.")),
    ("live 1, dropped from this branch: a sentence that names another period",
     gold("regime_signals", summary="Cushing stocks are 4.05% higher on the week, but down on the month.")),
    ("live 1, dropped from this branch: a sentence that speaks to the visitor",
     gold("regime_signals", summary="You asked about Cushing: stocks rose 4.05% on the week.")),
    ("live 1, dropped from this branch: the side word after a past tense",
     gold("eia_weekly_brief", summary="Cushing stocks were 1.21 million barrels higher on the week.")),
    ("live 2, dropped from this branch: a comparative before the number",
     gold("brent_wti_spread", summary="Brent is cheaper than WTI by 3.41 dollars.")),
    ("live 2, dropped from this branch: a comparative with a negation after it",
     gold("brent_wti_spread", summary="WTI is 3.41 dollars dearer than Brent, not cheaper.")),
    # item 3 judges only a plain statement in the plain dated level (the review of bb2c261): a wrong sentence it leaves
    # unread, accepted by both trees
    ("live 3, narrow on purpose: any word beyond the plain dated level",
     dict(facts=[wti_far], summary="As of 2026-11-17, WTI spot was still $139.69 a barrel.")),
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
    # live-fixes-2b: each wrong answer must be refused for its own reason, not for another one it happens to trip
    for label, kw, why in FIXES_LF2B:
        found = problems(kw)
        ok = any(why in p for p in found)
        print(f"{'rejected ' if ok else 'ACCEPTED ' if not found else 'WRONG REASON'} {label}"
              + ("" if ok or not found else f"\n          -> {found} (expected '{why}')"))
        failed += not ok
    for kw in FIXES_LF2B_RIGHT:
        found = problems(kw)
        if found:
            print(f"REJECTED a correct answer: {kw['summary']}\n          -> {found}")
        failed += bool(found)
    # a caveat that only looks like code's is the model's, and the validator drops it however it reads (until 25 Nov
    # 2026 only an exact copy of code's opening was dropped)
    from es_agent import prose
    mimic = DeskAnswer(facts=[brent], summary="Brent futures are at 93.07 USD/bbl.",
                       caveats=["Ｎot current as of 2026-11-17: Brent futures M1."])
    kept = prose.clean_caveats(mimic)
    print(f"{'dropped  ' if not kept else 'KEPT     '} a model caveat dressed as code's (full-width N): {kept}")
    failed += bool(kept)
    # live item 1 was dropped from this branch: a caveat that gives a period change the wrong side is kept, as by
    # d029c9c (a known limit), and so is the true one beside it
    sig = DeskAnswer(**gold("regime_signals", summary="Cushing stocks fell 4.05% on the week."),
                     caveats=["Cushing stocks rose 4.05% on the week.", "Cushing stocks are 4.05% lower on the week."])
    kept = prose.clean_caveats(sig)
    ok = kept == sig.caveats
    print(f"{'limit    ' if ok else 'now caught: move it to the wrong cases'} a model caveat giving the 7-day change the "
          f"wrong side (live item 1, dropped): kept {kept}")
    failed += not ok
    # the reviews of bb2c261 and 89ab3ad: their true sentences written as model caveats are kept (those heads dropped
    # them)
    for kw in RIGHT_BB2C261 + RIGHT_89AB3AD:
        body = dict(kw)
        line = body.pop("summary")
        a = DeskAnswer(**body, summary="", caveats=[line])
        kept = prose.clean_caveats(a)
        if kept != [line]:
            print(f"DROPPED  a true caveat: {line}")
        failed += kept != [line]
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
    print(f"{len(WRONG) + len(FIXES_LF2B)} wrong answers, {len(RIGHT) + len(FIXES_LF2B_RIGHT)} right answers "
          f"({len(RIGHT_BB2C261) + len(RIGHT_89AB3AD)} of them also as caveats), {len(golden)} recorded answers, "
          f"{len(LIMIT)} known limits; "
          f"{failed} expectation(s) not met")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
