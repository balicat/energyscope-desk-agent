"""What the prose may say: the checks on the sentences, as opposed to the tables.

The validator (before an answer is accepted), `verify()` (before the page shows its tick) and
the evaluators all call these, so one rule decides in all three places.

Checked, in the summary and in every caveat the model wrote:
- every run of digits is a valid rounding of a value a tool returned, of the right kind. A number
  followed by a money word must be an amount, not a percentage or a count; a number followed by
  "days" or "years" must be a count; a scale word or "per tonne" after a number must appear in the
  units of something the answer cites. A number glued to letters ("USD97.72") is still a number;
  only a whole token that a tool returned as a name ("M12") is excused;
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
nouns, and claims made in words alone ("a record high", "has narrowed" where no earlier value was
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
                "Average-price contract: ")

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
_NUMWORD = (r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
            r"seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion)")
_SPELLED = re.compile(rf"\b{_NUMWORD}(?:[\s-]+(?:and\s+)?{_NUMWORD})*\s+(?:us\s+)?"
                      r"(?:usd|dollars?|cents?|percent|per\s+cent|barrels?|bbl|contracts?|tonnes?|gallons?)\b", re.I)

_UNIT_WORDS = {"usd": "dollars", "$": "dollars", "us$": "dollars", "/": " per ", "bbl": "barrel", "barrels": "barrel",
               "gal": "gallon", "gallons": "gallon", "mt": "tonne", "tonnes": "tonne", "ton": "tonne", "mmbtu": "million btu"}


def unit_key(units: str) -> str:
    """Publishers label the same unit differently ('USD/bbl', 'Dollars per Barrel'); compare on this."""
    text = units.lower().replace("/", " per ")
    return " ".join(_UNIT_WORDS.get(w, w) for w in text.split())


def _kind(key: str) -> str:
    parts = key.lower().split("_")
    if key in ("lines", "tight", "loose", "neutral") or "observations" in parts or any(p in ("days", "weeks", "years") for p in parts):
        return "count"
    if "percentile" in parts or key.endswith("_pct") or "percentile" in key:
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
    units: str = ""                                 # units and labels of everything cited, normalised

    def add(self, key: str, value: float) -> None:
        kind = _kind(key)
        {"count": self.counts, "percent": self.percents, "amount": self.amounts}[kind].append(value)
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

    def label(self, *parts: str) -> None:
        self.units += " " + unit_key(" ".join(parts).replace("_", " "))


def pool_of(answer: DeskAnswer) -> Pool:
    p = Pool()
    for f in answer.facts:
        p.amounts += [x for x in (f.latest_value, f.base_value, f.change_abs) if x is not None]
        if f.change_pct is not None:
            p.percents.append(f.change_pct)
        if f.lookback_days is not None:
            p.counts.append(f.lookback_days)
        p.dates |= {d for d in (f.latest_period, f.base_period) if d is not None}
        p.text(f.name, f.series_id)
        p.label(f.units, f.name)
    for s in answer.spreads:
        p.amounts += [s.value_a, s.value_b, s.spread]
        for k, v in s.extras.items():
            p.add(k, v)
        p.dates.add(s.period)
        p.text(s.name_a, s.series_a, s.name_b, s.series_b, s.context, s.note)
        p.label(s.units, s.name_a, s.name_b)
    for r in answer.readings:
        for k, v in r.values.items():
            p.add(k, v)
        p.dates.add(r.period)
        p.text(r.title, r.note, r.context, r.counter, r.key, " ".join(r.series_ids), " ".join(r.values))
        p.label(r.units, r.title, r.note, r.context, " ".join(r.values))
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


def text_problems(text: str, pool: Pool) -> list[str]:
    """Numbers and dates in one piece of prose that trace to nothing a tool returned."""
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
        if not glued and tok in pool.names:
            continue
        n, dp = _parse(tok)
        after = clean[end:end + 40]
        money = bool(_MONEY.match(after)) or clean[max(0, start - 1):start] == "$" or whole[:3].lower() == "usd"
        pct, count = bool(_PCT.match(after)), bool(_COUNT.match(after))

        def hit(values: list[float]) -> bool:
            return any(_rounds_to(v, n, dp) for v in values)

        ok = (hit(pool.amounts) if money else
              hit(pool.amounts) or hit(pool.percents) if pct else
              hit(pool.counts) if count else
              hit(pool.amounts) or hit(pool.percents) or hit(pool.counts))
        if not ok:
            bad.append(whole if glued else tok)
            continue
        scale, per = _SCALE.match(after), _PER.match(after)
        if scale and scale.group(1).lower() not in pool.units:
            bad.append(f"{tok} {scale.group(1)} (no cited series is in that unit)")
        elif per and unit_key(per.group(1)) not in pool.units:
            bad.append(f"{tok} per {per.group(1)} (no cited series is in that unit)")
    return bad


def model_caveats(answer: DeskAnswer) -> list[str]:
    return [c for c in answer.caveats if not c.startswith(CODE_CAVEATS)]


def untraceable(answer: DeskAnswer) -> list[str]:
    """Numbers and dates in the summary and in the model's caveats that trace to nothing."""
    pool = pool_of(answer)
    return [b for text in [answer.summary, *model_caveats(answer)] for b in text_problems(text, pool)]


def clean_caveats(answer: DeskAnswer) -> list[str]:
    """The model's caveats, minus any that states a number or date no tool returned. A caveat is
    where a number goes when the summary may not hold it, so code removes it there too."""
    pool = pool_of(answer)
    return [c for c in model_caveats(answer) if not text_problems(c, pool)]


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


def _signed(answer: DeskAnswer) -> tuple[list[float], list[tuple[float, set[str], set[str]]]]:
    """(changes, levels). A level is (value, words for the first thing, words for the second):
    positive means the first is above the second."""
    moves: list[float] = []
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
                moves.append(v)
            elif "_minus_" in k:
                a, b = (_words(part.replace("_", " ")) for part in k.split("_minus_", 1))
                levels.append((v, a - b, b - a))
            elif k in ("difference", "difference_pct") or k.endswith("_vs_5y_pct"):
                levels.append((v, set(), _AVERAGE))
    return moves, levels


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


def direction_problems(answer: DeskAnswer) -> list[str]:
    """Direction words that contradict the data, and quoted changes with no direction at all."""
    lowered = [w.lower() for w in re.findall(r"[A-Za-z]+", answer.summary)]
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
    moves, levels = _signed(answer)
    pool = pool_of(answer)
    clean = _blank_dates(answer.summary)
    for sentence in re.split(r"(?<=[.!?;:])\s+", clean):
        found = list(_TOKEN.finditer(sentence))
        toks = [("num", m.group().rstrip(",")) if m.lastgroup == "num" else ("word", m.group().lower()) for m in found]
        commas = [m.start() for m in re.finditer(r",(?!\d)", sentence)]
        sentence_words = {w for k, w in toks if k == "word"}
        for i, (kind, tok) in enumerate(toks):
            if kind != "num":
                continue
            n, dp = _parse(tok)
            move_signs = {v > 0 for v in moves if _quotes(v, n, dp)}
            if len(move_signs) == 1:
                rose = move_signs.pop()
                lead = sentence[:found[i].start()].rstrip()
                sign = lead[-1:] if lead[-1:] in "+-−" and not lead[-2:-1].isalnum() else ""
                before = [w for k, w in reversed(toks[max(0, i - 8):i]) if k == "word"]
                said = (sign == "+") if sign else next((w in _CHANGE_UP for w in before if w in _CHANGE_UP | _CHANGE_DOWN), None)
                if said is None:
                    after = [w for k, w in toks[i + 1:i + 4] if k == "word"]
                    said = next((w in _CHANGE_UP for w in after if w in ("higher", "lower", "up", "down")), None)
                if said is None:
                    problems.append(f"'{tok}' is a change: write rose or fell (or up, down, a sign) right beside it")
                elif said != rose:
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
            if ranks and all(v >= 75 for v in ranks) and sentence_words & _LOW and not sentence_words & _HIGH:
                problems.append(f"percentile {tok} is called low; it is high")
            if ranks and all(v <= 25 for v in ranks) and sentence_words & _HIGH and not sentence_words & _LOW:
                problems.append(f"percentile {tok} is called high; it is low")
    return list(dict.fromkeys(problems))
