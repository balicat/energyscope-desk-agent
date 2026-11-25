"""Playbooks as data (exploration, branch `leads`; design: TheLibrarian/playbooks-and-hints.html).

A playbook is an analyst's routine: when it applies, the steps, the notes, what a good answer must say. The steps a
reading already does are `done`; each remaining step becomes a lead, a ready-to-run call of an EnergyScope MCP
tool. Plain dicts, no code: es_agent/leads.py binds the templates to the cited reading and builds the answer's
`deeper` part after the model has replied. The model never sees any of this.

Lead templates: {"step", "why", "tool", "args"} where string values in args hold {slots} filled from the
triggering reading (see leads.slots). "each": "<slot>" repeats the lead for every item of a list slot (the item's
keys are then available as slots too). A step whose tool is not on the MCP server has "tool": None and
"proposed_tool": the name it would have, so the gap shows.
"""

from __future__ import annotations

PLAYBOOKS: list[dict] = [
    {
        "id": "two-measures-disagree",
        "version": 1,
        "title": "Two measures of the same thing disagree",
        # reading keys by prefix (the part before the first colon)
        "when": ["fspread", "fcrack", "crack", "arb"],
        "steps": {
            1: "Like for like: same delivery month, same date, same unit; say what was mismatched.",
            2: "Bridge: split the difference into parts that add up exactly.",
            3: "How unusual: rank each part against its own history.",
            4: "Drift or steps: when did each part change; does it move daily or hold a level.",
            5: "Data check: one-day jumps that reverse; the same value days running.",
            6: "Limits: what the data cannot show; label untested causes as unproven.",
        },
        # steps the triggering reading already does, by reading kind
        # crack kinds: no pair lead exists (crude in $/bbl against products in $/gal), so no step is claimed done
        "done": {"fspread": [1, 2], "arb": [1]},
        "notes": [
            {"about": "PET.RWTC.D", "by": "analyst note",
             "text": "US pipeline crude trades by trade month, which runs from the 26th to the 25th; physical differentials to futures are commonly set per trade month."},
            {"about": "NYMEX.WTI", "by": "analyst note",
             "text": "The front WTI contract (CL) delivers one month ahead and expires about the 20th."},
            {"about": "ICE.BRENT", "by": "analyst note",
             "text": "The front Brent contract (BZ) delivers two months ahead."},
            {"about": "spot against futures", "by": "analyst note",
             "text": "Spot series are published days after futures: compare on the last date both exist."},
        ],
        "must_say": [
            "Name the part that drives the gap, with its number.",
            "Say how unusual that part is against its own history.",
            "Say which measure to use for which purpose.",
        ],
        "leads": [
            {"step": 3, "each": "pairs_long", "why": "How unusual is the distance of {a} from {b} against its history?",
             "tool": "spread", "args": {"series_a": "{a}", "series_b": "{b}", "start": "{start_long}"}},
            {"step": 3, "only": ["crack"], "why": "How unusual is this crack spread against its own history (the server converts the products to dollars per barrel)?",
             "tool": "crack_spread", "args": {"ratio": "{ratio}", "crude": "{crude}", "gasoline": "{gasoline}", "distillate": "{distillate}", "start": "{start_long}"}},
            {"step": 4, "each": "pairs_long", "why": "When did the gap of {a} from {b} step to a new level, or drift?",
             "tool": "gap_breakpoints", "args": {"series_a": "{a}", "series_b": "{b}", "start": "{start_recent}"}},
            {"step": 5, "each": "spots", "why": "Any one-day jump in {id} that reverses the next day?",
             "tool": "jumps", "args": {"series_id": "{id}", "start": "{start_recent}"}},
            {"step": 5, "each": "pairs_long", "why": "Is the gap of {a} from {b} the same value several days running?",
             "tool": "jumps", "args": {"series_id": "{a}", "series_b": "{b}", "start": "{start_recent}"}},
            {"step": 4, "covers": [4, 5], "why": "The daily values, to read what the two tools find.",
             "tool": "get_data", "args": {"series_ids": "{ids}", "start": "{start_recent}"}},
        ],
        "planned": [],
    },
    {
        "id": "high-or-low-for-the-season",
        "version": 1,
        "title": "High or low for the time of year",
        "when": ["seasonal", "percentile"],
        "steps": {
            1: "Same week in past years.",
            2: "Percentile and five-year range.",
            3: "Direction of the last weeks against the seasonal norm: toward or away from normal.",
            4: "Days of cover, if demand is known.",
        },
        "done": {"seasonal": [1, 2], "percentile": [2]},
        "notes": [
            {"about": "weekly stocks", "by": "analyst note",
             "text": "A weekly series is matched on the ISO week: a holiday moves the release day, and a 53-week year shifts the week by one."},
            {"about": "seasonal percentile", "by": "analyst note",
             "text": "A percentile over only five prior years moves in steps of 20 points: do not read a few points of it as a change."},
        ],
        "must_say": [
            "Say high, low or normal, with the percentile.",
            "Say whether the series is moving toward or away from normal.",
        ],
        "leads": [
            {"step": 1, "needs_years": 5, "why": "The same week in each prior year, with the range and z-score.",
             "tool": "seasonal", "args": {"series_id": "{id}", "lookback_years": 5}},
            {"step": 2, "why": "Where the latest value ranks in the full history, not only the seasonal window.",
             "tool": "percentile", "args": {"series_id": "{id}", "start": "{start_long}"}},
            {"step": 3, "why": "The last eight weeks of values, to see the direction against the seasonal norm.",
             "tool": "get_data", "args": {"series_ids": ["{id}"], "start": "{start_8w}"}},
        ],
    },
    {
        "id": "what-changed-this-week",
        "version": 1,
        "title": "What matters in this week's data",
        "when": ["surprises", "watch"],
        "steps": {
            1: "Changes ranked by surprise (z against usual moves), not by size.",
            2: "Firing signals, from the report's snapshot.",
            3: "Contradictions between the signals.",
            4: "What was expected (consensus), where known.",
        },
        "done": {"surprises": [1], "watch": [1]},
        "notes": [
            {"about": "surprises", "by": "analyst note",
             "text": "Lead with the biggest surprise, not the biggest number: a large move in a volatile series is less news than a small one in a quiet series."},
            {"about": "weekly reports", "by": "analyst note",
             "text": "EIA stocks land Wednesday, CFTC positioning Friday, and holiday weeks shift both."},
        ],
        "must_say": [
            "Lead with the biggest surprise, not the biggest number.",
            "Name any contradiction between the signals.",
        ],
        "leads": [
            {"step": 1, "why": "The same series ranked by size of change, to compare with the surprise ranking.",
             "tool": "changes", "args": {"series_ids": "{ids}", "lookback_days": "{lookback_days}"}},
            {"step": 2, "covers": [2, 3], "why": "A report on the series. It ends with a SNAPSHOT block of metrics; pass that block to derived_signals(metrics=...) to get the firing signals and the contradictions between them.",
             "tool": "report", "args": {"series_ids": "{ids}", "preset": "eia_weekly", "lookback_days": "{lookback_days}"}},
        ],
        "planned": [
            {"tool": "consensus_expectations", "step": 4, "why": "what the market expected for these releases"},
        ],
    },
]

# A spot series and the continuous future of its own commodity, in the same unit: the only pair a lead may make.
# Anything else (a crude price against a product price, a continuous front against a dated contract) is not a pair.
OWN_FUTURE: dict[str, dict] = {
    "PET.RWTC.D": {"future": "NYMEX.WTI.FRONT.D", "commodity": "WTI", "unit": "USD/bbl"},
    "PET.RBRTE.D": {"future": "ICE.BRENT.M1.D", "commodity": "Brent", "unit": "USD/bbl"},
}

# Series whose history is shorter than the seasonal lead needs (about five years): no seasonal lead for them.
# The catalogue says use SHIP.BWET.D for returns, not levels.
SHORT_HISTORY: dict[str, str] = {"SHIP.BWET.D": "starts 2023-05; use it for returns, not levels"}

# A dated contract has a short history; a lead that ranks against history uses its continuous series instead.
# (pattern of the dated series, the continuous series it maps to). RBOB and HO have no confirmed continuous
# series, so they stay as they are.
CONTINUOUS: list[tuple[str, str]] = [
    (r"^ICE\.BRENT\.\d{4}-\d{2}\.D$", "ICE.BRENT.M1.D"),
    (r"^NYMEX\.WTI\.\d{4}-\d{2}\.D$", "NYMEX.WTI.FRONT.D"),
    (r"^GME\.OMAN\.\d{4}-\d{2}\.D$", "GME.OMAN.M1.D"),
]

# Tools of the EnergyScope MCP server (v2.15.1) the leads may name, with the arguments each takes. leads_controls.py
# checks every lead against this table; it was copied from the server's tool schemas on 25 Nov 2026.
MCP_TOOLS: dict[str, set[str]] = {
    "spread": {"series_a", "series_b", "start", "end"},
    "get_data": {"series_ids", "start", "end", "watchlist"},
    "breakpoints": {"series_id", "min_shift", "start", "end", "annotate", "event_window_days"},
    "outliers": {"series_id", "method", "threshold", "start", "end"},
    "seasonal": {"series_id", "lookback_years", "start"},
    "percentile": {"series_id", "as_of", "start", "end"},
    "changes": {"series_ids", "lookback_days", "watchlist"},
    "derived_signals": {"metrics", "prev_metrics", "schema"},
    "term_structure": {"prefix", "n_maturities"},
    "report": {"series_ids", "sections", "preset", "lookback_days", "forecast_horizon", "start", "end", "watchlist",
               "curve_prefix", "positioning_series"},
    "gap_breakpoints": {"series_a", "series_b", "start", "end", "min_shift", "min_size"},
    "jumps": {"series_id", "series_b", "start", "end", "k"},
    "crack_spread": {"ratio", "crude", "gasoline", "distillate", "start", "end"},
    "stats": {"series_id", "start", "end"},
    "latest": {"series_ids", "include_coverage", "watchlist"},
}
