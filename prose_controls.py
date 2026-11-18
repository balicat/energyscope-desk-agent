"""Control for the prose checks: answers whose tables are true and whose sentences are wrong.

    python prose_controls.py        # exit 1 if any expectation below is not met

The eval suite's control run plants a wrong number in the facts. This plants errors in the
wording, where the tables cannot help: a wrong date, a flipped sign, a number in a caveat. Each
case says what must happen. No model, no data, no cost; it runs in CI and in the release gate.

The first eleven wrong answers came from an adversarial review of the live service on 18 Nov 2026
(a second Claude session given the job of breaking it). Two of them are still accepted and are
kept here marked LIMIT, so the gap stays visible: the checks cannot tell that two true values have
been attached to the wrong nouns, or judge a claim made in words alone.
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
                values={"managed_money_net": 151200.0, "net_change_on_week": 12000.0, "net_percentile": 6.8, "percentile_weeks": 156})
gap = Spread(series_a="PET.RBRTE.D", name_a="Brent spot", series_b="PET.RWTC.D", name_b="WTI spot", units="USD/bbl",
             period=dt.date(2026, 11, 11), value_a=87.48, value_b=88.10, spread=-0.62)
curve = Reading(key="evidence:x", title="Curves", period=D, units="USD/bbl", series_ids=["ICE.BRENT.M1.D"],
                values={"brent_M1_minus_M12": 14.55, "us_stocks_vs_5y_pct": -4.47})

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
    ("a price misquoted by 5%",
     dict(facts=[brent], summary="Brent futures are at 97.72 USD/bbl.")),
    ("falling words only, when every change is a rise",
     dict(facts=[wti_up], summary="WTI fell 1.20 USD/bbl on the week to 88.10.")),
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
]

LIMIT = [  # wrong, and still accepted: what the checks cannot see
    ("two true values attached to the wrong nouns",
     dict(facts=[brent, wti], summary="WTI futures are at 93.07 USD/bbl and Brent futures at 88.10.")),
    ("claims made in words alone",
     dict(facts=[stocks], summary="US crude stocks are 414,417 thousand barrels, a record high, roughly double their ten-year average.")),
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
