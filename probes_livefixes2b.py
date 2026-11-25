"""Probes for live-fixes-2b: the sentences the two reviews of live-fixes-2 (2064ff0, 25 Nov 2026) wrote.

    python probes_livefixes2b.py [--json out.json]     # in a tree's root; exit 1 if a MUST_ACCEPT sentence is refused

Each sentence is checked against the suite's own tool results (results/golden.json, the frozen data), with the tree's
own checker (es_agent in the current directory), so the same file runs on d029c9c and on this branch and the two
outputs can be compared line for line.

- MUST_ACCEPT: every TRUE sentence in the reviewers' evidence. Each was accepted by d029c9c, and a wider rule of
  live-fixes-2 refused it; this branch must accept every one. Plus true sentences with the glyphs the first review
  tried (CO₂, m³, °C, an en dash, the Unicode minus, a narrow no-break space, curly quotes, ™). Plus, since the review
  of 906e707 (25 Nov 2026), every true sentence that review found refused there (a point's value as the subject, a
  premise corrected after the placement, a placement in the past, notation such as R², C₃ and MTCO₂e), and the
  builder's own true sentences in the shapes beside them. Plus the live items' true sentences (25 Nov 2026, 'live
  1' to 'live 3'), each accepted by d029c9c too.
- REFUSED_BOTH: true sentences the reviewers found refused by d029c9c too (older rules, not changed here). Reported.
- MUST_REFUSE: wrong sentences this branch must refuse: the brief's own B sentences (B's footnote marks among them),
  the second review's wrong sentences that d029c9c refuses and a wider rule had let through, and the live items'
  wrong sentences (each accepted by d029c9c).
- LIMIT: the brief's own A sentences and the ones 6f63817 judged. A (a percentile written as a place) was dropped
  from this branch on 25 Nov 2026 and moved to the lab branch, so each is accepted, as on d029c9c; one that is
  refused here is reported as CAUGHT and fails the run, because it would mean A was not fully removed.
- DROPPED: the brief's own C sentence. C is not in this branch, so it is accepted as on d029c9c. Reported.
"""

from __future__ import annotations

import json
import sys

from es_agent import metrics
from es_agent.models import DeskAnswer

with open("results/golden.json", encoding="utf-8") as _f:
    G = json.load(_f)

# a 7-day WTI change, as get_change returns it from the frozen data (the reviewers' wti_7)
WTI_7 = {"series_id": "PET.RWTC.D", "name": "Cushing, OK WTI Spot Price FOB, Daily", "units": "Dollars per Barrel",
         "latest_period": "2026-11-17", "latest_value": 89.53, "lookback_days": 7, "base_period": "2026-11-10",
         "base_value": 89.62, "change_abs": -0.09, "change_pct": -0.100424}

HH, FR, FC = "henry_hub_percentile", "freight_history", "futures_crack"
BWS, POS, C321 = "brent_wti_spread", "wti_positioning", "crack_321"
W30, RIGS, C4W, CYOY, W5, SURP = "wti_30d", "us_rigs_yoy", "cushing_4w", "us_crude_yoy", "wti_five_years", "week_surprises"
SIG, EIA = "regime_signals", "eia_weekly_brief"

MUST_ACCEPT = [  # (where it comes from, golden answers, the sentence)
    # review 1, blocker 1 (D): two windows in one sentence
    ("r1 D", [W30, RIGS], "Over 30 days WTI fell 18.68 dollars and over the past year US rigs rose 58."),
    ("r1 D", [W30, RIGS], "Over the month WTI fell 17.26% and over the year rigs rose 58."),
    ("r1 D", [W30, RIGS], "In the month to 2026-11-17 WTI fell 17.26% and in the year to 2026-11-20 rigs rose 58."),
    ("r1 D", [C4W, CYOY], "Over four weeks Cushing drew 1,447 thousand barrels and over the year US crude stocks fell 9,784."),
    ("r1 D", [W30, W5], "WTI fell 17.26% over 30 days but is up 16.67% over the past five years."),
    ("r1 D", [W30, W5], "WTI is down 17.26% on the month but up 16.67% over five years."),
    ("r1 D", [W30, W5], "WTI fell 17.26% over 30 days and averaged 80.06 over five years."),
    ("r1 D", [W30, W5], "WTI fell 17.26% over 30 days to 89.53 and has ranged from 55.44 to 123.64 over the past five years."),
    ("r1 D", [RIGS, SURP], "US rigs rose 58 over the year and 6 over the week."),
    # review 1, blocker 2 (A): a place said not to hold, or only as a condition
    ("r1 A", [FR], "Freight has not fallen below its 90th percentile line (268.00) since 2026-07-31, 112 days."),
    ("r1 A", [FR], "Freight is not below its 90th percentile line; it is at the 96th."),
    ("r1 A", [FR], "The spell ends when freight falls back below its 90th percentile line of 268.00."),
    ("r1 A", [HH], "Henry Hub is not above its 90th percentile line (3.90)."),
    ("r1 A", [HH], "Henry Hub isn't above its 90th percentile line of 3.90."),
    ("r1 A", [HH], "Henry Hub would need to rise above its 90th percentile line of 3.90 to look stretched."),
    ("r1 A", [HH], "If Henry Hub rose above its 90th percentile of 3.90, it would be outside its usual range."),
    ("r1 A", [HH], "Henry Hub would have to climb to its 95th percentile of 4.36 before it looked expensive."),
    ("r1 A", [HH], "Henry Hub at 3.10 is no longer above its 75th percentile of 3.22."),
    ("r1 A", [HH], "Henry Hub at 3.10 is neither above its 90th percentile (3.90) nor below its 10th (1.83)."),
    ("r1 A", [FC], "The crack would need to rise above its 90th percentile line of 44.98 to look extreme."),
    # review 1, minors: C's true control and the ellipsis
    ("r1 C", [W30, RIGS], "WTI plunged 17% and rigs rose 11%."),
    ("r1 C", [W30, RIGS], "WTI plunged 17% over 30 days."),
    ("r1 B", [W30], "WTI fell… 17.26% over 30 days, to 89.53 dollars."),
    # review 2, blocker 2 (D): an opening window word
    ("r2 D", ["wti_7", RIGS], "As WTI slipped over the week, US rigs rose 58 over the year."),
    ("r2 D", [W30, RIGS], "While WTI fell over the month, rigs rose 58 over the year."),
    ("r2 D", [W30, RIGS], "After WTI's slide over the month, rigs are up 10.56% on the year."),
    ("r2 D", [W30, RIGS], "Unlike WTI over the month, rigs rose 10.56% year on year."),
    ("r2 D", [W30, RIGS], "While WTI tumbled over the month, the rig count is 11% higher than a year ago."),
    ("r2 D", [W30, CYOY], "Over the month WTI weakened, and US crude stocks fell 9,784 thousand barrels over the year."),
    # review 2, blocker 3 (A): a percentile point named with its value, and frames that place nothing
    ("r2 A", [HH], "The 95th percentile of the window is 4.36."),
    ("r2 A", [HH], "The 95th percentile for Henry Hub is 4.36."),
    ("r2 A", [HH], "The 95th percentile in the three-year window is 4.36."),
    ("r2 A", [HH], "The 90th percentile, at 3.90, is the line to watch."),
    ("r2 A", [HH], "The 75th percentile, at 3.22, is just above today's 3.10."),
    ("r2 A", [HH], "Henry Hub's 75th percentile over the window is 3.22, just above today's 3.10."),
    ("r2 A", [HH], "Henry Hub has some way to go before it reaches its 95th percentile of 4.36."),
    ("r2 A", [HH], "Henry Hub would need to climb above 4.36 to pass its 95th percentile."),
    ("r2 A", [HH], "Henry Hub is well short of its 95th percentile."),
    ("r2 A", [HH], "Henry Hub is nowhere near its 95th percentile."),
    # review 2, blocker 4 (C): a rounded change with its direction as a noun, or a word on no list
    ("r2 C", [W30, RIGS], "WTI posted a 17% fall over 30 days."),
    ("r2 C", [W30, RIGS], "WTI posted a 17% drop over 30 days."),
    ("r2 C", [W30, RIGS], "A 17% fall over 30 days leaves WTI at 89.53."),
    ("r2 C", [W30, RIGS], "A 17% decline over the month left WTI at 89.53."),
    ("r2 C", [W30, RIGS], "Rigs posted an 11% rise over the year."),
    ("r2 C", [W30, RIGS], "WTI's 17% fall over 30 days contrasts with an 11% rise in rigs over the year."),
    ("r2 C", [W30, RIGS], "WTI is 17% cheaper than 30 days ago."),
    ("r2 C", [W30, RIGS], "WTI is 17% weaker than 30 days ago."),
    ("r2 C", [W30, RIGS], "Rigs are 11% more than a year ago."),
    ("r2 C", [W30, RIGS], "WTI weakened 17% over 30 days."),
    ("r2 C", [W30, RIGS], "WTI is off 17% over 30 days."),
    ("r2 C", [W30, RIGS], "WTI sagged 17% over 30 days."),
    ("r2 C", [W30, RIGS], "WTI has given up 17% over 30 days."),
    # review 2, blocker 5 (C): another series' move verb before the number
    ("r2 C", [W30, RIGS], "Even after WTI plunged, rigs are 10.56% higher year on year."),
    ("r2 C", [W30, RIGS], "Rigs, which climbed as WTI plunged, are 10.56% higher than a year ago."),
    # review 1: the glyphs it tried, which must still pass (sentences of this branch, in the reviewers' terms)
    ("r1 B glyphs", [W30], "WTI fell 17.26% over 30 days, to 89.53 dollars; no series here is quoted in m³, km², °C or tCO₂e."),
    ("r1 B glyphs", [W30], "WTI fell 17.26% over 30 days, to 89.53 dollars, a price that does not include the cost of CO₂."),
    ("r1 B glyphs", [W30], "WTI fell 17.26% over 30 days – to 89.53 dollars."),
    ("r1 B glyphs", [W30], "WTI's 30-day change was −18.68 dollars, to 89.53."),
    ("r1 B glyphs", [W30], "WTI fell 17.26% over 30 days, to 89.53\u202fdollars."),
    ("r1 B glyphs", [W30], "WTI’s fall over 30 days was 17.26%, to “89.53” dollars."),
    ("r1 B glyphs", [W30], "WTI™ fell 17.26% over 30 days, to 89.53 dollars."),
    # review of 906e707 (25 Nov 2026), blocker (A): a percentile point named by its own value as the subject
    ("r3 A", [HH], "A price of 4.36 is at the 95th percentile of the three-year window."),
    ("r3 A", [HH], "4.36 sits at the 95th percentile of Henry Hub's three-year range."),
    ("r3 A", [HH], "A Henry Hub price of 3.90 is in the 90th percentile of the window."),
    ("r3 A", [HH], "The 3.22 mark is at the 75th percentile."),
    ("r3 A", [HH], "Henry Hub's upper tail starts at 4.36, which is at the 95th percentile."),
    ("r3 A", [HH], "A value of 1.58 sits at the 5th percentile, and 4.36 sits at the 95th."),
    ("r3 A", [HH], "Henry Hub's window runs from 1.21 to 30.72; 3.90 is at its 90th percentile."),
    ("r3 A", [HH], "Henry Hub's 3.10 sits at the 66th percentile, while 3.22 is at the 75th percentile."),
    ("r3 A", [HH], "Today's 3.10 is at the 66th percentile, and 3.90 is at the 90th percentile."),
    ("r3 A", [HH], "Prices at 3.90 are at the 90th percentile of Henry Hub's three-year window."),
    ("r3 A", [HH], "The 90th percentile line is 3.90: a price there is at the 90th percentile."),
    ("r3 A", [FC], "A crack of 44.98 is at the 90th percentile of the window."),
    ("r3 A", [FC], "Today's 41.13 crack is in the 88th percentile, while 44.98 is at the 90th percentile."),
    ("r3 A", [C321], "A crack of 56.87 dollars is at the 90th percentile and one of 14.69 dollars at the 10th."),
    ("r3 A", [BWS], "A spread of 9.71 dollars is at the 90th percentile."),
    ("r3 A", [BWS], "The spread is at the 34th percentile; a spread of 2.03 dollars is at the 10th percentile and 9.71 "
                    "dollars at the 90th."),
    ("r3 A", [POS], "Net length of 15,814 contracts is in the 10th percentile, and 191,531 contracts is at the 90th "
                    "percentile."),
    ("r3 A", [FR], "A freight level of 268.00 is at the 90th percentile of the window; today's 745.77 is at the 96th "
                   "percentile."),
    # ... a premise corrected, with the negation or the correction after the placement
    ("r3 A", [HH], "The premise that Henry Hub is at its 95th percentile does not hold: it sits at the 66th."),
    ("r3 A", [HH], "The idea that Henry Hub trades in the 95th percentile is wrong; it is at the 66th percentile."),
    ("r3 A", [HH], "It is false that Henry Hub is at the 95th percentile; it is at the 66th."),
    ("r3 A", [HH], "You suggest Henry Hub is at the 95th percentile; the data puts it at the 66th."),
    ("r3 A", [HH], "The claim that Henry Hub sits at the 95th percentile is wrong: the data put it at the 66th."),
    ("r3 A", [HH], "That Henry Hub is at its 95th percentile isn't true; it is at its 66th."),
    ("r3 A", [HH], "Henry Hub is at its 95th percentile only in the question; in the data it is at its 66th percentile."),
    ("r3 A", [HH], "The visitor's figure, that Henry Hub is in the 95th percentile, does not match the data: it is in the "
                   "66th percentile."),
    # ... plausible, and not checkable from the tools: the past, a date, a question
    ("r3 A", [FR], "Freight was in the 90th percentile on 2026-07-31 and is in the 96th now."),
    ("r3 A", [FR], "On 2026-07-31 freight was at the 90th percentile; it has stayed above that line for 112 days."),
    ("r3 A", [HH], "Henry Hub was at the 95th percentile? No: it is at the 66th percentile."),
    # review of 906e707, minor (B): notation, not a footnote (d029c9c accepted each)
    ("r3 B", [W30], "No R² is computed here; WTI fell 17.26% over 30 days."),
    ("r3 B", [W30], "Propane (C₃) is not covered; WTI fell 17.26% over 30 days."),
    ("r3 B", [W30], "Condensate (C₅+) is not covered; WTI fell 17.26% over 30 days."),
    ("r3 B", [W30], "Emissions in MTCO₂e are not covered; WTI fell 17.26% over 30 days."),
    ("r3 B", [W30], "Emissions in MMtCO₂e are not covered; WTI fell 17.26% over 30 days."),
    ("r3 B", [W30], "Intensity in lbCO₂ per barrel is not covered; WTI fell 17.26% over 30 days."),
    ("r3 B", [W30], "The variance σ² is not shown; WTI fell 17.26% over 30 days."),
    # the builder's own true sentences beside those shapes (each accepted by d029c9c, and most refused by 906e707)
    ("fix A", [HH], "The upper quartile is at the 75th percentile."),
    ("fix A", [HH], "Henry Hub's upper quartile, 3.22, is at the 75th percentile."),
    ("fix A", [HH], "A price of 3.90 sits at the 90th percentile, and Henry Hub at 3.10 sits at the 66th."),
    ("fix A", [HH], "A stretched market is in the 90th percentile."),
    ("fix A", [HH], "At 4.36, Henry Hub is at its 95th percentile."),
    ("fix A", [HH], "Some say Henry Hub is at its 95th percentile, but it is at its 66th."),
    ("fix A", [FR], "Today freight is in the 96th percentile; on 2026-07-31 it was in the 90th percentile."),
    ("fix A", [HH], "Henry Hub's 4.36 upper threshold is at the 95th percentile."),
    ("fix A", [HH], "Henry Hub trades at 3.10, and 4.36 is at the 95th percentile."),
    ("fix A", [HH], "Henry Hub is in the 95th percentile? It is not: it is in the 66th."),
    ("fix A", [HH], "To say Henry Hub is at the 95th percentile is wrong: it is at the 66th."),
    ("fix A", [HH], "Henry Hub, at 3.10, is at the 66th percentile, and a price of 4.36 is at the 95th percentile."),
    ("fix A", [POS], "A net length of 191,531 contracts is at the 90th percentile."),
    ("fix A", [HH], "Henry Hub is at the 95th percentile in the visitor's question and at the 66th percentile in the data."),
    ("fix A", [HH], "Henry Hub is at the 95th percentile only if the window is cut short."),
    ("fix A", [HH], "Prices above 4.36 are in the 95th percentile."),
    ("fix A", [HH], "The 90th percentile is 3.90. A price there is at the 90th percentile."),
    ("fix A", [HH], "Such a price is at the 95th percentile."),
    ("fix A", [HH], "The premise is that Henry Hub sits at the 95th percentile; it sits at the 66th."),
    ("fix A", [HH], "The market thinks Henry Hub is at its 95th percentile; the data put it at the 66th."),
    ("fix A", [HH], "Henry Hub is at the 95th percentile on a misreading of the window; it is at the 66th."),
    ("fix A", [HH], "Henry Hub is instead at the 66th percentile, and it is at the 95th percentile nowhere in the data."),
    ("fix A", [FR], "Freight was in the 90th percentile then and is in the 96th percentile now."),
    ("fix A", [FR], "Freight was at the 90th percentile 112 days ago and is at the 96th percentile today."),
    ("fix A", [HH], "Two levels matter: 3.90 is at the 90th percentile, and 4.36 is at the 95th percentile."),
    ("fix A", [FC], "The crack sits at the 88th percentile; a crack of 44.98 dollars is at the 90th percentile."),
    ("fix A", [HH], "Henry Hub is currently trading at the 66th percentile."),
    # ... and true sentences in the shapes the rule still judges: the latest value (with its own date) in the subject,
    # a point named after the placement, "That" for the latest value, "at most", a pronoun for a point named before
    ("fix A", [HH], "Henry Hub spot gas at 3.10 dollars on 2026-11-17 sits at the 66th percentile of its last three years, "
                    "above its median."),
    ("fix A", [HH], "Henry Hub at 3.10 is in the 75th percentile at most."),
    ("fix A", [BWS], "The Brent-WTI spread of 3.41 dollars is at the 34th percentile."),
    ("fix A", [C321], "The 3-2-1 crack was 34.85 dollars. That sits at the 77th percentile of the last three years."),
    ("fix A", [HH], "Henry Hub at 3.10 sits at the 66th percentile, below the 75th percentile of 3.22 and above the 25th of "
                    "2.44."),
    ("fix A", [FR], "Freight at 745.77 is at the 96th percentile, above its 95th percentile of 703.44."),
    ("fix A", [FR], "Freight at 745.77 is in the 90th percentile and above."),
    ("fix A", [HH], "Henry Hub was 3.10 dollars on 2026-11-17. That sits at the 66th percentile."),
    ("fix A", [HH], "That level is at the 66th percentile, inside the band."),
    ("fix A", [BWS], "The Brent-WTI spread of 3.41 dollars is at the 10th percentile or above."),
    ("fix A", [FC], "The crack of 41.13 is in the 88th percentile, short of its 90th percentile of 44.98."),
    ("fix A", [FR], "Freight crossed its 90th percentile line on 2026-07-31. That sits at the 90th percentile."),
    ("fix A", [HH], "Henry Hub's 95th percentile is 4.36. It is at the 95th percentile by definition."),
    ("fix A", [HH], "The upper quartile begins at 3.22. That is at the 75th percentile."),
    ("fix A", [HH], "Watch the 90th percentile, which sits at the 90th percentile by definition."),
    ("fix A", [POS], "Net length of 15,814 contracts sits at the 10th percentile of 156 weeks."),
    ("fix A", [HH, FR], "Henry Hub at 3.10 sits at the 66th percentile and freight at 745.77 at the 96th percentile."),
    ("fix B", [W30], "WTI fell 17.26% over 30 days, a price that leaves out the cost of CO²."),
    ("fix B", [W30], "WTI fell 17.26% over 30 days; gas in Gm³ is not covered."),
    ("fix B", [W30], "WTI fell 17.26% over 30 days; volumes in hm³ and dam³ are not covered."),
    ("fix B", [W30], "WTI fell 17.26% over 30 days; no χ² test is run."),
    ("fix B", [W30], "WTI fell 17.26% over 30 days; C₂+ liquids are not covered."),
    ("fix B", [W30], "WTI is at $⁸⁹.⁵³ after falling ¹⁷.²⁶% over 30 days."),
    # review of 6f63817 (25 Nov 2026), minor (B): notation must still pass once a lowered digit after a currency code
    # or a plain word is read as a number
    ("r4 B", [W30], "WTI fell 17.26% over 30 days; CO₂, C₃, MTCO₂e and lbCO₂ are not covered."),
    ("r4 B", [W30], "WTI fell 17.26% over 30 days; As₂O₃, In₂O₃, Na₂CO₃ and H₂SO₄ are not energy series."),
    ("r4 B", [W30], "WTI fell 17.26% over 30 days; no regression on x₁ or log₁₀ of the price is run."),
    # live item 1 (25 Nov 2026): true sentences about the signals' 7-day percent (metric.cushing_7d_pct -4.05) and the
    # eia_weekly report's wow and yoy, in the shapes the period-change rule reads and beside them
    ("live 1", [SIG], "Cushing stocks fell 4.0% on the week."),
    ("live 1", [SIG], "Cushing stocks fell 4.05% over the week."),
    ("live 1", [SIG], "Cushing stocks are down 4% on the week."),
    ("live 1", [SIG], "Cushing stocks are 4.05% lower than a week ago."),
    ("live 1", [SIG], "Cushing's 7-day change is -4.05%."),
    ("live 1", [SIG], "Cushing stocks have given up 4.05% over the week."),
    ("live 1", [SIG], "Cushing stocks did not rise; they fell 4.05% over the week."),
    ("live 1", [SIG], "Cushing stocks drew 4.05% on the week, even as refinery runs rose."),
    ("live 1", [SIG], "As refinery runs rose, Cushing stocks fell 4.05% on the week."),
    ("live 1", [SIG], "Even after crude stocks rose, Cushing is 4.05% lower on the week."),
    ("live 1", [SIG], "Refinery runs rose and Cushing stocks ended 4.05% lower on the week."),
    ("live 1", [SIG], "Cushing stocks posted a 4.05% weekly draw."),
    ("live 1", [SIG], "The Cushing 7-day percent change is 4.05% down."),
    ("live 1", [SIG], "Cushing stocks are not up 4.05% on the week; they are down 4.05%."),
    ("live 1", [SIG], "Cushing stocks, which rose last month, fell 4.05% this week."),
    ("live 1", [SIG], "Cushing stocks ended the week 4.05% down."),
    ("live 1", [SIG], "Cushing stocks are 4% lower on the week, with the z-score at 0.49."),
    ("live 1", [SIG], "The call on OPEC crude rose 0.55 million barrels a day on the quarter, while Cushing fell 4.05% on the week."),
    ("live 1", [EIA], "Cushing stocks fell 1,209 thousand barrels on the week."),
    ("live 1", [EIA], "Cushing stocks drew 1.21 million barrels on the week, while crude stocks rose 3.38 million."),
    ("live 1", [EIA], "US crude stocks rose 3.38 million barrels, gasoline 5.19 million and distillate 1.57 million."),
    ("live 1", [EIA], "Crude stocks are 6,358 thousand barrels lower than a year ago."),
    ("live 1", [EIA], "Brent is up 28.08 dollars on the year."),
    ("live 1", [EIA], "Regular gasoline fell 0.19 dollars a gallon on the week."),
    ("live 1", [EIA], "Crude imports fell 1,122 thousand barrels per day on the week, and production rose 19 thousand barrels per day."),
    ("live 1", [EIA], "Gasoline stocks rose 5.19 million barrels while Cushing fell 1.21 million barrels."),
    ("live 1", [EIA], "Distillate stocks rose 1.57 million barrels on the week but are 6.18 million barrels lower than a year ago."),
    ("live 1", [EIA], "Crude oil stocks were 417,797 thousand barrels, up 3,380 on the week and down 6,358 on the year."),
    ("live 1", [EIA], "Cushing stocks fell 1,209 thousand barrels to 26,147 even as crude stocks rose 3,380."),
    ("live 1", [EIA], "As Cushing drew 1.21 million barrels, total crude stocks rose 3.38 million."),
    ("live 1", [EIA], "WTI rose 0.29 dollars on the week, and Brent is up 0.04."),
    ("live 1", [EIA], "Brent rose 28.08 dollars on the year to 92.94, while WTI is 28.02 dollars higher than a year ago."),
    ("live 1", [EIA], "Refinery utilization rose 5.7 percentage points on the year, to 95.7%."),
    ("live 1", [EIA], "Crude stocks rose 3.38 million barrels on the week, though they are 6.36 million barrels below last year."),
    ("live 1", [EIA], "Regular gasoline gave up 0.19 dollars a gallon on the week."),
    ("live 1", [EIA], "Crude imports dropped by 1,122 thousand barrels per day; Cushing lost 1.21 million barrels."),
    ("live 1", [EIA], "SPR stocks fell 3.17 million barrels on the week and 134.56 million on the year."),
    ("live 1", [EIA], "Propane/propylene stocks rose 12 thousand barrels on the week."),
    ("live 1", [SIG], "Rising runs took 4.05% off Cushing stocks on the week."),
    ("live 1", [SIG], "Higher refinery runs pulled Cushing stocks 4.05% lower on the week."),
    ("live 1", [SIG], "Strong refinery demand drained 4.05% from Cushing over the week."),
    ("live 1", [SIG], "Cushing stocks fell back 4.05% on the week after rising the week before."),
    ("live 1", [SIG], "Up north, Cushing stocks fell 4.05% on the week."),
    ("live 1", [SIG], "Cushing, up in the summer, fell 4.05% on the week."),
    ("live 1", [SIG], "Cushing stocks moved down 4.05% on the week."),
    ("live 1", [SIG], "Cushing stocks are 4.05% below where they were a week ago."),
    ("live 1", [SIG], "Cushing stocks shrank 4.05% on the week."),
    ("live 1", [SIG], "Cushing stocks dipped 4.05% on the week."),
    ("live 1", [SIG], "Cushing stocks fell 4.05% on the week to their lowest since the summer."),
    ("live 1", [SIG], "Cushing stocks increased their draw, down 4.05% on the week."),
    ("live 1", [SIG], "Cushing stocks gained no ground, down 4.05% on the week."),
    ("live 1", [EIA], "Crude stocks built 3.38 million barrels on the week while Cushing drew 1.21 million."),
    ("live 1", [EIA], "Crude stocks rose by 3,380 thousand barrels, the first build in three weeks."),
    ("live 1", [EIA], "Gasoline rose 0.01 dollars a gallon at NY Harbor."),
    ("live 1", [EIA], "Higher imports would have lifted stocks, but crude imports fell 1,122 thousand barrels per day."),
    ("live 1", [EIA], "Brent, up 28.08 dollars on the year, now trades at 92.94."),
    ("live 1", [EIA], "Total gasoline stocks rose 5.19 million barrels, a 1.55-sigma move."),
    ("live 1", [EIA], "Cushing stocks were down 1.21 million barrels, and crude stocks were up 3.38 million."),
    ("live 1", [SIG], "Cushing stocks fell more than 4% on the week."),
    ("live 1", [SIG], "Cushing stocks fell a little less than 4.05% on the week."),
    ("live 1", [SIG], "WTI rose more than Brent, while Cushing stocks fell 4.05% on the week."),
    ("live 1", [SIG], "Cushing stocks fell faster than crude stocks rose, down 4.05% on the week."),
]

REFUSED_BOTH = [  # true, and refused by d029c9c as well (the second review's last minor; the first review's third)
    ("r1 minor", [RIGS], "US rigs rose 58 year on year, to 607."),
    ("r2 minor", [RIGS], "Rigs rose 58 year on year to 607."),
    ("r2 minor", [RIGS], "Rigs are up 58 year on year."),
    ("r2 minor", [RIGS], "US rigs rose 58 over the past 12 months."),
    ("r2 minor", [RIGS], "US rigs rose 58 over 52 weeks."),
    ("r2 minor", [W30], "WTI fell 17.26% over 22 trading days."),
    ("r2 minor", [HH], "Henry Hub is above its 50th percentile."),
]

MUST_REFUSE = [  # wrong; (where it comes from, golden answers, the sentence)
    # the brief's B: raised and lowered digits
    ("brief B", [W30], "WTI will reach $¹⁵⁰ by spring."),
    ("brief B", [W30], "WTI could fall to $₈₀."),
    ("brief B", [RIGS], "US rigs are up ¹⁴% on the year."),
    # the brief's B, footnote marks: after a word, a stop or a percent sign (d029c9c read none of them)
    ("brief B", [W30], "WTI² fell 17.26% over 30 days."),
    ("brief B", [W30], "WTI fell 17.26% over 30 days.¹"),
    ("brief B", [W30], "WTI fell 17.26%¹ over 30 days."),
    ("brief B", [W30], "WTI fell 17.26% over 30 days (EIA)²."),
    # review of 6f63817, minor (B): a lowered digit after a currency code or a plain word is a number
    ("r4 B", [W30], "WTI could fall to USD₈₀."),
    ("r4 B", [W30], "WTI could fall to₈₀ dollars."),
    # live item 1: a change named by its period given the wrong side (d029c9c read no side for these keys)
    ("live 1", [SIG], "Cushing stocks rose 4.0% on the week."),
    ("live 1", [SIG], "Cushing stocks rose 4.05% over the week."),
    ("live 1", [SIG], "Cushing stocks are up 4% on the week."),
    ("live 1", [SIG], "Cushing stocks climbed 4.05% in seven days."),
    ("live 1", [SIG], "Cushing inventories are 4.05% higher than a week ago."),
    ("live 1", [EIA], "Cushing stocks rose 1,209 thousand barrels on the week."),
    ("live 1", [EIA], "Cushing stocks rose 1.21 million barrels on the week."),
    ("live 1", [EIA], "US crude stocks fell 3.38 million barrels on the week."),
    ("live 1", [EIA], "Crude stocks are 6,358 thousand barrels higher than a year ago."),
    ("live 1", [EIA], "Brent is down 28.08 dollars on the year."),
    ("live 1", [EIA], "Regular gasoline rose 0.19 dollars a gallon on the week."),
    ("live 1", [EIA], "Crude imports rose 1,122 thousand barrels per day on the week."),
    ("live 1", [EIA], "Refinery utilization fell 5.7 percentage points on the year."),
    ("live 1", [SIG], "Cushing stocks rose by a further 4.05% on the week."),
    ("live 1", [SIG], "Cushing stocks rose more than 4% on the week."),
    ("live 1", [EIA], "Cushing stocks built 1.21 million barrels on the week."),
    ("live 1", [SIG], "Cushing stocks rose more than 4% on the week, the steepest climb in months."),
    # review 2, blocker 1: a change against its own past with the wrong window, refused by d029c9c for want of rose or
    # fell; a wider rule read "below where it was" as the direction word and let them through
    ("r2 own past", [W30], "WTI is 17.26% below where it was a week ago."),
    ("r2 own past", [W30], "WTI is 17.26% below a week ago."),
    ("r2 own past", [W30], "WTI is 17.26% below its level of a week ago."),
    ("r2 own past", [W30], "WTI is 18.68 dollars below where it was a week ago."),
    ("r2 own past", [W30, "wti_7"], "WTI is 17.26% below where it was 7 days ago."),
    ("r2 own past", [RIGS], "Rigs are 10.56% above where they were a month ago."),
    ("r2 own past", [RIGS], "Rigs are 58 above their level a month ago."),
    ("r2 own past", [C4W], "Cushing stocks are 5.24% below where they were a year ago."),
    ("r2 own past", [W30], "WTI rose 17.26% (below where it was 30 days ago)."),
]

LIMIT = [  # wrong, and accepted here as on d029c9c: item A, a percentile written as a place, moved to the lab branch
    # the brief's A: a key's N placed as the rank (Henry Hub is at its 65.93rd percentile)
    ("brief A", [HH], "Henry Hub sits at the 95th percentile."),
    ("brief A", [HH], "Henry Hub sits at the 5th percentile."),
    ("brief A", [HH], "Henry Hub sits at the 25th percentile."),
    ("brief A", [HH], "Henry Hub sits at the 75th percentile."),
    ("brief A", [HH], "Henry Hub is at its 90th percentile."),
    ("brief A", [HH], "Henry Hub trades in the 90th percentile of its three-year range."),
    # ... and in the shapes 6f63817 judged (a present-tense placement of the latest value, plainly made)
    ("brief A", [HH], "Henry Hub is now at the 95th percentile."),
    ("brief A", [HH], "Henry Hub, at 3.10, sits at the 95th percentile."),
    ("brief A", [HH], "Henry Hub's price, which sits at the 95th percentile, looks rich."),
    ("brief A", [HH], "Henry Hub is currently trading at the 95th percentile."),
    ("brief A", [FR], "Freight sits at the 95th percentile."),
    ("brief A", [HH], "Henry Hub spot gas at 3.10 dollars on 2026-11-17 sits at the 95th percentile of its last three "
                      "years, above its 90th percentile line of 3.90."),
    ("brief A", [BWS], "The Brent-WTI spread of 3.41 dollars is at the 90th percentile."),
    ("brief A", [C321], "The 3-2-1 crack was 34.85 dollars. That sits at the 90th percentile of the last three years."),
    ("brief A", [FR], "Freight at 745.77 is at the 90th percentile of its three-year window."),
    ("brief A", [POS], "Managed money net length of 15,814 contracts sits at the 90th percentile."),
]

DROPPED = [  # wrong; the brief's C, accepted here as on d029c9c because C is not in this branch
    ("brief C", [W30, RIGS], "WTI rose 17%; rigs fell 11%."),
]


def answer(names: list[str], summary: str) -> DeskAnswer:
    body = {"facts": [], "spreads": [], "readings": [], "summary": summary}
    for n in names:
        if n == "wti_7":
            body["facts"].append(WTI_7)
            continue
        for part in ("facts", "spreads", "readings"):
            body[part] += G[n].get(part, [])
    a = DeskAnswer(**body)
    a.summary = metrics.tidy(a.summary)
    return a


def problems(names: list[str], summary: str) -> list[str]:
    a = answer(names, summary)
    return metrics.untraceable_numbers(a) + metrics.direction_problems(a)


def main() -> int:
    out, failed = {}, 0
    for group, cases, expect in (("MUST_ACCEPT", MUST_ACCEPT, "accept"), ("REFUSED_BOTH", REFUSED_BOTH, None),
                                 ("MUST_REFUSE", MUST_REFUSE, "refuse"), ("LIMIT", LIMIT, "limit"), ("DROPPED", DROPPED, None)):
        for where, names, summary in cases:
            found = problems(names, summary)
            out.setdefault(group, []).append({"where": where, "summary": summary, "problems": found})
            bad = (expect in ("accept", "limit") and found) or (expect == "refuse" and not found)
            failed += bool(bad)
            mark = ("refused " if found else "ACCEPTED") if expect == "refuse" else (
                ("CAUGHT  " if found else "limit   ") if expect == "limit" else ("REFUSED " if found else "accepted"))
            print(f"{group:12} {mark} {'<- NOT MET ' if bad else ''}[{where}] {summary}" + (f"\n             -> {found}" if found else ""))
    print(f"{len(MUST_ACCEPT)} must accept, {len(REFUSED_BOTH)} refused by both, {len(MUST_REFUSE)} must refuse, "
          f"{len(LIMIT)} known limits, {len(DROPPED)} dropped item; {failed} expectation(s) not met")
    if "--json" in sys.argv:
        with open(sys.argv[sys.argv.index("--json") + 1], "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
