"""Probes for live-fixes-2b: the sentences the two reviews of live-fixes-2 (2064ff0, 25 Nov 2026) wrote.

    python probes_livefixes2b.py [--json out.json]     # in a tree's root; exit 1 if a MUST_ACCEPT sentence is refused

Each sentence is checked against the suite's own tool results (results/golden.json, the frozen data), with the tree's
own checker (es_agent in the current directory), so the same file runs on d029c9c and on this branch and the two
outputs can be compared line for line.

- MUST_ACCEPT: every TRUE sentence in the reviewers' evidence. Each was accepted by d029c9c, and a wider rule of
  live-fixes-2 refused it; this branch must accept every one. Plus true sentences with the glyphs the first review
  tried (CO₂, m³, °C, an en dash, the Unicode minus, a narrow no-break space, curly quotes, ™).
- REFUSED_BOTH: true sentences the reviewers found refused by d029c9c too (older rules, not changed here). Reported.
- MUST_REFUSE: wrong sentences this branch must refuse: the brief's own A and B sentences, and the second review's
  wrong sentences that d029c9c refuses and a wider rule had let through.
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
W30, RIGS, C4W, CYOY, W5, SURP = "wti_30d", "us_rigs_yoy", "cushing_4w", "us_crude_yoy", "wti_five_years", "week_surprises"

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
    # the brief's A: a key's N placed as the rank (Henry Hub is at its 65.93rd percentile)
    ("brief A", [HH], "Henry Hub sits at the 95th percentile."),
    ("brief A", [HH], "Henry Hub sits at the 5th percentile."),
    ("brief A", [HH], "Henry Hub sits at the 25th percentile."),
    ("brief A", [HH], "Henry Hub sits at the 75th percentile."),
    ("brief A", [HH], "Henry Hub is at its 90th percentile."),
    ("brief A", [HH], "Henry Hub trades in the 90th percentile of its three-year range."),
    # the brief's B: raised and lowered digits
    ("brief B", [W30], "WTI will reach $¹⁵⁰ by spring."),
    ("brief B", [W30], "WTI could fall to $₈₀."),
    ("brief B", [RIGS], "US rigs are up ¹⁴% on the year."),
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
                                 ("MUST_REFUSE", MUST_REFUSE, "refuse"), ("DROPPED", DROPPED, None)):
        for where, names, summary in cases:
            found = problems(names, summary)
            out.setdefault(group, []).append({"where": where, "summary": summary, "problems": found})
            bad = (expect == "accept" and found) or (expect == "refuse" and not found)
            failed += bool(bad)
            mark = ("REFUSED " if found else "accepted") if expect != "refuse" else ("refused " if found else "ACCEPTED")
            print(f"{group:12} {mark} {'<- NOT MET ' if bad else ''}[{where}] {summary}" + (f"\n             -> {found}" if found else ""))
    print(f"{len(MUST_ACCEPT)} must accept, {len(REFUSED_BOTH)} refused by both, {len(MUST_REFUSE)} must refuse, "
          f"{len(DROPPED)} dropped item; {failed} expectation(s) not met")
    if "--json" in sys.argv:
        with open(sys.argv[sys.argv.index("--json") + 1], "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
