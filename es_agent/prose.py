"""What the prose may say: the checks on the sentences, as opposed to the tables.

The validator (before an answer is accepted), `verify()` (before the page shows its tick) and
the evaluators all call these, so one rule decides in all three places.

Checked, in the summary and in every caveat the model wrote:
- every run of digits is a valid rounding of a value a tool returned, of the right kind. A number
  followed by a money word must be an amount, not a percentage or a count; a number followed by
  "days" or "years" must be a count; a scale word or "per tonne" after a number must appear in the
  units of something the answer cites. A number glued to letters ("USD97.72") is still a number;
  only a whole token that a tool returned as a name ("M12") is excused;
- a number written WITH a unit (a scale word, a currency, barrels, gallons, tonnes, contracts, rigs, "per
  day", "%") must match a value of that number in that unit (21 Nov 2026): a price change of 0.19 dollars a
  gallon written as "0.19 million barrels" is rejected. Each value's unit is code's: a fact's units, a
  spread's, a reading's `value_units`. Values whose unit code does not know (the evidence, watch, surprises,
  arbitrage and scenario readings, the signals' metrics, numbers in a reading's own text) are matched on the
  number alone, as before;
- a window named in words ("five-year", "over ten years") must be one a reading or fact used, unless the
  sentence says it is missing ("could not pull the five-year history");
- a number spelled out beside a unit ("ninety-eight dollars") is rejected;
- a figure code converted to million barrels (from thousand) is written with "million" after it; M and MM are
  read as EIA writes them (Mbbl a thousand barrels, MMbbl a million), mb/d as IEA does (a million);
- a server text's parameter ("week=46") is written only as its phrase: "week 46", "the 46th week of the year";
- every date is one a tool returned, written as YYYY-MM-DD. Month names, weekday names and quarters
  are rejected, because a date written in words cannot be traced; a bare year passes only as part
  of a returned name; only code writes today's date;
- direction. A change that is quoted must have a word of the right sign beside it, or an explicit
  sign ("rose 1.20", "+1.20"): denied by default, so an unlisted verb cannot slip through. A gap
  with "above", "below", "premium" or "discount" beside it must point the right way. A curve's shape
  word must be the reading's own and not negated; "steepened" or "flattened" must be the reading's
  own word; a high percentile may not be called low, nor a low one high ("stretched" takes its side word:
  "stretched short" is low). A usual change (the norm a change is compared with) needs no direction word when it
  has the same sign as that change, but a wrong one is still wrong.

Not checked, and stated as limits in the README: two true values or dates attached to the wrong
nouns when they share a unit (Brent's price given to WTI), and claims made in words alone ("a record high", "has narrowed" where no earlier value was
returned). A short number such as "2" matches any returned value between 1.5 and 2.5, so the chance
of an accidental match grows with the number of values cited.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from .models import DeskAnswer

# Caveats written by code start with one of these. The validator removes any the model wrote with
# the same opening and appends its own, so the prefix marks text that needs no tracing.
CODE_CAVEATS = ("Not current as of ", "Against the balance of the evidence: ", "Not like for like: ",
                "Average-price contract: ", "Shorter history: ")

_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_DIGITS = re.compile(r"\d[\d,]*(?:\.\d+)?")
_TOKEN = re.compile(r"(?P<num>\d[\d,]*(?:\.\d+)?)|(?P<word>[A-Za-z][A-Za-z0-9]*)")
_LOOSE_DATE = re.compile(
    r"\b(?:january|february|march|april|june|july|august|september|october|november|december|"
    r"jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|q[1-4])\b|\bmay \d|\d(?:st|nd|rd|th)? may\b", re.I)
_MONEY = re.compile(r"\s*(?:usd|us\$|\$|dollars?|cents?|eur|euros?|€|£|gbp)", re.I)
_PCT = re.compile(r"\s*(?:%|percent|per cent)", re.I)
_COUNT = re.compile(r"[\s-]*(?:days?|weeks?|years?|months?|lines?|observations?|reports?)\b", re.I)
# The nouns a window or count of the data is written with: "5 years", "747 observations", "a 90-day window". Not a
# bare "points": "Henry Hub could fall 747 points" reads as an index level (the adversary, 24 Nov 2026); "data points" stays
_META_NOUNS = (r"(?:trading[\s-]+days?|data[\s-]+points?|days?|weeks?|years?|months?|observations?|obs|values?|"
               r"readings?|periods?|sessions?|reports?|lines?|window|sample)")
# after the number, with up to two describing words between: "5 years", "746 daily observations", "a 90-day window"
_META_NOUN = re.compile(r"[\s-]*(?:(?:daily|weekly|monthly|annual|yearly|trading|rolling|consecutive|business|calendar|"
                        r"data|price|sample|historical|earlier|previous|past|full|prior|separate|distinct)[\s-]+){0,2}"
                        + _META_NOUNS + r"\b", re.I)
# Keys whose value is a window or a count of the data, not a market figure: quotable only with their noun
_META_KEYS = {"years", "lookback_years", "years_of_history", "history_years", "observations", "obs", "n_obs", "window",
              "window_days", "n", "count", "periods", "lookback_days"}
_SCALE = re.compile(r"\s*(thousand|million|billion|trillion|hundred)\b", re.I)
_PER = re.compile(r"[^.;,]{0,24}?\bper\s+(?:metric\s+)?(barrel|bbl|tonne|ton|mt|gallon|gal|day|mmbtu|btu|mwh|therm)\b", re.I)
_ORDINAL = {"st", "nd", "rd", "th"}
# A spelled-out number starts with a counting word. A scale word alone ("reported in thousand barrels")
# is a unit, not a number: this rule once refused that sentence four times running and blocked a release.
_COUNTING = (r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
             r"seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)")
_NUMWORD = rf"(?:{_COUNTING}|hundred|thousand|million|billion)"
_SPELLED = re.compile(rf"\b{_COUNTING}(?:[\s-]+(?:and\s+)?{_NUMWORD})*\s+(?:us\s+)?"
                      r"(?:usd|dollars?|cents?|percent|per\s+cent|barrels?|bbl|contracts?|tonnes?|gallons?)\b", re.I)

_UNIT_WORDS = {"usd": "dollars", "$": "dollars", "us$": "dollars", "/": " per ", "bbl": "barrel", "barrels": "barrel",
               "gal": "gallon", "gallons": "gallon", "mt": "tonne", "tonnes": "tonne", "ton": "tonne", "mmbtu": "million btu",
               # for the unit rule (21 Nov 2026): OPEC's mb/d, plurals of the nouns a value's unit names
               "mb": "million barrel", "kb": "thousand barrel", "tb": "thousand barrel", "d": "day", "bbls": "barrel", "contracts": "contract",
               "rigs": "rig", "dollar": "dollars", "tons": "tonne"}


# The currency a unit or a written number is in (ported from the display-forms branch's checker, df-checker 759ee70,
# for the released code; the adversary's LF2 identity case, 24 Nov 2026: "Henry Hub is at EUR 3.10 per million Btu"
# passed for a dollar price). Dollars and cents are kept apart, and so are dollars, euros and pounds; another
# country's dollar (C$, A$) is none of the series' currencies.
_CURRENCY_OF = {"dollars": "dollars", "dollar": "dollars", "cents": "cents", "cent": "cents", "euros": "euros",
                "euro": "euros", "eur": "euros", "pounds": "pounds", "gbp": "pounds", "sterling": "pounds"}
_SIGNS = {"$": "dollars", "€": "euros", "£": "pounds"}


def unit_key(units: str) -> str:
    """Publishers label the same unit differently ('USD/bbl', 'Dollars per Barrel'); compare on this."""
    text = units.lower().replace("/", " per ")
    return " ".join(_UNIT_WORDS.get(w, w) for w in text.split())


def also_in(units: str, value: float) -> dict[str, float]:
    """The same value in the unit people ask for. EIA publishes stocks in thousand barrels; a person asks
    for million barrels. The conversion is done here so the model has a figure to quote and never divides.
    Facts carry it (`also`); a reading's values get it in the pool of quotable numbers (`pool_of`)."""
    key = unit_key(units)
    if key == "thousand barrel":
        return {"million_barrels": round(value / 1000, 3)}
    if key == "thousand barrel per day":
        return {"million_barrels_per_day": round(value / 1000, 3)}
    return {}


def _kind(key: str) -> str:
    # a server reading's names are nested with dots ("coverage.observations", "segments.2.mean"): split on both
    parts = re.split(r"[._]", key.lower())
    # a half-life is counted in observations ("a half-life of 10.04 days"); a value named count is a count (stats)
    if key in ("lines", "tight", "loose", "neutral") or key.startswith("groups_") or "observations" in parts or any(p in ("days", "weeks", "years", "life", "count") for p in parts):
        return "count"
    # pct anywhere in the name is a percent: the server's pct_vs_avg and pct_change (the live gate, 21 Nov 2026,
    # refused "3.65 percent below the average" while pct_vs_avg was read as an amount in thousand barrels)
    if "percentile" in parts or "pct" in parts or key.endswith("_pct") or "percentile" in key:
        return "percent"
    return "amount"


def _blank_dates(text: str) -> str:
    return _ISO.sub(lambda m: " " * len(m.group()), text)


def _numbers(text: str):
    """Every run of digits in `text` (ISO dates already blanked): (written, start, end, the whole
    letters-and-digits token around it, whether it is glued to letters)."""
    for m in _DIGITS.finditer(text):
        tok = m.group().rstrip(",")
        start, end = m.start(), m.start() + len(tok)
        s, e = start, end
        while s > 0 and text[s - 1].isalnum():
            s -= 1
        while e < len(text) and text[e].isalnum():
            e += 1
        suffix = text[end:e].lower()
        glued = s < start or (bool(suffix) and suffix not in _ORDINAL)
        yield tok, start, end, text[s:e], glued


# Words too common to tie a number to a name: "Brent could fall to 500" has "to" beside its 500, as "up to 500" might
# in a title, and that must not make it the S&P 500's.
_PLAIN_WORDS = {"a", "an", "the", "to", "of", "at", "in", "on", "by", "for", "and", "or", "from", "with", "is", "was",
                "are", "be", "as", "up", "down", "over", "under", "than", "per", "its", "it", "this", "that"}


_COMPOUND = re.compile(r"\d+(?:[-,:]\d+)+|\d+-[A-Za-z]+")    # 3-2-1, 2027-01, 1,1, 2:1, 20-day
# segments.1.count, metric.crack_321_z, value_in_2021: a letter somewhere, so a decimal (92.94) is never one
_IDENT = re.compile(r"(?=[\w.]*[A-Za-z])[A-Za-z0-9]+(?:[._][A-Za-z0-9]+)+")
_WINDOW_AFTER = re.compile(r"[\s-]+(?:trading\s+)?(?:days?|weeks?|months?|years?|quarters?|observations?|sessions?)\b", re.I)
_YEAR_WORDS = {"in", "since", "during", "of", "for", "from", "between", "until", "each", "year", "years", "and", "with",
               "where", "when", "only"}
_RANGE_TO = r"\s*(?:to|through|and|\u2013|\u2014|-)\s*"


def _year_position(text: str, start: int, end: int) -> bool:
    """A year where a year goes: after in, since, during, of, for, from, between, until, each, year(s), and, with,
    where, when, only; in brackets; before a colon; before its own value in a list ("2021 434,020", "2022 at
    431665.0"); after "the" and before a word ("the 2025 level"); or as either end of a range of years whose first
    end is itself in such a place ("in 2021 to 2025", "(2021 to 2025)", "the 2021-2025 range"). Not after "to" or
    "reach": "rise to 2027" is a quantity, and so is "hit 2021 to 2025"."""
    m = re.search(r"((?:19|20)\d\d)" + _RANGE_TO + r"$", text[max(0, start - 14):start])
    if m:   # the second end of a range: it stands where the first end stands
        first = max(0, start - 14) + m.start(1)
        return _year_place(text, first, first + 4, range_after=True)
    return _year_place(text, start, end, range_after=bool(re.match(_RANGE_TO + r"(?:19|20)\d\d\b", text[end:end + 14])))


def _year_place(text: str, start: int, end: int, range_after: bool = False) -> bool:
    before = re.search(r"([A-Za-z]+)\W*$", text[max(0, start - 20):start])
    word = before[1].lower() if before else ""
    if word in _YEAR_WORDS or re.search(r"\(\s*$", text[max(0, start - 3):start]):
        return True   # ... or in brackets: "424155.0 thousand barrels (2025)", "(2021 to 2025)"
    if range_after:   # "the 2021-2025 range", "424155.0 to 448054.0 thousand barrels, 2021 to 2025"
        return word == "the" or bool(re.search(r",\s*$", text[max(0, start - 3):start]))
    if re.match(r"\s*[(:]", text[end:end + 3]):
        return True   # "2025 (424,155)", "2025: 424,155"
    if re.match(r" (?:at )?\d[\d,]*(?:\.\d+)?(?![\d.]|\s*(?:%|percent))", text[end:end + 20]):
        return True   # a year before its own value in a list: "2021 434,020", "2022 at 431665.0"
    return word == "the" and bool(re.match(r" [A-Za-z]", text[end:end + 2]))


def _signed_at(text: str, start: int) -> bool:
    """A sign written right before the number, not a hyphen of a term ("-2" in "of -2", not the 2 of "3-2-1")."""
    return start > 0 and text[start - 1] in "+-\u2212" and (start < 2 or not text[start - 2].isalnum())


def _beside(text: str, start: int, end: int) -> tuple[str, ...]:
    """The word right before text[start:end] and the two right after it, lowercased, a plural folded to its singular
    ("days" is "day"), a hyphen read as a space ("an 18-series watchlist"); "" for none or a plain word."""
    before = re.search(r"([A-Za-z][A-Za-z&']*)[.\s]*$", text[max(0, start - 40):start])
    after = re.match(r"[\s-]*([A-Za-z][A-Za-z&']*)(?:[\s-]+([A-Za-z][A-Za-z&']*))?", text[end:end + 60])
    words = [before[1] if before else ""] + ([after[1], after[2] or ""] if after else ["", ""])

    def fold(w: str) -> str:
        w = w.lower().strip("'")
        return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
    return tuple("" if fold(w) in _PLAIN_WORDS else fold(w) for w in words)


@dataclass
class Pool:
    """Everything the tools returned that the prose may quote."""

    amounts: list[float] = field(default_factory=list)
    percents: list[float] = field(default_factory=list)
    counts: list[float] = field(default_factory=list)
    percentiles: list[float] = field(default_factory=list)  # a subset of percents: ranks, for the high/low rule
    dates: set[dt.date] = field(default_factory=set)
    names: set[str] = field(default_factory=set)    # plain numbers that are part of a name or of code-written text
    # ... and the words beside each in the text it came from: a name's number may be written only beside one of them
    # ("S&P 500", "No. 2 heating oil"), never on its own ("Brent could fall to 500": the adversary's L1, 24 Nov 2026)
    name_words: dict[str, set[str]] = field(default_factory=dict)
    pctl_names: set[str] = field(default_factory=set)  # the 95 of a key p95: written only as an ordinal, "the 95th"
    terms: set[str] = field(default_factory=set)       # compound terms of names and ids: 3-2-1, 2027-01, 1,1, 20-day
    idents: set[str] = field(default_factory=set)      # key-like identifiers: segments.1.count, value_in_2021
    key_numbers: set[str] = field(default_factory=set)  # plain numbers of keys and ids: a window, written with its noun
    key_years: set[str] = field(default_factory=set)    # years of keys and ids: written only where a year goes
    signed: set[str] = field(default_factory=set)        # numbers a name writes with a sign: the -2 and +2 of a scale
    tokens: set[str] = field(default_factory=set)   # names that mix letters and digits: M12, PF4
    hyphens: set[str] = field(default_factory=set)  # whole numbers of a hyphenated term of a text: the 12 of 12-month
    phrases: set[tuple[str, str]] = field(default_factory=set)  # a server text's parameters: ("week", "46") of week=46
    # entries of `tagged` that code converted (thousand to million barrels): by entry, not by value, since a server
    # report's own million-barrel figure has the same value as code's conversion and is not one
    converted: set[int] = field(default_factory=set)
    # entries of `tagged` that are a window or a count of the data (years, observations, a lookback): with a noun only
    metas: dict[int, str] = field(default_factory=dict)
    units: str = ""                                 # units and labels of everything cited, normalised
    # every quotable number with its kind and its unit: the unit a tool gave it, "percent" for a percent, "1" for a
    # number with none (a z-score, a correlation), None where code does not know it (a reading of mixed units)
    tagged: list[tuple[float, str, str | None]] = field(default_factory=list)

    def put(self, value: float, kind: str, unit: str | None) -> None:
        """kind "any": a number of a code-written text, whose kind is not known either ("the 253.00 line", "all 12
        months"): it may be quoted as an amount, a percent or a count."""
        if kind != "any":
            {"count": self.counts, "percent": self.percents, "amount": self.amounts}[kind].append(value)
        self.tagged.append((value, kind, "percent" if kind == "percent" else unit))

    def add(self, key: str, value: float, unit: str | None = None) -> None:
        kind = _kind(key)
        self.put(value, kind, unit)
        if kind == "percent" and "percentile" in key:
            self.percentiles.append(value)

    def text(self, *parts: str) -> None:
        joined = " ".join(parts)
        for d in _ISO.findall(joined):
            try:
                self.dates.add(dt.date.fromisoformat(d))
            except ValueError:
                pass
        blanked = _blank_dates(joined)
        self._shapes(blanked)
        for tok, start, end, whole, glued in _numbers(blanked):
            if glued:
                self.tokens.add(whole)
                continue
            self.names.add(tok)
            self.name_words.setdefault(tok, set()).update(w for w in _beside(blanked, start, end) if w)
            if _signed_at(blanked, start):
                self.signed.add(tok)

    def _shapes(self, text: str) -> None:
        self.terms |= {m.lower() for m in _COMPOUND.findall(text)}
        self.idents |= {m.lower() for m in _IDENT.findall(text) if any(c.isdigit() for c in m)}

    def ids(self, *parts: str) -> None:
        """Series ids, reading keys and value keys: their dates and their letter-and-digit names (M12) may be written,
        never a bare number of theirs. Until 24 Nov 2026 every number in them was a name, so "WTI could reach 2027"
        passed on the id NYMEX.WTI.2027-01.D and "Henry Hub will reach 95" on the key p95 (the adversary's L1)."""
        joined = " ".join(parts)
        for d in _ISO.findall(joined):
            try:
                self.dates.add(dt.date.fromisoformat(d))
            except ValueError:
                pass
        blanked = _blank_dates(joined)
        self._shapes(blanked)
        for tok, _, _, whole, glued in _numbers(blanked):
            if glued:
                self.tokens.add(whole)
            elif re.fullmatch(r"(?:19|20)\d\d", tok):
                self.key_years.add(tok)
            else:
                self.key_numbers.add(tok)

    def named(self, clean: str, start: int, end: int, tok: str) -> bool:
        """Is the number at clean[start:end] written as part of a name a tool returned, and not as a quantity? A key's,
        an id's or a title's number may be written only in the shapes a name takes:
          - inside the same compound term or key ("the 3-2-1 crack", "2027-01 delivery", "GARCH(1,1)", "the 20-day",
            "segments.1.count", "value_in_2021");
          - a percentile point of the reading (key p95) as an ordinal: "the 95th percentile", "the 10th and 90th";
          - a key's window with its noun: "the latest 90 observations";
          - a key's year where a year goes: "in 2023", "2025 (424,155)";
          - a number a name writes with a sign, with that sign: "a scale of -2 to +2";
          - beside a word that stood beside it in the name: "the S&P 500", "No. 2 heating oil".
        Never alone: "Henry Hub will reach 95", "WTI could reach 2027", "Brent could fall to 500" (the adversary's L1,
        24 Nov 2026: every number of a key, an id or a title had been a name that passed anywhere without a unit)."""
        for pat, known in ((_COMPOUND, self.terms), (_IDENT, self.idents)):
            for m in pat.finditer(clean):
                if m.start() <= start and end <= m.end() and m.group().lower() in known:
                    return True
        if tok in self.pctl_names and re.match(r"(?:st|nd|rd|th)\b", clean[end:end + 3], re.I):
            return True
        if tok in self.key_numbers and _WINDOW_AFTER.match(clean[end:end + 32]):
            return True
        if tok in self.key_years and _year_position(clean, start, end):
            return True
        if tok in self.signed and _signed_at(clean, start):
            return True
        words = self.name_words.get(tok)
        return bool(words) and bool(words & set(_beside(clean, start, end)))

    def context(self, text: str, quotable: bool = True) -> None:
        """A reading's or a spread's code-written text: its dates and its letter-and-digit names (M12) may be
        written; a plain number in it is an AMOUNT and takes the money, percent, scale and per-unit tests like any
        value. Until 21 Nov 2026 such a number was a name and skipped them ("Gasoline stocks were 0.19 million
        barrels" passed on 0.19 dollars a gallon from a report's text: the adversary). A server reading's text
        gives no numbers at all (`quotable` False): every number it holds is also one of its values."""
        for d in _ISO.findall(text):
            try:
                self.dates.add(dt.date.fromisoformat(d))
            except ValueError:
                pass
        # A whole number that is part of a hyphenated term of the text ("12-month roll yield", "3-2-1") may be
        # written the same way, hyphenated. Not a digit of a decimal (the 8 of "1.8-sigma"), and not the number on
        # its own: "fell by 8 million barrels" passed on that 8 until the adversary's round 3 (21 Nov 2026).
        for m in re.finditer(r"(?<![\d.,])\b(\d+)(?=-[A-Za-z0-9])", _blank_dates(text)):
            self.hyphens.add(m[1])
        # A server text's parameters ("week=46") may be written as the phrase they are: "week=46", "week 46", "the
        # 46th week" (the adversary's P11, 23 Nov 2026: the seasonal reading's own first sentence, quoted back, was
        # refused on its week number). Only as that phrase: as a bare name, 46 passed in "fallen for 46 weeks", "a
        # 46-week low", "46 below their average" (the adversary, 24 Nov 2026). Not the whole part of a decimal:
        # x=3.41 names nothing.
        if not quotable:
            self.phrases |= {(k.replace("_", " "), n) for k, n in re.findall(r"\b([a-z_]+)=(\d+)(?!\.?\d)", _blank_dates(text))}
        for tok, _, _, whole, glued in _numbers(_blank_dates(text)):
            if glued:
                self.tokens.add(whole)
            elif quotable:
                try:
                    self.put(_parse(tok)[0], "any", None)   # neither its kind nor its unit is known: the text mixes them
                except ValueError:
                    pass

    def label(self, *parts: str) -> None:
        # the same word reader as the unit rule, so a unit inside punctuation counts: "($/bbl;" is dollars per barrel
        text = " ".join(parts).replace("_", " ")
        self.units += " " + unit_key(text) + " " + " ".join(_unit_words(text))


def pool_of(answer: DeskAnswer) -> Pool:
    p = Pool()
    for f in answer.facts:
        for x in (f.latest_value, f.base_value, f.change_abs):
            if x is not None:
                p.put(x, "amount", f.units)
                # the year-ago level and the change may be written in million barrels, as the latest may (`also`):
                # code converts all three (24 Nov 2026; the sweep's us_crude_yoy send-back, "427.58")
                for name, conv in also_in(f.units or "", x).items():
                    p.put(conv, "amount", name.replace("_", " "))
                    p.label(name)
                    p.converted.add(len(p.tagged) - 1)
        if f.change_pct is not None:
            p.put(f.change_pct, "percent", None)
        if f.lookback_days is not None:
            p.put(f.lookback_days, "count", None)
            p.metas[len(p.tagged) - 1] = "lookback_days"
        p.dates |= {d for d in (f.latest_period, f.base_period) if d is not None}
        for k, v in f.also.items():          # million_barrels, million_barrels_per_day
            p.put(v, "amount", k.replace("_", " "))
            p.converted.add(len(p.tagged) - 1)
        p.text(f.name)
        p.ids(f.series_id)
        p.label(f.units, f.name, " ".join(f.also))
    for s in answer.spreads:
        for x in (s.value_a, s.value_b, s.spread):
            p.put(x, "amount", s.units)
        for k, v in s.extras.items():
            p.add(k, v, s.units)
        p.dates.add(s.period)
        p.text(s.name_a, s.name_b, s.note)
        p.ids(s.series_a, s.series_b)
        p.context(s.context)
        p.label(s.units, s.name_a, s.name_b)
    for r in answer.readings:
        for k, v in r.values.items():
            p.add(k, v, r.value_units.get(k))   # no entry: a reading of mixed units, its unit is not known
            if k.lower().split(".")[-1] in _META_KEYS:
                p.metas[len(p.tagged) - 1] = k.split(".")[-1]
            # a value in thousand barrels may be written in million barrels, as a fact's may (`also`): code converts,
            # so "about 417.8 million barrels" for 417,797 thousand is checked against 417.797 (the adversary's P11)
            for name, conv in also_in(r.value_units.get(k) or "", v).items():
                p.put(conv, "amount", name.replace("_", " "))
                p.label(name)
                p.converted.add(len(p.tagged) - 1)
            # a window of N years may be written in months ("over 36 months", the adversary)
            if k.lower().split(".")[-1] in ("years", "lookback_years") and float(v).is_integer():
                p.put(12 * v, "count", None)
                p.metas[len(p.tagged) - 1] = "months"
            # a percentile point named p95 or p5 is written "the 95th percentile": its number is part of its name
            q = re.fullmatch(r"(?:.*\.)?p(\d{1,2})", k)
            if q:
                p.pctl_names.add(q[1])
        p.dates.add(r.period)
        p.text(r.title, r.note, r.counter)
        p.ids(r.key, " ".join(r.series_ids), " ".join(r.values))
        p.context(r.context, quotable=r.request is None)
        # the units a quoted number may carry: the reading's own. A server reading's text never adds to them; the
        # Librarian's own readings of mixed units (watch, evidence) state their units in their text, which stays.
        p.label(r.units, r.title, r.note, " ".join(r.values), "" if r.request else r.context)
    return p


def _rounds_to(value: float, written: float, decimals: int) -> bool:
    """Is `written` a valid rounding of `value` to the decimals it was written with? Signs are not
    compared here: "down 5.37" is a fall of 5.37, and the direction rule reads the word."""
    return abs(abs(value) - abs(written)) <= 0.5 * 10 ** -decimals + 1e-9


def _quotes(value: float, written: float, decimals: int) -> bool:
    """Is this number in the prose a quotation of that signed value? Stricter than `_rounds_to` for
    small whole numbers, so the 7 in "7 days" is not taken for a change of 7.10."""
    if decimals == 0 and abs(value) < 100:
        return abs(abs(value) - abs(written)) < 1e-9
    return _rounds_to(value, written, decimals)


def _parse(tok: str) -> tuple[float, int]:
    raw = tok.replace(",", "")
    return float(raw), (len(raw.split(".")[1]) if "." in raw else 0)


@dataclass
class Written:
    """The unit the prose puts on a number: "417,797 thousand barrels", "$3.81 a gallon", "1.38%"."""
    currency: str = ""     # dollars, cents, euros, pounds, or another country's dollars
    scale: str = ""        # thousand, million, billion
    noun: str = ""         # barrel, gallon, tonne, contract, rig, btu, cubic
    per: str = ""          # per barrel, per gallon, per day, per tonne, per btu
    pct: bool = False

    def any(self) -> bool:
        return bool(self.currency or self.scale or self.noun or self.per) or self.pct

    def words(self) -> str:
        parts = ([self.currency] if self.currency else []) + ([self.scale] if self.scale else []) + ([self.noun] if self.noun else [])
        return " ".join(parts + ([f"per {self.per}"] if self.per else []) + (["percent"] if self.pct else []))


_SCALES = {"thousand", "million", "billion", "trillion"}
_CURRENCY = {"dollars", "dollar", "cents", "cent", "euros", "euro", "eur"}
_NOUNS = {"barrel", "gallon", "tonne", "contract", "rig", "btu", "cubic"}
_PER_NOUNS = {"barrel", "gallon", "tonne", "day", "btu", "mwh", "therm"}


def _currency_of(unit: str) -> str:
    head = " ".join(_unit_words(unit)).partition(" per ")[0].split()
    return next((_CURRENCY_OF[w] for w in head if w in _CURRENCY_OF), "")


def _unit_words(text: str) -> list[str]:
    """The words of a unit, normalised as unit_key normalises a unit: barrels -> barrel, USD -> dollars, mb -> million
    barrel, "/" -> per."""
    out = []
    for w in re.findall(r"[a-z]+|/|%|[$€£]", text.lower()):
        out += (_SIGNS.get(w) or _UNIT_WORDS.get(w, w)).split() if w != "/" else ["per"]
    return out


# Units written glued to a number: 95.7mb/d, 417,797bbl, 5,576kb/d, 1.2bn, 30k (the adversary, round 5)
_SUFFIX = {"mb": "million barrel", "kb": "thousand barrel", "b": "barrel", "bbl": "barrel", "bbls": "barrel",
           "bpd": "barrel per day", "kbd": "thousand barrel per day", "mbd": "million barrel per day",
           "kt": "thousand tonne", "t": "tonne", "mt": "tonne", "bcf": "billion cubic", "tcf": "trillion cubic",
           "mmbtu": "million btu", "k": "thousand", "m": "million", "mn": "million", "mln": "million",
           "bn": "billion", "pct": "percent"}


_CURRENCY_PREFIX = {"USD": "dollars", "EUR": "euros", "GBP": "pounds"}

# EIA writes M for a thousand and MM for a million (Mbbl, MMbbl, Mb/d); IEA's and OPEC's mb/d is a million. Case
# decides, so these are read as written, before anything is lowercased (the adversary, 24 Nov 2026: "417.8 Mbbl"
# passed on the million-barrel figure code converts to, while it says 417.8 thousand barrels).
_CASED = {"MMbbl": "million barrel", "MMbbls": "million barrel", "MMBbl": "million barrel", "MMb": "million barrel",
          "MM": "million", "Mbbl": "thousand barrel", "Mbbls": "thousand barrel", "MBbl": "thousand barrel",
          "Mb": "thousand barrel", "kbbl": "thousand barrel", "kbbls": "thousand barrel"}


def glued_suffix(tok: str, whole: str) -> str:
    """The letters glued AFTER a number ("mb" of 95.7mb), "" when there are none (M1, USD97.72: letters before)."""
    i = whole.find(tok)
    return whole[i + len(tok):] if i >= 0 else ""


# A currency written before the number, with or without a space: "USD 65.93", "EUR 65.93", "$ 65.93" are money as
# "$65.93" is. Until 24 Nov 2026 only "$" right before the number and USD glued to it were read, so "Henry Hub trades
# at USD 65.93" passed on a percentile of 65.93 (the adversary's L2).
_CURRENCY_BEFORE = re.compile(r"(?:\b(?P<word>usd|eur|gbp|us\$|(?:c|ca|a|au|nz|hk|s)\$|dollars?|euros?|sterling)|"
                              r"(?P<sign>[$€£]))\s*$", re.I)
_WORD_CURRENCY = {"usd": "dollars", "us$": "dollars", "dollar": "dollars", "dollars": "dollars", "eur": "euros",
                  "euro": "euros", "euros": "euros", "gbp": "pounds", "sterling": "pounds"}


def _currency_before(clean: str, start: int) -> str:
    """The currency written right before the number, with or without a space: "USD 65.93", "€ 65.93", "£65.93",
    "$65.93" (the adversary's L2 and LF2). Another country's dollar ("C$ 65.93") is a currency of its own: it fits no
    series here."""
    m = _CURRENCY_BEFORE.search(clean[max(0, start - 12):start])
    if not m:
        return ""
    if m["sign"]:
        return _SIGNS[m["sign"]]
    word = m["word"].lower()
    return _WORD_CURRENCY.get(word) or f"{word[:-1].upper()} dollars"


def written_unit(clean: str, start: int, end: int, whole: str, suffix: str = "") -> Written:
    """What unit, if any, the prose writes on the number at clean[start:end]: letters glued after it (`suffix`),
    then the words right after it up to the next comma, bracket or full stop, and a currency sign or USD before it."""
    w = Written(currency=_currency_before(clean, start) or _CURRENCY_PREFIX.get(whole[:3].upper(), ""))
    after = clean[end + len(suffix):end + len(suffix) + 48]
    tail = re.split(r"[,;:()\[\]]|\.(?:\s|$)", after)[0]
    first = re.match(r"(\s*)([A-Za-z]+)(?![A-Za-z0-9])", tail)
    if first and first[2] in _CASED:
        tail = first[1] + _CASED[first[2]] + tail[first.end():]
    head = (_CASED.get(suffix) or _SUFFIX.get(suffix.lower(), suffix.lower())).split() if suffix else []
    words, i = [_UNIT_WORDS.get(x, x) for x in head] + _unit_words(tail), 0
    if words[:1] == ["%"] or words[:1] == ["percent"] or words[:2] == ["per", "cent"] or words[:2] == ["percentage", "points"]:
        w.pct = True
        return w
    while i < len(words) and words[i] in _SCALES:
        w.scale, i = words[i], i + 1
    if i < len(words) and words[i] in _CURRENCY:
        w.currency, i = w.currency or _CURRENCY_OF.get(words[i], "dollars"), i + 1
    if i < len(words) and words[i] in _NOUNS:
        w.noun, i = words[i], i + 1
        if i < len(words) and words[i] == "feet":
            i += 1
    if i + 1 < len(words) and words[i] in ("per", "a", "an"):
        rest = [x for x in words[i + 1:i + 3] if x not in _SCALES]
        if rest and rest[0] in _PER_NOUNS:
            w.per = rest[0]
    elif w.noun and i < len(words) and words[i] == "daily":    # "5,576 thousand barrels daily", not "748 daily values"
        w.per = "day"
    return w


def fits(w: Written, unit: str | None) -> bool:
    """Can a value in `unit` be written with the unit `w`? A value of unknown unit (None) can: that is the rule as
    it stood before 21 Nov 2026, and stays so for readings whose values mix units."""
    if unit is None:
        return True
    if unit == "percent":
        return w.pct and not (w.currency or w.scale or w.noun or w.per)
    u = " ".join(_unit_words(unit))
    head, _, per = u.partition(" per ")
    if w.pct:
        return "percent" in u or "%" in u
    # the currency must be the value's own: dollars are not euros ("EUR 3.10 per million Btu" for a dollar price),
    # cents are not dollars, and another country's dollar is neither
    if w.currency and w.currency != _currency_of(unit):
        return False
    if w.scale and w.scale not in head.split():
        return False
    if w.noun and w.noun not in head.split():
        return False
    if w.per and w.per not in per.split():
        return False
    # Writing the measure ("barrels") commits to the whole unit: a value in Thousand Barrels written as "417,797
    # barrels" is a thousandfold error, and one in Thousand Barrels per Day written as "5,576 thousand barrels"
    # turns a rate into a stock (the adversary's held-out U06 and U10). A bare currency ("89.53 dollars" for a
    # price per barrel) commits to less, and stays allowed.
    if w.noun and set(head.split()) & _SCALES - {w.scale}:
        return False
    if w.noun and per and not w.per:
        return False
    return True


def text_problems(text: str, pool: Pool) -> list[str]:
    """Numbers and dates in one piece of prose that trace to nothing a tool returned.

    A number written WITH a unit must also match a value in that unit (since 21 Nov 2026, David: a price change of
    0.19 dollars a gallon written as "0.19 million barrels" passed, because the number and the unit were each true
    somewhere in the answer). A value whose unit code does not know is matched on its number alone."""
    bad = []
    for d in _ISO.findall(text):
        try:
            ok = dt.date.fromisoformat(d) in pool.dates
        except ValueError:
            ok = False
        if not ok:
            bad.append(d)
    bad += [f"{m.group().strip()} (write dates as YYYY-MM-DD)" for m in _LOOSE_DATE.finditer(text)]
    clean = _blank_dates(text)
    for m in _SPELLED.finditer(clean):
        if not clean[:m.start()].rstrip()[-1:].isdigit():  # "414,417 thousand barrels" is a unit, not a spelled number
            bad.append(f"{m.group()} (write the number in digits, from a tool result)")
    for tok, start, end, whole, glued in _numbers(clean):
        if glued and whole in pool.tokens:
            continue  # M12, PF4: a name a tool returned
        suffix = glued_suffix(tok, whole) if glued else ""
        if glued:
            # Fail closed (the adversary, round 6): letters glued to a number are a name only when a tool returned
            # the whole token, or it is a contract month (M1 to M12); a currency in front (USD5.94) is money; a unit
            # behind it must be one this module reads (95.7mb/d). Anything else could hide a unit no rule reads
            # ("95.7MMbbl/d" for a percent), so it is refused with the way to write it.
            prefix = whole[:whole.find(tok)] if whole.find(tok) >= 0 else ""
            if re.fullmatch(r"M(?:1[0-2]|[1-9])", whole):
                continue
            if (prefix and prefix.upper() not in _CURRENCY_PREFIX) or (suffix and suffix.lower() not in _SUFFIX):
                bad.append(f"{whole} (write the number apart from its letters, and the unit as a word)")
                continue
        unit = written_unit(clean, start, end, whole, suffix)
        if not glued and not unit.any() and pool.named(clean, start, end, tok):
            continue  # a number of a name, written beside its name's own words and without a unit of its own
        if not glued and not unit.any() and any(n == tok and _in_phrase(clean, start, end, word) for word, n in pool.phrases):
            continue  # week 46, week=46, the 46th week: a server text's parameter, as its phrase
        if not glued and tok in pool.hyphens and re.match(r"-[A-Za-z0-9]", clean[end:end + 2]):
            continue  # the 12 of "12-month", written hyphenated as the text writes it
        n, dp = _parse(tok)
        after = clean[end:end + 40]
        money = (bool(_MONEY.match(after)) or bool(_currency_before(clean, start))
                 or whole[:3].upper() in _CURRENCY_PREFIX)
        pct, count = bool(_PCT.match(after)), bool(_COUNT.match(after))
        kinds = ({"amount"} if money else {"amount", "percent"} if pct else {"count"} if count else {"amount", "percent", "count"})
        hits = [(i, u) for i, (v, kind, u) in enumerate(pool.tagged) if (kind in kinds or kind == "any") and _rounds_to(v, n, dp)]
        matches = [u for _, u in hits]
        if not matches:
            bad.append(whole if glued else tok)
            continue
        # A window or a count of the data (years 3, lookback_years 5, observations 747) is not a market figure: it
        # may be written only with its noun, "5 years", "747 observations" (the adversary, 24 Nov 2026: "US crude
        # stocks could fall 5 next week" passed on the seasonal reading's lookback of 5 years)
        if all(i in pool.metas for i, _ in hits) and not _META_NOUN.match(after) and not _meta_before(clean, start, pool, hits):
            bad.append(f"{tok} (a window or count of the data, not a market figure: write it with its noun, as in "
                       f"'{tok} years' or '{tok} observations')")
            continue
        # A figure code converted (thousand to million barrels) is written with its scale: the source says thousand,
        # and a unit word this module does not read ("417.8 mbbl") could carry the thousandfold error past the unit
        # rule (the adversary, 24 Nov 2026). Fail closed: a number that matches only converted figures says million.
        if all(i in pool.converted for i, _ in hits) and unit.scale != "million":
            bad.append(f"{tok} (a figure in million barrels: write million barrels after it)")
            continue
        # A value whose unit is known decides; a copy of the same number of unknown unit does not rescue a misfit
        # ("95.7 million barrels a day" for utilisation in Percent, rescued by an unlabelled snapshot metric of 95.7:
        # the adversary's held-out U08). Unknown-unit values count only when no known-unit value has the number.
        known = [u for u in matches if u is not None]
        # (a glued number that gets here has a currency in front or a unit behind it: both are tested)
        if unit.any() and not count and not (any(fits(unit, u) for u in known) if known else True):
            shown = sorted({u for u in matches if u})
            bad.append(f"{tok} {unit.words()} (the values {tok} matches are in {', '.join(shown) or 'no unit'})")
            continue
        scale, per = _SCALE.match(after), _PER.match(after)
        if scale and scale.group(1).lower() not in pool.units:
            bad.append(f"{tok} {scale.group(1)} (no cited series is in that unit)")
        elif per and unit_key(per.group(1)) not in pool.units:
            bad.append(f"{tok} per {per.group(1)} (no cited series is in that unit)")
    return bad


def _meta_before(clean: str, start: int, pool: Pool, hits: list) -> bool:
    """Is a window or count of the data written with its noun, or its own key, right before it: "observations 747",
    "lookback_years 5", "a window of 90", "n = 747"?"""
    keys = {re.escape(pool.metas[i]) for i, _ in hits if pool.metas.get(i)}
    alt = "|".join(sorted(keys) + [_META_NOUNS, "n"])
    return bool(re.search(rf"\b(?:{alt})\s*(?:[:=]|of|is|was|are|were)?\s*$", clean[max(0, start - 48):start], re.I))


def _in_phrase(clean: str, start: int, end: int, word: str) -> bool:
    """Is the number at clean[start:end] written as the parameter phrase: "week 46", "week=46", "the 46th week of the
    year"? Not "the 46th week of decline" or "week 46 of their decline": a week of the year, not a count of weeks (the
    adversary's G2a, 24 Nov 2026)."""
    w = re.escape(word)
    if re.search(rf"\b{w}\s*=?\s*$", clean[:start], re.I):
        return not re.match(rf"\s+of\s+(?!{_YEARLY})", clean[end:], re.I)
    return bool(re.match(rf"(?:st|nd|rd|th)\s+{w}\s+of\s+{_YEARLY}", clean[end:], re.I))


# What a week of the year may be "of": the year, each year, each of the last five years (the adversary's B6: "week 46
# of each of the last five years" was refused by the G2a fix in 1b631ca)
_YEARLY = r"(?:the\s+year|(?:each|every)\s+year|(?:each|every)\s+of\s+the\s+(?:last|past|previous)\s+\w+\s+years)\b"


def model_caveats(answer: DeskAnswer) -> list[str]:
    return [c for c in answer.caveats if not c.startswith(CODE_CAVEATS)]


_YEARWORD = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
             "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40}
_WINDOW = re.compile(r"\b(\d{1,2}|" + "|".join(_YEARWORD) + r")(?:-|\s+)(?:(?:earlier|prior|previous|past|last)\s+)?years?\b", re.I)


def _years_in(text: str) -> set[int]:
    return {int(m[1]) if m[1].isdigit() else _YEARWORD[m[1].lower()] for m in _WINDOW.finditer(text)}


def window_problems(answer: DeskAnswer) -> list[str]:
    """A window named in words ("the five-year average", "over ten years") must be one a reading or fact used.
    Until 21 Nov 2026 the words were free: a three-year seasonal average written as "five-year" passed (the
    adversary). Allowed: the years a reading names in its values (years, lookback_years ...) or its own text,
    a fact's lookback in whole years, a spread's percentile_years."""
    allowed: set[int] = set()
    for r in answer.readings:
        allowed |= {int(v) for k, v in r.values.items() if "years" in k.lower().split(".")[-1] and float(v).is_integer()}
        # a window named in a value's own name: us_stocks_vs_5y_pct
        allowed |= {int(t[:-1]) for k in r.values for t in re.split(r"[._]", k.lower()) if re.fullmatch(r"\d{1,2}y", t)}
        # a window counted in weekly reports: positioning's percentile_weeks of 156 is three years (the live gate
        # refused "the three-year range" on 21 Nov 2026)
        allowed |= {round(v / 52) for k, v in r.values.items() if k.lower().endswith("weeks") and v >= 50}
        allowed |= _years_in(" ".join((r.title, r.note, r.context, r.counter)))
    for f in answer.facts:
        if f.lookback_days and f.lookback_days >= 300:
            allowed.add(round(f.lookback_days / 365.25))
    for s in answer.spreads:
        allowed |= {int(v) for k, v in s.extras.items() if k.endswith("years")}
        allowed |= _years_in(s.context + " " + s.note)
    out = []
    sentences = [x for text in [answer.summary, *model_caveats(answer)] for x in re.split(r"(?<=[.;!?])\s+", text)]
    for text in sentences:
        # "I could not pull the five-year history", "no five-year comparison was requested": what is missing
        if re.search(r"\b(?:not|no|cannot|unable|without|none|lacks?|missing)\b|n't\b", text, re.I):
            continue
        for m in _WINDOW.finditer(text):
            n = int(m[1]) if m[1].isdigit() else _YEARWORD[m[1].lower()]
            if n not in allowed:
                out.append(f"{m.group().strip()} (no reading or fact uses a window of {n} years"
                           + (f"; they use {sorted(allowed)}" if allowed else "") + ")")
    return out


def untraceable(answer: DeskAnswer) -> list[str]:
    """Numbers and dates in the summary and in the model's caveats that trace to nothing, and windows named in
    words that no reading used."""
    pool = pool_of(answer)
    return [b for text in [answer.summary, *model_caveats(answer)] for b in text_problems(text, pool)] + window_problems(answer)


# A caveat is for the reader. One that talks about the machinery (reading keys, the facts list, tool
# names, series IDs) tells a visitor nothing and is removed.
_PLUMBING = re.compile(r"\b(?:facts|series facts?|series lookups?|cited readings?|reading keys?|tool calls?|tool results?|"
                       r"get_[a-z_]+|search_series|(?:was|were|been) (?:not )?requested|not asked for)\b|"
                       r"\b[a-z]+:[a-z_0-9]+\b|\b[A-Z][A-Z_]+\.[A-Z0-9_.-]+\b")


def echoes(text: str, asked: str, words: int) -> bool:
    """Does `text` repeat `words` or more consecutive words of what the visitor wrote? A visitor who
    asks for a sentence "exactly" must not see it come back as The Librarian's own, under the tick."""
    mine = re.findall(r"[a-z0-9']+", text.lower())
    theirs = " " + " ".join(re.findall(r"[a-z0-9']+", asked.lower())) + " "
    return any(" " + " ".join(mine[i:i + words]) + " " in theirs for i in range(len(mine) - words + 1))


ECHO_CAVEAT, ECHO_SUMMARY = 6, 12  # a summary may restate the question's terms; a caveat has no reason to


def clean_caveats(answer: DeskAnswer, plumbing: bool = True, asked: str = "") -> list[str]:
    """The model's caveats, minus any that states a number or date no tool returned, points a
    direction the data does not, or talks about the machinery. A caveat is where a number goes
    when the summary may not hold it, so the summary's rules apply there too."""
    pool = pool_of(answer)
    return [c for c in model_caveats(answer)
            if not text_problems(c, pool) and not direction_problems(answer, c)
            and not (plumbing and _PLUMBING.search(c)) and not (asked and echoes(c, asked, ECHO_CAVEAT))]


# ---- direction -------------------------------------------------------------------------------

_CHANGE_UP = {"up", "rose", "risen", "rise", "rising", "increase", "increased", "gain", "gained", "climbed", "jumped",
              "build", "built", "grew", "added", "raised", "lengthened", "bought", "higher"}
_CHANGE_DOWN = {"down", "fell", "fallen", "fall", "falling", "decrease", "decreased", "decline", "declined", "dropped",
                "drop", "draw", "drew", "shrank", "lost", "cut", "reduced", "trimmed", "slipped", "shed", "sold", "lower"}
_LEVEL_UP, _LEVEL_DOWN = {"above", "over", "premium"}, {"below", "under", "beneath", "discount"}
_AVERAGE = {"average", "norm", "usual", "mean"}
_SMALL = {"a", "an", "the", "its", "on", "of", "per", "date"}
_NEGATION = {"not", "no", "longer", "unlike", "never", "isn", "neither", "nor", "without", "than"}
_HIGH = {"high", "highest", "top", "upper", "elevated", "rich"}
_LOW = {"low", "lowest", "bottom", "lower", "depressed", "cheap"}
# "stretched" names either tail, as the watch's own flag does ("funds are stretched short", readings.watch): the side
# word after it decides. It sat in _HIGH until 24 Nov 2026 and sent the watch's true sentence back in most runs.
# "Stretched long" counts as a high word and "stretched short" as a low one where they are WRONG; neither excuses a
# plain word of the other side: "high and stretched short, at the 1.9 percentile" is refused (the adversary's H2b).
_STRETCHED = {"long": "high", "short": "low"}
_SHAPES = ("backwardation", "contango")


def _words(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9]*", text)} - _SMALL


def _signed(answer: DeskAnswer) -> tuple[list[float], list[tuple[float, set[str], set[str]]], list[float]]:
    """(changes, levels, quiet changes). A level is (value, words for the first thing, words for the second):
    positive means the first is above the second. A quiet change is a snapshot metric that is itself a change
    ("QoQ change of 0.55", the server's own words): it needs no direction word, but a wrong one is still wrong."""
    moves: list[float] = []
    quiet: list[float] = []
    levels: list[tuple[float, set[str], set[str]]] = []
    for f in answer.facts:
        moves += [x for x in (f.change_abs, f.change_pct) if x]
        if f.change_abs:  # the change in million barrels (pool_of) is a change too
            moves += list(also_in(f.units or "", f.change_abs).values())
    for s in answer.spreads:
        a, b = _words(s.name_a), _words(s.name_b)
        if s.spread:
            levels.append((s.spread, a - b, b - a))
    for r in answer.readings:
        for k, v in r.values.items():
            if not v:
                continue
            if "change" in k:
                # A usual change (the norm for the time of year, readings.evidence) is a yardstick, not this period's
                # move. Beside a change of the same sign it needs no direction word of its own: "a build of 5,280
                # against a usual 5,492" carries "build" over (the sweep's crude_tight send-back, 24 Nov 2026). Of the
                # other sign it needs its own, or the reader carries the wrong one over. A wrong word is refused either way.
                vals = [v, *also_in(r.value_units.get(k) or "", v).values()]
                partner = r.values.get(k.replace("usual_", "")) if "usual_" in k else None
                same_way = partner is not None and partner * v > 0
                (quiet if k.startswith("metric.") or same_way else moves).extend(vals)
            elif "_minus_" in k:
                a, b = (_words(part.replace("_", " ")) for part in k.split("_minus_", 1))
                levels.append((v, a - b, b - a))
            elif k in ("difference", "difference_pct", "delta_vs_avg", "pct_vs_avg") or k.endswith("_vs_5y_pct"):
                levels.append((v, set(), _AVERAGE))
    return moves, levels, quiet


def _shape_problems(answer: DeskAnswer, words: list[str]) -> list[str]:
    """A curve's shape word must be the reading's own, and not negated."""
    notes = [re.match(r"[a-z]+", r.note.lower()) for r in answer.readings if r.key.startswith("curve:")]
    shapes = {m.group() for m in notes if m}
    if len(shapes) != 1 or not shapes <= set(_SHAPES):
        return []  # no curve, two curves of different shape, or a mixed curve: nothing to hold the prose to
    right = shapes.pop()
    wrong = _SHAPES[1 - _SHAPES.index(right)]

    def uses(shape: str) -> tuple[bool, bool]:  # (said plainly, said at all)
        at = [i for i, w in enumerate(words) if w.startswith(shape[:9])]
        return any(not set(words[max(0, i - 3):i]) & _NEGATION for i in at), bool(at)

    right_plain, right_any = uses(right)
    wrong_plain, _ = uses(wrong)
    if wrong_plain:
        return [f"the summary says {wrong}; the curve is in {right}"]
    if right_any and not right_plain:
        return [f"the summary denies {right}; the curve is in {right}"]
    return []


def _slope_problems(answer: DeskAnswer, words: set[str]) -> list[str]:
    """'Steepened' or 'flattened' must be the word the curve reading itself wrote."""
    said = {w for w in ("steepened", "flattened") for r in answer.readings if r.key.startswith("curve:") and f"has {w}" in r.context}
    if len(said) != 1:
        return []
    right = said.pop()
    wrong = "flattened" if right == "steepened" else "steepened"
    if any(w.startswith(wrong[:6]) for w in words) and not any(w.startswith(right[:6]) for w in words):
        return [f"the summary says the curve {wrong}; the reading says it {right}"]
    return []


def direction_problems(answer: DeskAnswer, text: str | None = None) -> list[str]:
    """Direction words that contradict the data, and quoted changes with no direction at all.
    Reads the summary, or `text` when one of the model's caveats is being checked."""
    text = answer.summary if text is None else text
    lowered = [w.lower() for w in re.findall(r"[A-Za-z]+", text)]
    all_words = set(lowered)
    problems = _shape_problems(answer, lowered) + _slope_problems(answer, all_words)
    changes = [c for f in answer.facts if (c := f.change_abs) is not None and c != 0]
    signs = {c > 0 for c in changes}
    if len(signs) == 1:
        rose = signs.pop()
        right_set, wrong_set = (_CHANGE_UP, _CHANGE_DOWN) if rose else (_CHANGE_DOWN, _CHANGE_UP)
        if all_words & wrong_set and not all_words & right_set:
            problems.append(f"the summary uses {sorted(all_words & wrong_set)} but every change in the facts is "
                            f"{'a rise' if rose else 'a fall'}; say so in plain words")
    if changes and "unchanged" in all_words:
        problems.append("the summary says unchanged; the facts show a change")
    moves, levels, quiet = _signed(answer)
    pool = pool_of(answer)
    clean = _blank_dates(text)
    for sentence in re.split(r"(?<=[.!?;:])\s+", clean):
        found = list(_TOKEN.finditer(sentence))
        toks = [("num", m.group().rstrip(",")) if m.lastgroup == "num" else ("word", m.group().lower()) for m in found]
        commas = [m.start() for m in re.finditer(r",(?!\d)", sentence)]
        sentence_words = {w for k, w in toks if k == "word"}
        seq = [w for k, w in toks if k == "word"]
        stretched = {_STRETCHED[b] for a, b in zip(seq, seq[1:]) if a == "stretched" and b in _STRETCHED}
        says_high = sentence_words & _HIGH or "high" in stretched
        says_low = sentence_words & _LOW or "low" in stretched
        for i, (kind, tok) in enumerate(toks):
            if kind != "num":
                continue
            n, dp = _parse(tok)
            loud = {v > 0 for v in moves if _quotes(v, n, dp)}
            move_signs = loud | {v > 0 for v in quiet if _quotes(v, n, dp)}
            if len(move_signs) == 1:
                rose = move_signs.pop()
                lead = sentence[:found[i].start()].rstrip()
                sign = lead[-1:] if lead[-1:] in "+-−" and not lead[-2:-1].isalnum() else ""
                before = [w for k, w in reversed(toks[max(0, i - 8):i]) if k == "word"]
                said = (sign == "+") if sign else next((w in _CHANGE_UP for w in before if w in _CHANGE_UP | _CHANGE_DOWN), None)
                if said is None:
                    after = [w for k, w in toks[i + 1:i + 4] if k == "word"]
                    said = next((w in _CHANGE_UP for w in after if w in ("higher", "lower", "up", "down")), None)
                if said is None and loud:
                    problems.append(f"'{tok}' is a change: write rose or fell (or up, down, a sign) right beside it")
                elif said is not None and said != rose:
                    problems.append(f"'{tok}' is described as a {'rise' if said else 'fall'}; the data shows a "
                                    f"{'rise' if rose else 'fall'}")
            hits = [(v, a, b) for v, a, b in levels if _quotes(v, n, dp)]
            if len(hits) == 1:
                v, a, b = hits[0]
                # A level word and the thing it points at are read only up to the next comma: past it,
                # the words belong to another clause.
                stop = next((c for c in commas if c > found[i].end()), len(sentence))
                rest = [w for (k, w), m in zip(toks[i + 1:], found[i + 1:]) if k == "word" and m.start() < stop]
                lead_words = [w for k, w in toks[max(0, i - 4):i] if k == "word"]
                word = next((w for w in reversed(lead_words) if w in ("premium", "discount")), None)
                tail = rest
                if word is None:
                    at = next((j for j, w in enumerate(rest[:4]) if w in _LEVEL_UP | _LEVEL_DOWN), None)
                    if at is not None:
                        word, tail = rest[at], rest[at + 1:]
                target = next((w for w in tail[:6] if w in a | b), None) if word else None
                if target is not None:
                    expect_above = (v > 0) if target in b else (v < 0)
                    if (word in _LEVEL_UP) != expect_above:
                        problems.append(f"'{tok}' with '{word}' points the wrong way; the data has it the other way round")
            ranks = [v for v in pool.percentiles if _rounds_to(v, n, dp)]
            others = [t for k, t in toks if k == "num" and t != tok and any(_rounds_to(v, *_parse(t)) for v in pool.percentiles)]
            if others:
                ranks = []  # two percentiles in one sentence: "low" may belong to the other one
            if ranks and all(v >= 75 for v in ranks) and says_low and not sentence_words & _HIGH:
                problems.append(f"percentile {tok} is called low; it is high")
            if ranks and all(v <= 25 for v in ranks) and says_high and not sentence_words & _LOW:
                problems.append(f"percentile {tok} is called high; it is low")
    return list(dict.fromkeys(problems))
