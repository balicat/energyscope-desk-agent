"""Slots: the model writes addresses, code writes every number, unit, date, noun and direction word.

A summary is a template: plain words with slots such as {curve:brent.M1_minus_M12}. Code builds a
table for the run (address -> text) from what the tools returned, and the page shows the text in
place of the slot. The model never types a digit.

This is not a template language, on purpose. A visitor can steer what the model writes, so the
template is visitor-influenced input:
- a slot is an exact key of the run's table, compared as a string; there are no filters, no
  arguments, no format specifications and no escapes, and a brace does nothing else;
- the renderer is a hand-written single pass; rendered text is never scanned again;
- the model cannot choose a word that code then signs: every variant is its own address.

What code writes. Every numeric slot names its own thing, so a value cannot be put under another
noun, unit, window or date:
- a level: "WTI spot at 89.62 dollars per barrel";
- a change: "WTI spot up 1.20 dollars per barrel (1.36%) over 30 days, from 88.42 dollars per barrel
  on 2026-10-12"; "almost unchanged" when it would print as zero;
- a gap (A minus B): "Brent M1 15.81 dollars per barrel above M12";
- a percentile, with its window: "the 3-2-1 crack spread at the 87th percentile of its last 3 years";
- a what-if value ends "(hypothetical)";
- words and whole sentences a reading wrote: a curve's shape, an arbitrage's verdict, a scorecard line.
There are no date slots. Each numeric slot carries the date of its own value, and the renderer
prints it, in brackets, whenever it differs from the last date printed.

Not offered as slots: bare counts (days, years, observations), percentile lines and spell lengths
(the sentences that hold them are slots), and a scorecard's raw values (its lines are).

Outside a slot the model may not write a digit, a number word, a date word, or a direction or
verdict word: closed lists, below. The list of change verbs is not complete and cannot be; it moves
the model to the slot, it does not prove absence. What the remaining free words claim ("sharply",
"a record", "because") is not checked, and the README says so.
"""

from __future__ import annotations

import datetime as dt
import difflib
import math
import re
from dataclasses import dataclass

from .models import Part, Reading, SeriesFact, Spread
from .readings import short


@dataclass(frozen=True)
class Slot:
    text: str
    source: str                     # the fact, spread or reading it belongs to
    series: tuple[str, ...] = ()
    date: dt.date | None = None     # the date of the value; None for words and sentences


Table = dict[str, Slot]

# ---- how a number is written ---------------------------------------------------------------------

_UNITS = {
    "usd/bbl": "dollars per barrel", "dollars per barrel": "dollars per barrel", "usd/gal": "dollars per gallon",
    "dollars per gallon": "dollars per gallon", "usd/mt": "dollars per tonne", "dollars per tonne": "dollars per tonne",
    "dollars per million btu": "dollars per million Btu", "thousand barrels": "thousand barrels",
    "thousand barrels per day": "thousand barrels per day", "contracts": "contracts", "rigs": "rigs", "usd": "dollars",
    "%": "%", "percent": "%", "percentage points/day": "percentage points per day", "vessels/day": "vessels per day",
    "points": "points", "percentage points": "percentage points",
}
_UNIT_TOKENS = {"usd": "dollars", "us$": "dollars", "$": "dollars", "bbl": "barrel", "gal": "gallon", "mt": "tonne"}

def _plain(text: str) -> str:
    """Text a slot may carry: one line, and no brace, so it can never be read as a slot."""
    return " ".join(str(text).replace("{", "(").replace("}", ")").split())


def unit_words(units: str) -> str:
    """A publisher's unit label in plain words. Unknown labels are passed through."""
    key = " ".join(str(units).lower().split())
    if key in _UNITS:
        return _UNITS[key]
    words = [_UNIT_TOKENS.get(w.lower(), w.lower() if w.istitle() else w) for w in _plain(units).replace("/", " per ").split()]
    return " ".join(words)


def num(v: float, money: bool = False) -> str:
    """The magnitude of v as the page writes it. The sign is the caller's business."""
    a = abs(v)
    if a >= 1000:
        return f"{a:,.0f}" if abs(a - round(a)) < 1e-6 else f"{a:,.2f}"
    if not money and abs(a - round(a)) < 1e-9:
        return f"{a:.0f}"
    if 0 < a < 1 and round(a, 2) != round(a, 4):
        return f"{a:.4f}".rstrip("0").rstrip(".") or "0"
    return f"{a:.2f}"


def _is_zero(n: str) -> bool:
    return not n.strip("0.,")


def _join(n: str, unit: str) -> str:
    return n + unit if unit == "%" else f"{n} {unit}".strip()


def _money(unit: str) -> bool:
    return unit.startswith("dollars")


def amount(v: float, unit: str) -> str:
    return ("-" if v < 0 else "") + _join(num(v, _money(unit)), unit)


def change(v: float, unit: str) -> str:
    n = num(v, _money(unit))
    if v == 0:
        return "unchanged"
    if _is_zero(n):  # a move too small to print: neither "up 0.00" nor "unchanged" would be true
        return "almost unchanged"
    return f"{'up' if v > 0 else 'down'} {_join(n, unit)}"


def gap(a: str, v: float, unit: str, b: str) -> str:
    n = num(v, _money(unit))
    if v == 0 or _is_zero(n):
        return f"{a} {'level' if v == 0 else 'almost level'} with {b}"
    return f"{a} {_join(n, unit)} {'above' if v > 0 else 'below'} {b}"


def signed(v: float) -> str:
    """A score or z-score with its sign; a value that prints as zero has none."""
    return "0.00" if abs(v) < 0.005 else f"{v:+.2f}"


def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def percentile(v: float) -> str:
    """With its preposition, and honest at the ends: 99.6 is not 'the 100th percentile'."""
    if v >= 100:
        return "at the highest of the window, the 100th percentile"
    if v > 99:
        return "above the 99th percentile"
    if v < 1:
        return "below the 1st percentile"
    return f"at the {ordinal(min(99, max(1, int(round(v)))))} percentile"


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text.strip()) if s]


# ---- the table -------------------------------------------------------------------------------------

# Value keys that are not offered as slots: bare counts, percentile lines, spell lengths, verdict integers,
# constants. The sentences that hold them are offered instead.
_NOT_OFFERED = re.compile(r"(?:^|_)(?:p10|p90)$|spell|(?:^|_)(?:days|weeks|years|observations)(?:_|$)|_verdict$|_share_pct$|"
                          r"^gallons_per_|^lines$|^flags$|^groups_")
_SCORES = ("score", "observed_score", "scenario_score")
_WORDS = {"brent": "Brent", "wti": "WTI", "us": "US", "ice": "ICE", "europe": "Europe", "pct": "", "observed": "", "scenario": ""}


def _generic(key: str) -> str:
    """A value's own key, spelled as words: the fallback label, clumsy but never wrong."""
    return " ".join(w for w in (_WORDS.get(p, p) for p in key.replace(": ", "_").split("_")) if w)


def fact_source(f: SeriesFact) -> str:
    return f.series_id if f.lookback_days is None else f"{f.series_id}.{f.lookback_days}d"


def spread_source(s: Spread) -> str:
    return f"{s.series_a}-minus-{s.series_b}"


def _fact_slots(f: SeriesFact) -> dict[str, tuple[str, dt.date | None]]:
    u, name = unit_words(f.units), _plain(short(f.series_id, f.name))
    out = {"value": (f"{name} at {amount(f.latest_value, u)}", f.latest_period)}
    for k, v in f.also.items():
        out[k] = (f"{name} at {amount(v, k.replace('_', ' '))}", f.latest_period)
    if f.lookback_days is not None and f.change_abs is not None and f.base_value is not None:
        out["base"] = (f"{name} at {amount(f.base_value, u)}", f.base_period)
        pct, moved = f.change_pct, change(f.change_abs, "percentage points" if u == "%" else u)
        share = (f" ({num(pct)}%)" if pct is not None and not math.isnan(pct) and u != "%" and moved.startswith(("up", "down"))
                 and not _is_zero(num(pct)) else "")
        out["change"] = (f"{name} {moved}{share} over {f.lookback_days} days, from {amount(f.base_value, u)} on {f.base_period}",
                         f.latest_period)
    return out


def _long_text(out: dict, name: str, text: str, numbered: bool = True) -> None:
    if text:
        out[name] = (_plain(text), None)
        parts = sentences(text)
        if numbered and len(parts) > 1:
            out.update({f"{name}.{i}": (_plain(p), None) for i, p in enumerate(parts, 1)})


def _spread_slots(s: Spread) -> dict[str, tuple[str, dt.date | None]]:
    u, a, b = unit_words(s.units), _plain(short(s.series_a, s.name_a)), _plain(short(s.series_b, s.name_b))
    out = {"a": (f"{a} at {amount(s.value_a, u)}", s.period), "b": (f"{b} at {amount(s.value_b, u)}", s.period),
           "gap": (gap(a, s.spread, u, b), s.period)}
    if "percentile" in s.extras:
        years = int(s.extras.get("percentile_years", 0))
        out["percentile"] = (f"the spread {percentile(s.extras['percentile'])} of its last {years} years", s.period)
    _long_text(out, "context", s.context)
    _long_text(out, "note", s.note)
    return out


def _reading_unit(r: Reading, k: str) -> str:
    if k in r.unit_of:
        return unit_words(r.unit_of[k])
    for suffix, u in (("_per_gallon", "dollars per gallon"), ("_per_tonne", "dollars per tonne"), ("_per_barrel", "dollars per barrel"),
                      ("_pct", "%"), (" pct", "%")):
        if k.endswith(suffix):
            return u
    return unit_words(r.unit_of.get("*", r.units))


def _value_text(r: Reading, k: str, v: float) -> str | None:
    """What a reading's value says, by the kind of value its key names. None = not offered as a slot."""
    label, _, field = k.rpartition(": ")       # watchlist readings key their values "Label: field"
    low = (field if label else k).lower().replace("-", "_").replace(" ", "_")
    if _NOT_OFFERED.search(low):
        return None
    name = _plain(r.label_of.get(k) or label or _generic(k))
    unit, window = _reading_unit(r, k), _plain(r.window_of.get(k, ""))
    parts = low.split("_")
    if "percentile" in low:
        text = f"{name} {percentile(v)} {window or 'of the window its reading states'}"
    elif "z_score" in low:
        text = f"{name} at a z-score of {signed(v)} {window}"
    elif low == "score_change":
        text = f"{name} {change(v, 'points')} {window}"
    elif low in _SCORES:
        text = f"{name} at {signed(v)} on a scale from -2 to +2"
    elif low in ("difference", "difference_pct") and r.key.startswith("seasonal:"):
        u = "percentage points" if unit == "%" and low == "difference" else unit
        text = (f"{name} {_join(num(v, _money(u)), u)} {'above' if v >= 0 else 'below'} the average for the same time of year "
                f"in the previous {int(r.values.get('years', 0))} years")
    elif "_minus_" in low:
        a, _, b = name.partition("|")
        if not b:
            a, _, b = _generic(k).partition(" minus ")
        text = gap(a, v, unit, b)
    elif "change" in parts:
        text = f"{name} {change(v, unit)} {window}"
    elif unit:
        text = f"{name} at {amount(v, unit)}"
    else:
        return None
    text = " ".join(text.split())
    return text + " (hypothetical)" if low.startswith("scenario_") else text


def _reading_slots(r: Reading) -> dict[str, tuple[str, dt.date | None]]:
    out: dict[str, tuple[str, dt.date | None]] = {}
    if r.slot_values:
        for k, v in r.values.items():
            text = _value_text(r, k, v)
            if text:
                out[k] = (text, r.date_of.get(k, r.period))
    for k, text in r.words.items():
        out[k] = (_plain(text), None)
    _long_text(out, "context", r.context)
    _long_text(out, "note", r.note)
    _long_text(out, "counter", r.counter, numbered=False)
    return out


def table(facts: list[SeriesFact], spreads: list[Spread], readings: list[Reading]) -> Table:
    """Every slot the run may use: address -> what code writes there, and where it came from."""
    t: Table = {}
    for f in facts:
        src = fact_source(f)
        for k, (text, date) in _fact_slots(f).items():
            t[f"{src}.{k}"] = Slot(text, src, (f.series_id,), date)
    for s in spreads:
        src = spread_source(s)
        for k, (text, date) in _spread_slots(s).items():
            t[f"{src}.{k}"] = Slot(text, src, (s.series_a, s.series_b), date)
    for r in readings:
        for k, (text, date) in _reading_slots(r).items():
            t[f"{r.key}.{k}"] = Slot(text, r.key, tuple(r.series_ids), date)
    return {a: s for a, s in t.items() if "{" not in a and "}" not in a}


_SENTENCE = re.compile(r"\.(?:context|note|counter)(?:\.\d+)?$")


def sheet(source: str, t: Table) -> dict:
    """What the model is shown for one tool result: each address in braces and the text it stands for."""
    mine = {a: s for a, s in t.items() if s.source == source}
    long = {a for a in mine if _SENTENCE.search(a)}
    whole_with_parts = {a for a in long if any(n.startswith(a + ".") for n in long)}
    return {
        "source": source,
        # a figure names its subject and has no verb; a statement is a whole clause; a sentence is a whole sentence
        "figures": {"{" + a + "}": f"{s.text} ({s.date})" for a, s in mine.items() if a not in long and s.date},
        "statements": {"{" + a + "}": s.text for a, s in mine.items() if a not in long and not s.date},
        "sentences": {"{" + a + "}": mine[a].text for a in sorted(long - whole_with_parts)},
    }


# ---- parsing and rendering ---------------------------------------------------------------------------

class Malformed(ValueError):
    pass


def split(template: str) -> list[tuple[str, bool]]:
    """(text, is it a slot address) pieces, in order. A brace that does not open or close one slot is an error."""
    pieces: list[tuple[str, bool]] = []
    buf: list[str] = []
    i, n = 0, len(template)
    while i < n:
        c = template[i]
        if c == "{":
            j = template.find("}", i + 1)
            inner = template[i + 1:j] if j != -1 else ""
            if j == -1 or "{" in inner or not inner.strip():
                raise Malformed("a brace that does not form one slot")
            if buf:
                pieces.append(("".join(buf), False))
                buf = []
            pieces.append((inner, True))
            i = j + 1
        elif c == "}":
            raise Malformed("a closing brace with no slot")
        else:
            buf.append(c)
            i += 1
    if buf:
        pieces.append(("".join(buf), False))
    return pieces


def render(template: str, t: Table) -> tuple[str, list[Part]]:
    """(the summary, its parts). One pass; what code wrote is never read again. An unknown slot is left as
    written, braces and all, so that it cannot pass for an answer. A date is printed after a slot whenever
    the slot's own date differs from the last one printed."""
    try:
        pieces = split(template)
    except Malformed:
        return template, [Part(text=template)]
    parts: list[Part] = []
    shown: dt.date | None = None
    for text, is_slot in pieces:
        if not is_slot:
            parts.append(Part(text=text))
        elif text in t:
            s = t[text]
            before = "".join(p.text for p in parts[-1:]).rstrip()
            out = s.text[:1].upper() + s.text[1:] if before[-1:] in ("", ".", "!", "?") else s.text  # a slot that opens a sentence
            if s.date is not None and s.date != shown:
                out, shown = f"{out} ({s.date})", s.date
            parts.append(Part(text=out, slot=text, source=s.source, series=list(s.series), date=s.date))
        else:
            parts.append(Part(text="{" + text + "}"))
    return "".join(p.text for p in parts), parts


def used_sources(template: str, t: Table) -> list[str]:
    try:
        return list(dict.fromkeys(t[a].source for a, is_slot in split(template) if is_slot and a in t))
    except Malformed:
        return []


# ---- what the model may not write outside a slot -------------------------------------------------------

NUMBER_WORDS = frozenset(
    "zero nil two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen "
    "nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred hundreds thousand thousands million millions "
    "billion billions trillion trillions dozen dozens half halved halving halve halves double doubled doubling doubles "
    "twice triple tripled tripling treble trebled quadruple quadrupled twofold threefold fourfold fivefold tenfold "
    "third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth quarter quarters".split())
_ONE = frozenset("one a an single".split())
_ONE_OF = frozenset("dollar cent percent percentage point basis".split())  # "a dollar higher" is a number
DATE_WORDS = frozenset(
    "january february march april june july august september october november december jan feb mar apr jun jul aug sep "
    "sept oct nov dec monday tuesday wednesday thursday friday saturday sunday today yesterday tomorrow tonight".split())
_DAY_PARTS = frozenset("morning afternoon evening".split())
# Verdicts are code's. A curve's shape, a move's direction, a scorecard's reading and an arbitrage's state each
# have a slot that says it; the model's own word for one would be an unchecked claim beside a checked number.
SHAPE_WORDS = frozenset("backwardation backwardated contango contangoed inverted inversion".split())
CHANGE_WORDS = frozenset(
    "rose risen rise rises rising fell fallen fall falls falling climbed climbs climbing jumped jumps dropped drops dropping "
    "drop declined declines declining decline increased increases increasing increase decreased decreases decreasing decrease "
    "gained gains gain slipped slips shed surged surges plunged plunges soared tumbled slumped rallied rallies eased firmed "
    "weakened strengthened widened widens widening narrowed narrows narrowing steepened steepens steepening flattened flattens "
    "flattening built drew grew shrank build builds draw draws higher lower".split())
BALANCE_WORDS = frozenset("tight tighter tightening tightened tightness loose looser loosening loosened".split())
ARB_WORDS = frozenset("open opens opened opening shut shuts closed closes close closing".split())
_BEFORE_SLOT = re.compile(r"(?:^|[\s(\"'])$")
_AFTER_SLOT = re.compile(r"^(?:$|[\s.,;:)!?\"'])")
_JOIN = re.compile(r"\s*[.,;:()]\s*|\s*[.;:,]?\s*\(\s*|\s*\)\s*[.,;:]?\s*")  # what may stand alone between two slots

Problem = tuple[str, str]  # (cause, what to tell the model)


def free_text_problems(text: str, arbitrage: bool = False) -> list[Problem]:
    """What one stretch of the model's own words may not contain."""
    bad: list[Problem] = []
    digits = sorted({m.group() for m in re.finditer(r"\S+", text) if any(ch.isnumeric() for ch in m.group())})
    if digits:
        bad.append(("digit", f"digits typed outside a slot: {digits[:6]}. Place the slot whose text holds the figure"))
    words = re.findall(r"[A-Za-z]+", text)
    low = [w.lower() for w in words]
    numbers = sorted({w for w in low if w in NUMBER_WORDS}
                     | {f"{a} {b}" for a, b in zip(low, low[1:]) if a in _ONE and b.rstrip("s") in _ONE_OF})
    if numbers:
        bad.append(("number word", f"number words typed outside a slot: {numbers[:6]}. A slot's text already says it "
                                   "(the window, the unit); reword without it"))
    dates = {w for w in low if w in DATE_WORDS} | {f"this {b}" for a, b in zip(low, low[1:]) if a == "this" and b in _DAY_PARTS}
    for m in re.finditer(r"\bMay\b", text):   # the month, when it is not the first word of a sentence
        if text[:m.start()].rstrip()[-1:] not in ("", ".", "!", "?", ":"):
            dates.add("May")
    if dates:
        bad.append(("date word", f"date words typed outside a slot: {sorted(dates)[:6]}. The page prints each value's date itself"))
    verdicts = sorted({w for w in low if w in SHAPE_WORDS | CHANGE_WORDS | BALANCE_WORDS or (arbitrage and w in ARB_WORDS)})
    if verdicts:
        bad.append(("verdict word", f"direction or verdict words typed outside a slot: {verdicts[:8]}. Code writes these: a change "
                                    "slot says up or down, a gap slot says above or below, and shape, verdict, balance and line slots "
                                    "give the rest. Place the slot and remove the word"))
    return bad


def template_problems(template: str, t: Table) -> list[Problem]:
    """Everything wrong with a template: its braces, its addresses, and the words between the slots."""
    try:
        pieces = split(template)
    except Malformed as e:
        return [("brace", f"malformed template: {e}. A brace may only open and close one slot; write no other braces")]
    bad: list[Problem] = []
    unknown = [a for a, is_slot in pieces if is_slot and a not in t]
    for a in unknown[:4]:
        near = difflib.get_close_matches(a, list(t), n=3, cutoff=0.5)
        bad.append(("address", f"slot {{{a}}} is not an address a tool returned in this run"
                    + (f"; the nearest are {', '.join('{' + x + '}' for x in near)}" if near else "")))
    if len(unknown) > 4:
        bad.append(("address", f"and {len(unknown) - 4} more unknown slots"))
    arbitrage = any(s.source.startswith(("arb:", "scenario:arb:")) for s in t.values())
    for i, (text, is_slot) in enumerate(pieces):
        if not is_slot:
            bad += free_text_problems(text, arbitrage)
            continue
        before = pieces[i - 1] if i else ("", False)
        after = pieces[i + 1] if i + 1 < len(pieces) else ("", False)
        if before[1] or after[1] or not _BEFORE_SLOT.search(before[0]) or not _AFTER_SLOT.search(after[0]):
            bad.append(("adjacency", f"slot {{{text}}} must stand alone: a space before it, and a space or punctuation after it"))
        if i >= 2 and not before[1] and pieces[i - 2][1] and not re.search(r"[A-Za-z]", before[0]) and not _JOIN.fullmatch(before[0]):
            bad.append(("adjacency", f"join two slots (before {{{text}}}) with a word, a comma, a semicolon, a colon or a full stop: "
                                     "a slash or a dash between two figures reads as a ratio or a range that nobody computed"))
    return list(dict.fromkeys(bad))


# ---- caveats the model may choose; code writes each ------------------------------------------------------

LIMITS = {
    "not_in_data": "The data does not hold what was asked.",
    "out_of_scope": "The question is not about energy markets, so nothing was looked up.",
    "no_secrets": "Instructions and credentials are not shown.",
    "no_forecast": "This describes the data as it stands. It is not a forecast.",
    "no_causes": "The data shows what moved, not why: it holds no news.",
    "no_freight": "No route freight rates are in the data. Where freight appears, it is a tanker fund's price, a proxy.",
    "no_physical": "No physical differentials, port costs or quality differences are in the data.",
    "no_consensus": "The data holds no consensus forecasts, so a surprise here means an unusually large move for that series.",
    "partial": "Only part of the question could be answered from the data.",
    "unconfirmed_figure": "A figure given in the question does not appear in the data and is not confirmed.",
    "us_only": "The data used here covers the United States, not the world.",
}
WHAT_IF = "What-if: figures marked hypothetical are not market observations."
