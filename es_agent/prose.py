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
- every date is one a tool returned, written as YYYY-MM-DD. Month names, weekday names and quarters
  are rejected, because a date written in words cannot be traced; a bare year passes only as part
  of a returned name; only code writes today's date;
- direction. A change that is quoted must have a word of the right sign beside it, or an explicit
  sign ("rose 1.20", "+1.20"): denied by default, so an unlisted verb cannot slip through. A gap
  with "above", "below", "premium" or "discount" beside it must point the right way. A curve's shape
  word must be the reading's own and not negated; "steepened" or "flattened" must be the reading's
  own word; a high percentile may not be called low.

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
_MONEY = re.compile(r"\s*(?:usd|us\$|\$|dollars?|cents?)", re.I)
_PCT = re.compile(r"\s*(?:%|percent|per cent)", re.I)
_COUNT = re.compile(r"[\s-]*(?:days?|weeks?|years?|months?|lines?|observations?|reports?)\b", re.I)
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


@dataclass
class Pool:
    """Everything the tools returned that the prose may quote."""

    amounts: list[float] = field(default_factory=list)
    percents: list[float] = field(default_factory=list)
    counts: list[float] = field(default_factory=list)
    percentiles: list[float] = field(default_factory=list)  # a subset of percents: ranks, for the high/low rule
    dates: set[dt.date] = field(default_factory=set)
    names: set[str] = field(default_factory=set)    # plain numbers that are part of a name or of code-written text
    tokens: set[str] = field(default_factory=set)   # names that mix letters and digits: M12, PF4
    hyphens: set[str] = field(default_factory=set)  # whole numbers of a hyphenated term of a text: the 12 of 12-month
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
        for tok, _, _, whole, glued in _numbers(_blank_dates(joined)):
            (self.tokens if glued else self.names).add(whole if glued else tok)

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
        # A server text's parameters ("week=46") are names: they may be written, without a unit. A number written
        # with a unit still needs a value in that unit (the adversary's P11, 23 Nov 2026: the seasonal reading's own
        # first sentence, quoted back, was refused on its week number).
        if not quotable:
            self.names |= set(re.findall(r"\b[a-z_]+=(\d+)\b", _blank_dates(text)))
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
        if f.change_pct is not None:
            p.put(f.change_pct, "percent", None)
        if f.lookback_days is not None:
            p.put(f.lookback_days, "count", None)
        p.dates |= {d for d in (f.latest_period, f.base_period) if d is not None}
        for k, v in f.also.items():          # million_barrels, million_barrels_per_day
            p.put(v, "amount", k.replace("_", " "))
        p.text(f.name, f.series_id)
        p.label(f.units, f.name, " ".join(f.also))
    for s in answer.spreads:
        for x in (s.value_a, s.value_b, s.spread):
            p.put(x, "amount", s.units)
        for k, v in s.extras.items():
            p.add(k, v, s.units)
        p.dates.add(s.period)
        p.text(s.name_a, s.series_a, s.name_b, s.series_b, s.note)
        p.context(s.context)
        p.label(s.units, s.name_a, s.name_b)
    for r in answer.readings:
        for k, v in r.values.items():
            p.add(k, v, r.value_units.get(k))   # no entry: a reading of mixed units, its unit is not known
            # a value in thousand barrels may be written in million barrels, as a fact's may (`also`): code converts,
            # so "about 417.8 million barrels" for 417,797 thousand is checked against 417.797 (the adversary's P11)
            for name, conv in also_in(r.value_units.get(k) or "", v).items():
                p.put(conv, "amount", name.replace("_", " "))
                p.label(name)
            # a window of N years may be written in months ("over 36 months", the adversary)
            if k.lower().split(".")[-1] in ("years", "lookback_years") and float(v).is_integer():
                p.put(12 * v, "count", None)
            # a percentile point named p95 or p5 is written "the 95th percentile": its number is part of its name
            q = re.fullmatch(r"(?:.*\.)?p(\d{1,2})", k)
            if q:
                p.names.add(q[1])
        p.dates.add(r.period)
        p.text(r.title, r.note, r.counter, r.key, " ".join(r.series_ids), " ".join(r.values))
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
    currency: bool = False
    scale: str = ""        # thousand, million, billion
    noun: str = ""         # barrel, gallon, tonne, contract, rig, btu, cubic
    per: str = ""          # per barrel, per gallon, per day, per tonne, per btu
    pct: bool = False

    def any(self) -> bool:
        return self.currency or bool(self.scale or self.noun or self.per) or self.pct

    def words(self) -> str:
        parts = (["dollars"] if self.currency else []) + ([self.scale] if self.scale else []) + ([self.noun] if self.noun else [])
        return " ".join(parts + ([f"per {self.per}"] if self.per else []) + (["percent"] if self.pct else []))


_SCALES = {"thousand", "million", "billion", "trillion"}
_CURRENCY = {"dollars", "dollar", "cents", "cent", "euros", "euro", "eur"}
_NOUNS = {"barrel", "gallon", "tonne", "contract", "rig", "btu", "cubic"}
_PER_NOUNS = {"barrel", "gallon", "tonne", "day", "btu", "mwh", "therm"}


def _unit_words(text: str) -> list[str]:
    """The words of a unit, normalised as unit_key normalises a unit: barrels -> barrel, USD -> dollars, mb -> million
    barrel, "/" -> per."""
    out = []
    for w in re.findall(r"[a-z]+|/|%", text.lower()):
        out += (_UNIT_WORDS.get(w, w)).split() if w != "/" else ["per"]
    return out


# Units written glued to a number: 95.7mb/d, 417,797bbl, 5,576kb/d, 1.2bn, 30k (the adversary, round 5)
_SUFFIX = {"mb": "million barrel", "kb": "thousand barrel", "b": "barrel", "bbl": "barrel", "bbls": "barrel",
           "bpd": "barrel per day", "kbd": "thousand barrel per day", "mbd": "million barrel per day",
           "kt": "thousand tonne", "t": "tonne", "mt": "tonne", "bcf": "billion cubic", "tcf": "trillion cubic",
           "mmbtu": "million btu", "k": "thousand", "m": "million", "mn": "million", "mln": "million",
           "bn": "billion", "pct": "percent"}


_CURRENCY_PREFIX = {"USD", "EUR", "GBP"}


def glued_suffix(tok: str, whole: str) -> str:
    """The letters glued AFTER a number ("mb" of 95.7mb), "" when there are none (M1, USD97.72: letters before)."""
    i = whole.find(tok)
    return whole[i + len(tok):] if i >= 0 else ""


def written_unit(clean: str, start: int, end: int, whole: str, suffix: str = "") -> Written:
    """What unit, if any, the prose writes on the number at clean[start:end]: letters glued after it (`suffix`),
    then the words right after it up to the next comma, bracket or full stop, and a currency sign or USD before it."""
    w = Written(currency=clean[max(0, start - 1):start] == "$" or whole[:3].upper() in _CURRENCY_PREFIX)
    after = clean[end + len(suffix):end + len(suffix) + 48]
    tail = re.split(r"[,;:()\[\]]|\.(?:\s|$)", after)[0]
    head = _SUFFIX.get(suffix.lower(), suffix.lower()).split() if suffix else []
    words, i = [_UNIT_WORDS.get(x, x) for x in head] + _unit_words(tail), 0
    if words[:1] == ["%"] or words[:1] == ["percent"] or words[:2] == ["per", "cent"] or words[:2] == ["percentage", "points"]:
        w.pct = True
        return w
    while i < len(words) and words[i] in _SCALES:
        w.scale, i = words[i], i + 1
    if i < len(words) and words[i] in _CURRENCY:
        w.currency, i = True, i + 1
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
    if w.currency and not set(head.split()) & (_CURRENCY | {"dollars"}):
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
        if not glued and tok in pool.names and not unit.any():
            continue  # a number of a name, written without a unit of its own
        if not glued and tok in pool.hyphens and re.match(r"-[A-Za-z0-9]", clean[end:end + 2]):
            continue  # the 12 of "12-month", written hyphenated as the text writes it
        n, dp = _parse(tok)
        after = clean[end:end + 40]
        money = bool(_MONEY.match(after)) or clean[max(0, start - 1):start] == "$" or whole[:3].lower() == "usd"
        pct, count = bool(_PCT.match(after)), bool(_COUNT.match(after))
        kinds = ({"amount"} if money else {"amount", "percent"} if pct else {"count"} if count else {"amount", "percent", "count"})
        matches = [u for v, kind, u in pool.tagged if (kind in kinds or kind == "any") and _rounds_to(v, n, dp)]
        if not matches:
            bad.append(whole if glued else tok)
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
_HIGH = {"high", "highest", "top", "upper", "elevated", "stretched", "rich"}
_LOW = {"low", "lowest", "bottom", "lower", "depressed", "cheap"}
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
    for s in answer.spreads:
        a, b = _words(s.name_a), _words(s.name_b)
        if s.spread:
            levels.append((s.spread, a - b, b - a))
    for r in answer.readings:
        for k, v in r.values.items():
            if not v:
                continue
            if "change" in k:
                (quiet if k.startswith("metric.") else moves).append(v)
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
            if ranks and all(v >= 75 for v in ranks) and sentence_words & _LOW and not sentence_words & _HIGH:
                problems.append(f"percentile {tok} is called low; it is high")
            if ranks and all(v <= 25 for v in ranks) and sentence_words & _HIGH and not sentence_words & _LOW:
                problems.append(f"percentile {tok} is called high; it is low")
    return list(dict.fromkeys(problems))
