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

Every text is read as it is shown (`normal`, 25 Nov 2026): raised, lowered, full-width and circled digits are digits,
on both sides (the prose and every text a tool returned); unit glyphs (m², CO₂), notation (R², C₃, MTCO₂e) and the
ellipsis stay as written; a fraction sign, a direction control or a footnote digit (after a word, a digit or a stop)
is refused with the way to write it.

Not checked, and stated as limits in the README: two true values or dates attached to the wrong
nouns when they share a unit (Brent's price given to WTI), and claims made in words alone ("a record high", "has narrowed" where no earlier value was
returned). A short number such as "2" matches any returned value between 1.5 and 2.5, so the chance
of an accidental match grows with the number of values cited.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field

from .models import DeskAnswer

# Caveats written by code start with one of these. The validator removes any the model wrote with
# the same opening and appends its own, so the prefix marks text that needs no tracing.
CODE_CAVEATS = ("Not current as of ", "Against the balance of the evidence: ", "Not like for like: ",
                "Average-price contract: ", "Shorter history: ")


# ---- the text as a reader sees it -----------------------------------------------------------------------------------
# Every check reads text through `normal` (25 Nov 2026, the adversary's B): until then a raised or lowered digit was
# no digit to the checks, so "WTI will reach $¹⁵⁰" and "a fall to $₈₀" passed while "$150" was refused. NFKC makes
# raised, lowered, full-width, circled and mathematical digits plain digits (and full-width letters, %, $ plain), so
# they are read and checked as the numbers they show. Applied to both sides alike: the summary, the caveats, the
# visitor's question (the echo rule) and every text a tool returned (names, ids, units, notes, contexts, value keys).
# Kept as written, so they read as before (no number): the unit and formula glyphs below (m², m³, CO₂, CH₄ ...), the
# squared unit signs (㎡), and the ellipsis (NFKC writes "…" as three full stops, which would end the sentence there:
# "WTI fell… 17.26% over 30 days" would lose its verb; the reviewer, 25 Nov 2026); °C and ‰ have no digit. Refused
# with a plain message (`_glyph_problems`): a fraction sign (½, or the fraction slash NFKC writes for it: "1½" would
# read as 11⁄2), a direction control (it can reorder what is shown), and a raised digit that reads as a footnote mark:
# glued to a word of two or more letters ("WTI²", "settlement³"), to a digit ("1.20¹") or to closing punctuation
# ("days.¹"). Notation is kept as written, as d029c9c read it (no number; the reviewer of 906e707, 25 Nov 2026: "R²",
# "σ²", "C₃", "MTCO₂e" and "lbCO₂" were refused as footnotes): a lowered digit after a letter (a formula or an index:
# CO₂, C₅+, MTCO₂e) and a raised digit after a single letter (an exponent: R², σ², x²). Zero-width characters are
# dropped: "1\u200b50" shows as 150 and is read as 150. Ported from live-fixes-2 (2064ff0) with the ellipsis kept whole.
_SQUARES = "".join(chr(c) for c in range(0x3300, 0x3400) if unicodedata.decomposition(chr(c)).startswith("<square>"))
_PROTECTED = re.compile(
    r"(?<![A-Za-z])(?:Nm|Sm|km|cm|mm|dm|dam|hm|Mm|MMm|Gm|Tm|m|ft|in|yd|mi)[²³](?![A-Za-z0-9²³⁰¹⁴-⁹])"
    r"|(?<![A-Za-z0-9])(?:t|kt|Mt|Gt|kg|g)?(?:CO[₂²](?:eq|e)?|CH₄|N₂O|SO₂|NO₂|H₂S|H₂O|H₂|O₂|O₃|N₂|NH₃|C₂H₆|C₃H₈|C₄H₁₀|C₂H₄|"
    r"C₃H₆)(?![A-Za-z0-9₀-₉])"
    rf"|[\u2025\u2026\ufe19{_SQUARES}]+")
_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad\u180e"))
_BIDI = re.compile("[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_RAISED_LOWERED = re.compile("[⁰¹²³⁴-⁹₀-₉]")
_RAISED = re.compile("[⁰¹²³⁴-⁹]+")
_LOWERED = re.compile("[₀-₉]+")
_CLOSING = set(".,;:!?)]}%\"'\u2019\u201d\u00bb")
# A lowered digit after one of these is a number, not notation: a currency code or a plain lowercase word never takes a
# formula's index ("USD₈₀", "to₈₀": the reviewer of 6f63817, 25 Nov 2026). Matched as written, so a chemical symbol
# that looks like one ("As₂O₃", "In₂O₃") stays notation.
_NOT_NOTATION = {"USD", "EUR", "GBP", "usd", "eur", "gbp", "to", "of", "at", "in", "on", "by", "for", "and", "or", "from",
                 "with", "is", "was", "are", "be", "as", "up", "down", "over", "under", "than", "per", "its", "it", "the",
                 "an", "near", "about", "around", "above", "below"}


def _kept(text: str) -> list[tuple[int, int]]:
    """The spans `normal` keeps as written, in order: the unit and formula glyphs, the ellipsis, and notation (a lowered
    digit after a letter, not after a currency code or a plain word; a raised digit after a single letter; `str.isalpha`,
    so a digit is never the letter)."""
    spans = [m.span() for m in _PROTECTED.finditer(text)]
    for m in _LOWERED.finditer(text):
        if m.start() and text[m.start() - 1].isalpha():
            if re.search(r"[^\W\d_]+$", text[:m.start()])[0] not in _NOT_NOTATION:
                spans.append(m.span())
    for m in _RAISED.finditer(text):
        i = m.start()
        if i and text[i - 1].isalpha() and (i == 1 or not (text[i - 2].isalpha() or text[i - 2] in "'\u2019-")):
            spans.append(m.span())
    out: list[tuple[int, int]] = []
    for a, b in sorted(spans):
        if out and a < out[-1][1]:
            out[-1] = (out[-1][0], max(b, out[-1][1]))
        else:
            out.append((a, b))
    return out


def normal(text: str) -> str:
    """`text` as the checks read it: NFKC, zero-width characters dropped, the unit glyphs, notation and the ellipsis
    kept (see above). An all-ASCII text comes back unchanged."""
    if text.isascii():
        return text
    text = text.translate(_INVISIBLE)
    out, at = [], 0
    for a, b in _kept(text):
        out += [unicodedata.normalize("NFKC", text[at:a]), text[a:b]]
        at = b
    return "".join(out) + unicodedata.normalize("NFKC", text[at:])


def _glyph_problems(text: str) -> list[str]:
    """What `normal` cannot read safely, each with the way to write it."""
    if text.isascii():
        return []
    text = text.translate(_INVISIBLE)
    bad = [f"U+{ord(m.group()):04X} (a direction control character, which can reorder what is shown: write plain text)"
           for m in _BIDI.finditer(text)]
    bad += [f"{ch} (write the number in digits, as a decimal)" for ch in dict.fromkeys(text)
            if "⁄" in unicodedata.normalize("NFKC", ch)]
    kept = _kept(text)
    for m in _RAISED_LOWERED.finditer(text):
        i = m.start()
        if any(a <= i < b for a, b in kept) or i == 0 or _RAISED_LOWERED.match(text[i - 1]):
            continue
        before = unicodedata.normalize("NFKC", text[i - 1])
        decimal = before in ".," and i > 1 and normal(text[i - 2]).isdigit()
        stop = before in _CLOSING and _RAISED.match(text, i) and not decimal
        if before.isalnum() or stop:   # "1.20¹", "WTI²", "days.¹"; not the decimal point of "⁸⁸.¹⁰" or "88.¹⁰"
            word = re.search(r"\S*$", text[:i + 1])[0][-12:]   # the word it is glued to, as written
            bad.append(f"{word} (a raised or lowered digit after a word, a digit or a stop reads as a footnote mark or "
                       "part of the number: write numbers in plain digits, apart from words)")
    return list(dict.fromkeys(bad))


def _fold(x):
    if isinstance(x, str):
        return normal(x)
    if isinstance(x, list):
        return [_fold(v) for v in x]
    if isinstance(x, dict):
        return {(normal(k) if isinstance(k, str) else k): _fold(v) for k, v in x.items()}
    return x


def _normal_answer(answer: DeskAnswer) -> DeskAnswer:
    """The answer with every text in it read through `normal`: its own sentences and everything the tools returned
    (fact names, ids and units; spread names, notes and contexts; reading keys, titles, notes, contexts, counters,
    units and value keys). The same object when nothing changes, which is every all-ASCII answer."""
    data = answer.model_dump()
    folded = _fold(data)
    return answer if folded == data else DeskAnswer.model_validate(folded)

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
    # entries of `tagged` that are a change's base value (a fact's base_value and code's million-barrel figure of it),
    # with its own date: quotable with that date or none (`_base_problem`)
    bases: dict[int, set[dt.date]] = field(default_factory=dict)
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
    answer = _normal_answer(answer)
    p = Pool()
    for f in answer.facts:
        for which, x in (("latest", f.latest_value), ("base", f.base_value), ("change", f.change_abs)):
            if x is not None:
                p.put(x, "amount", f.units)
                if which == "base" and f.base_period is not None:
                    p.bases.setdefault(len(p.tagged) - 1, set()).add(f.base_period)
                # the year-ago level and the change may be written in million barrels, as the latest may (`also`):
                # code converts all three (24 Nov 2026; the sweep's us_crude_yoy send-back, "427.58")
                for name, conv in also_in(f.units or "", x).items():
                    p.put(conv, "amount", name.replace("_", " "))
                    p.label(name)
                    p.converted.add(len(p.tagged) - 1)
                    if which == "base" and f.base_period is not None:
                        p.bases.setdefault(len(p.tagged) - 1, set()).add(f.base_period)
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
    somewhere in the answer). A value whose unit code does not know is matched on its number alone.

    The text is read as it is shown (`normal`): a raised, lowered or full-width digit is a digit."""
    bad = _glyph_problems(text)
    text = normal(text)
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
        if all(i in pool.bases for i, _ in hits):
            problem = _base_problem(text, clean, start, end, tok, set().union(*(pool.bases[i] for i, _ in hits)))
            if problem:
                bad.append(problem)
    return bad


# ---- a base value beside another value's date (live item 3, 25 Nov 2026) --------------------------------------------
# A change's base value is quotable with its own date or with none. Until then any returned date could stand beside it:
# with get_change at a lookback of 6717 days (WTI's base 139.69 on 2008-06-27 in the frozen data), "As of 2026-11-17,
# WTI spot was $139.69 a barrel." passed (the adversary's 6.D, found on the sandbox, reproduced on d029c9c). Now a
# number that quotes nothing but base values, written as a level ("was $139.69", "traded at 139.69", "a price of",
# ": 139.69"), with a date of its own that is not the base's date, is sent back. Its date is the first date after it in
# the sentence (to a full stop or semicolon) with no other number between ("139.69 on 2026-11-17", "139.69 a barrel,
# on 2026-11-17", "USD139.69 ... (2026-11-17)"), else a date before it with no number before or after it up to the
# base ("As of 2026-11-17, WTI spot was ...", "WTI spot, from the 2026-11-17 data, was ...", "WTI's
# 2026-11-17-dated price was"): a date written after another number is that number's.
# Only the base's own data date is its own: never another value's, and never a date a tool was asked for.
# Read as before (not judged): a base written as where a move started or as a comparison ("from 139.69", "against",
# "versus", "than"), a clause that places it in another time or names it as a base ("earlier", "ago", "before",
# "then", "back", "at the time", "last month", "first", "start", "opening", "base", a year standing alone ...: any of
# these in its clause, up to the nearest comma), and a level written with any other word before it.
_BASE_LEVEL = re.compile(r"(?:\b(?:was|is|were|are|at|of|stood|stands|traded|trades|closed|closes|settled|settles|printed|"
                         r"prints|sat|sits|reached|reaches|hit|hits|fetched|fetches|cost|costs|priced|quoted)|[:=(,])\s*"
                         r"(?:usd|us\$|eur|gbp|[$\u20ac\u00a3])?\s*$", re.I)
_BASE_CUE = re.compile(
    r"\b(?:from|since|against|versus|vs|than|compared|comparison|relative|base|baseline|reference|first|earliest|oldest|"
    r"start|starts|started|starting|began|begin|begins|beginning|opening|opened|opens|initial|initially|earlier|previous|"
    r"previously|prior|old|original|originally|former|formerly|then|ago|before|back|once|used|when|while|high|highs|low|"
    r"lows|peak|peaked|trough|record|max|maximum|min|minimum|lookback|history|historical|historically|past|"
    r"at\s+the\s+time|(?:last|that|the\s+previous|the\s+prior)\s+(?:week|month|quarter|year|time|summer|winter|spring|autumn))\b"
    r"|(?<!\d)(?:19|20)\d\d(?!\d)", re.I)


# a joining word between a base and a date starts another clause, which the date belongs to ("WTI was 139.69, and on
# 2026-11-17 it was 89.53"); a date written after a determiner qualifies what follows it ("... and its 2026-11-17
# price 89.53")
_JOINED = re.compile(r"\b(?:and|but|while|whilst|whereas|yet|or|nor|so|though|although|because|after|before|since|"
                     r"until|when|then)\b", re.I)
_DATE_OF_NEXT = re.compile(r"(?:\b(?:its|their|the|a|an|this|that)|['’]s)\s*$", re.I)


def _base_problem(text: str, clean: str, start: int, end: int, tok: str, own: set[dt.date]) -> str | None:
    """The reason the base value written at clean[start:end] is sent back, or None (see above). `text` is `clean` with
    its dates, which `clean` blanks."""
    if not _BASE_LEVEL.search(clean[max(0, start - 24):start]):
        return None
    lo = max([m.end() for m in re.finditer(r"[;:()\[\]]|,(?!\d)", clean[:start])], default=0)
    hi = next((lo2.start() + end for lo2 in re.finditer(r"[;:()\[\]]|,(?!\d)|[.!?](?:\s|$)", clean[end:])), len(clean))
    if _BASE_CUE.search(clean, lo, hi):
        return None
    s0 = max([m.end() for m in re.finditer(r"[.!?;](?:\s|$)", text[:start])], default=0)
    stop = re.search(r"[.!?;](?:\s|$)", text[end:])
    s1 = end + stop.start() if stop else len(text)
    dates = [m for m in _ISO.finditer(text, s0, s1)]
    later = next((m for m in dates if m.start() >= end), None)
    earlier = next((m for m in reversed(dates) if m.end() <= start), None)
    if (later is not None and not _DIGITS.search(clean, end, later.start()) and not _JOINED.search(clean, end, later.start())
            and not _DATE_OF_NEXT.search(clean[:later.start()])):
        beside = later
    elif (earlier is not None and not _DIGITS.search(clean, earlier.end(), start) and not _DIGITS.search(clean, s0, earlier.start())
          and not _JOINED.search(clean, earlier.end(), start)):
        beside = earlier   # a date that follows another number is that number's ("26,147 on 2026-11-13 (27,594)")
    else:
        return None
    try:
        day = dt.date.fromisoformat(beside.group())
    except ValueError:
        return None
    if day in own:
        return None
    mine = ", ".join(sorted(d.isoformat() for d in own))
    return (f"{tok} (a base value, of {mine}, written beside {beside.group()}, another value's date: write it with its "
            f"own date, {mine}, or with none)")


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
    a fact's lookback in whole years, a spread's percentile_years. Read as shown (`normal`)."""
    answer = _normal_answer(answer)
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
    mine = re.findall(r"[a-z0-9']+", normal(text).lower())
    theirs = " " + " ".join(re.findall(r"[a-z0-9']+", normal(asked).lower())) + " "
    return any(" " + " ".join(mine[i:i + words]) + " " in theirs for i in range(len(mine) - words + 1))


ECHO_CAVEAT, ECHO_SUMMARY = 6, 12  # a summary may restate the question's terms; a caveat has no reason to


def clean_caveats(answer: DeskAnswer, plumbing: bool = True, asked: str = "") -> list[str]:
    """The model's caveats, minus any that states a number or date no tool returned, points a
    direction the data does not, or talks about the machinery. A caveat is where a number goes
    when the summary may not hold it, so the summary's rules apply there too."""
    pool = pool_of(answer)
    # read as shown: a caveat that only looks like code's ("Ｎot current as of ...") is dropped, as one that copies
    # code's opening exactly always was (code writes its own)
    return [c for c in model_caveats(answer)
            if not text_problems(c, pool) and not direction_problems(answer, c) and not normal(c).startswith(CODE_CAVEATS)
            and not (plumbing and _PLUMBING.search(normal(c))) and not (asked and echoes(c, asked, ECHO_CAVEAT))]


# ---- direction -------------------------------------------------------------------------------

_CHANGE_UP = {"up", "rose", "risen", "rise", "rising", "increase", "increased", "gain", "gained", "climbed", "jumped",
              "build", "built", "grew", "added", "raised", "lengthened", "bought", "higher"}
_CHANGE_DOWN = {"down", "fell", "fallen", "fall", "falling", "decrease", "decreased", "decline", "declined", "dropped",
                "drop", "draw", "drew", "shrank", "lost", "cut", "reduced", "trimmed", "slipped", "shed", "sold", "lower"}
_LEVEL_UP, _LEVEL_DOWN = {"above", "over", "premium"}, {"below", "under", "beneath", "discount"}
# Comparatives set the side of a gap between two named series as above and below do (live item 2, 25 Nov 2026: with
# Brent - WTI = +3.41, "Brent is $3.41 a barrel lower than WTI" and "WTI is $3.41 a barrel dearer than Brent" passed).
# Read only in the plain shape "<number> ... lower than <the other series>": the comparative within four words after
# the number, "than" right after it ("less expensive than", "more expensive than"), and the series named in the next
# two words. Not for a gap against an average, and never in place of above, below, premium or discount: where one of
# those is in the same four words it decides, as before.
_COMPARE_UP, _COMPARE_DOWN = {"higher", "dearer", "pricier", "expensive"}, {"lower", "cheaper", "less"}
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


# ---- a change named by its period (25 Nov 2026) ----------------------------------------------------------------------
# Until then a reading's value was a change only when its key said "change", so a key that names a change by its
# period was read as nothing at all: with the signals' metric.cushing_7d_pct at -4.05, "Cushing stocks rose 4.0% on
# the week" passed, and so did "rose 4.05%" and "are up 4%" (reproduced on d029c9c). Such a key is now a change with
# a side. The shapes, from the fixture's readings, the server's signal catalogue and engine._report: an N-day, -week,
# -month, -quarter or -year percent (cushing_7d_pct, eu_oil_imports_3m_pct), wow, yoy, mom, qoq, dod, chg and
# revision, with an optional _pct, and the report's own forms in another unit (Cushing, OK.wow_in_million_barrels).
# A key that says "change" was read before and is read as before. Like a server's other changes, such a value needs
# no direction word (the report and the signals quote them bare), but a wrong one is refused. Judged narrowly, so that
# no sentence d029c9c accepted becomes a refusal unless its word is wrong:
#   - only a number that no fact change or "change" value has (those are judged as before), that is a rounding, as
#     written, of such a value, in a unit that fits it, and of no other value in the answer;
#   - a whole number under 100 only with its unit ("up 4%", not "4 weeks running");
#   - the direction word must be the number's own: right before it, with only filler words between ("fell by 4.05%",
#     "rose a further 4%"); or higher, lower, up or down right after it, in its clause; or a sign;
#   - "given up" is a fall; a negation in the clause, or words before and after that disagree, leave it unjudged.
_PERIOD_CHANGE = re.compile(r"(?:^|_)(?:(?:wow|yoy|mom|qoq|dod|chg)(?:_pct|_percent)?|revisions?|\d+[dwmqy]_(?:pct|percent))"
                            r"(?:_in_[a-z_]+)?$")
_JOINING = {"and", "but", "while", "whilst", "whereas", "as", "after", "before", "though", "although", "even", "which",
            "who", "when", "where", "with", "since", "unlike", "despite", "yet", "or", "nor", "versus", "vs",
            "against", "because", "so", "if", "then", "whose"}
_GIVE = {"give", "gives", "gave", "given", "giving"}
# what may stand between a direction word and its number: "fell by 4.05%", "rose a further 4%", "fell more than 4%"
_FILLER = {"by", "of", "a", "an", "the", "some", "about", "around", "roughly", "nearly", "almost", "just", "over", "more",
           "less", "than", "further", "another", "fully", "sharply", "slightly", "modestly", "steeply", "strongly", "much",
           "only", "barely", "back"}
_CLAUSE_MARK = re.compile(r"[,;:()\[\]]|\s[\u2013\u2014-]\s")
_NEGATED = re.compile(r"\b(?:not|no|never|nor|neither|without|cannot)\b|n['\u2019]t\b", re.I)


def _period_changes(answer: DeskAnswer) -> list[tuple[float, str | None]]:
    """The values of the readings' keys that name a change by its period (see above), with the unit each is quoted in:
    "percent" for a percent, the reading's unit for the value and for code's million-barrel figure, None if unknown."""
    out: list[tuple[float, str | None]] = []
    for r in answer.readings:
        for k, v in r.values.items():
            last = k.lower().split(".")[-1].strip()
            if not v or "change" in k.lower() or not _PERIOD_CHANGE.search(last):
                continue
            unit = "percent" if _kind(k) == "percent" else r.value_units.get(k)
            out.append((v, unit))
            out += [(x, "million barrels" if "million" in name else None)
                    for name, x in also_in(r.value_units.get(k) or "", v).items()]
    return out


def _period_side(sentence: str, toks: list, found: list, i: int) -> bool | None:
    """The side the number toks[i] is given in its own clause: True for a rise, False for a fall, None for none or
    for one that cannot be told (see above)."""
    start = found[i].start()
    lead = sentence[:start].rstrip()
    if lead[-1:] in "+-\u2212" and not lead[-2:-1].isalnum():
        return lead[-1] == "+"

    def end_of(j: int) -> int:
        return found[j].start() + len(toks[j][1])
    before: list[str] = []
    first = start
    for j in range(i - 1, max(-1, i - 9), -1):
        kind, w = toks[j]
        if kind == "num" or w in _JOINING or _CLAUSE_MARK.search(sentence[end_of(j):first]):
            break
        before.append(w)
        first = found[j].start()
    after: list[str] = []
    last = end_of(i)
    for j in range(i + 1, min(len(toks), i + 4)):
        kind, w = toks[j]
        if kind == "num" or w in _JOINING or _CLAUSE_MARK.search(sentence[last:found[j].start()]):
            break
        after.append(w)
        last = end_of(j)
    if _NEGATED.search(sentence[first:last]):
        return None
    said = None
    for at, w in enumerate(before):   # the nearest first; only filler words may stand between it and the number
        if w in _CHANGE_UP | _CHANGE_DOWN:
            said = False if w == "up" and at + 1 < len(before) and before[at + 1] in _GIVE else w in _CHANGE_UP
            break
        if w not in _FILLER:
            break   # "Rising runs took 4.05% off Cushing": the word belongs to another noun
    later = next((w in _CHANGE_UP for w in after if w in ("higher", "lower", "up", "down")), None)
    if said is not None and later is not None and said != later:
        return None
    return said if said is not None else later


def _period_quoted(sentence: str, toks: list, found: list, i: int, tok: str, n: float, dp: int,
                   periods: list[tuple[float, str | None]], pool: "Pool") -> bool | None:
    """Is toks[i] a quote of a period change, and of nothing else in the answer? Its side (True a rise), or None."""
    start = found[i].start()
    if start and (sentence[start - 1].isalnum() or sentence[start - 1] == "."):
        return None   # glued to letters, or the decimals of another number
    unit = written_unit(sentence, start, start + len(tok), tok)
    small = dp == 0 and abs(n) < 100
    if small and not unit.any():
        return None   # "4 weeks running", "for 4 days": a bare whole number is not read as a period's change
    hits = [v for v, u in periods if _rounds_to(v, n, dp) and (not unit.any() or fits(unit, u))]
    if not hits or len({v > 0 for v in hits}) != 1:
        return None
    mine = {round(v, 9) for v, _ in periods}
    if any(_rounds_to(v, n, dp) and round(v, 9) not in mine and (not unit.any() or fits(unit, u))
           for v, kind, u in pool.tagged):
        return None   # the number may quote another value
    return hits[0] > 0


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


def _compared(rest: list[str], a: set[str], b: set[str], subject: set[str]) -> tuple[str | None, str | None]:
    """The comparative written after a gap's number and the series it compares with, in the plain shape only (see
    _COMPARE_UP): ("lower", "wti") for "Brent is 3.41 a barrel lower than WTI"; (None, None) otherwise. The other
    series must be the subject, named before the number in its clause, and the compared one not: in "The 3.41 spread
    is less than WTI's move" or "The Brent-WTI spread of 3.41 is lower than ..." the comparative is the gap's own."""
    for j, w in enumerate(rest[:4]):
        if w in _COMPARE_UP | _COMPARE_DOWN:
            k = j + 1 if w in ("less", "more") and rest[j + 1:j + 2] == ["expensive"] else j
            target = next((x for x in rest[k + 2:k + 4] if x in a | b), None) if rest[k + 1:k + 2] == ["than"] else None
            mine, other = (b, a) if target in b else (a, b)
            if target is None or not subject & other or subject & mine:
                return None, None
            return w, target
    return None, None


def direction_problems(answer: DeskAnswer, text: str | None = None) -> list[str]:
    """Direction words that contradict the data, and quoted changes with no direction at all.
    Reads the summary, or `text` when one of the model's caveats is being checked, as it is shown (`normal`)."""
    answer = _normal_answer(answer)
    text = normal(answer.summary if text is None else text)
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
    periods = _period_changes(answer)
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
            elif not move_signs and periods:
                rose = _period_quoted(sentence, toks, found, i, tok, n, dp, periods, pool)
                said = None if rose is None else _period_side(sentence, toks, found, i)
                if said is not None and said != rose:
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
                if word is None and a:   # a gap between two named series (a spread, a key a_minus_b), not an average
                    begin = max([c for c in commas if c < found[i].start()], default=-1)
                    subject = {w for (k, w), m in zip(toks[:i], found[:i]) if k == "word" and m.start() > begin}
                    word, target = _compared(rest, a, b, subject)
                if target is not None:
                    expect_above = (v > 0) if target in b else (v < 0)
                    if (word in _LEVEL_UP | _COMPARE_UP) != expect_above:
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
