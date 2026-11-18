"""What the prose may say: the checks on the sentences, as opposed to the tables.

The validator (before an answer is accepted), `verify()` (before the page shows its tick) and
the evaluators all call these, so one rule decides in all three places.

Checked, in the summary and in every caveat the model wrote:
- every number is a valid rounding of a value a tool returned, of the right kind: a number followed
  by a money word must be an amount, not a percentage or a count; a number followed by "days" or
  "years" must be a count; a number written with a thousands separator is never read as a year;
- every date is one a tool returned (or today), written as YYYY-MM-DD; month names, weekday names
  and quarters are rejected, because a date written in words cannot be traced;
- a direction word beside a number agrees with the sign of that number: "fell 1.20" needs a fall,
  "0.62 above WTI" needs Brent above WTI.

Not checked, and stated as limits in the README: two true values attached to the wrong nouns, and
claims made in words alone ("a record high"). A short number such as "2" matches any returned value
between 1.5 and 2.5, so the chance of an accidental match grows with the number of values cited.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from . import clock
from .models import DeskAnswer

# Caveats written by code start with one of these. The validator removes any the model wrote with
# the same opening and appends its own, so the prefix marks text that needs no tracing.
CODE_CAVEATS = ("Not current as of ", "Against the balance of the evidence: ", "Not like for like: ",
                "Average-price contract: ")

_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_NUM = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?")
_TOKEN = re.compile(r"(?P<num>(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?)|(?P<word>[A-Za-z][A-Za-z0-9]*)")
_LOOSE_DATE = re.compile(
    r"\b(?:january|february|march|april|june|july|august|september|october|november|december|"
    r"jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|q[1-4])\b|\bmay \d|\d(?:st|nd|rd|th)? may\b", re.I)
_MONEY = re.compile(r"\s*(?:usd|us\$|\$|dollars?|cents?)", re.I)
_PCT = re.compile(r"\s*(?:%|percent|per cent)", re.I)
_COUNT = re.compile(r"[\s-]*(?:days?|weeks?|years?|months?|lines?|observations?|reports?)\b", re.I)

_COUNT_KEYS = {"years", "lines", "tight", "loose", "neutral", "observations", "spread_observations",
               "percentile_weeks", "percentile_years"}


def _kind(key: str) -> str:
    if key in _COUNT_KEYS or key.endswith(("_days", "_years", "_weeks")) or key.startswith("days_"):
        return "count"
    if "percentile" in key or key.endswith("_pct"):
        return "percent"
    return "amount"


@dataclass
class Pool:
    """Everything the tools returned that the prose may quote."""

    amounts: list[float] = field(default_factory=list)
    percents: list[float] = field(default_factory=list)
    counts: list[float] = field(default_factory=list)
    dates: set[dt.date] = field(default_factory=set)
    names: set[str] = field(default_factory=set)  # numbers that are part of a name or of code-written text

    def add(self, key: str, value: float) -> None:
        {"count": self.counts, "percent": self.percents, "amount": self.amounts}[_kind(key)].append(value)

    def text(self, *parts: str) -> None:
        joined = " ".join(parts)
        self.names |= set(_NUM.findall(joined))
        for d in _ISO.findall(joined):
            try:
                self.dates.add(dt.date.fromisoformat(d))
            except ValueError:
                pass


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
    for s in answer.spreads:
        p.amounts += [s.value_a, s.value_b, s.spread]
        for k, v in s.extras.items():
            p.add(k, v)
        p.dates.add(s.period)
        p.text(s.name_a, s.series_a, s.name_b, s.series_b, s.context, s.note)
    for r in answer.readings:
        for k, v in r.values.items():
            p.add(k, v)
        p.dates.add(r.period)
        p.text(r.title, r.note, r.context, r.counter, r.key, " ".join(r.series_ids), " ".join(r.values))
    return p


def _rounds_to(value: float, written: float, decimals: int) -> bool:
    """Is `written` a valid rounding of `value` to the decimals it was written with? Signs are not
    compared here: "down 5.37" is a fall of 5.37, and the direction rule reads the word."""
    return abs(abs(value) - abs(written)) <= 0.5 * 10 ** -decimals + 1e-9


def _parse(tok: str) -> tuple[float, int]:
    raw = tok.replace(",", "")
    return float(raw), (len(raw.split(".")[1]) if "." in raw else 0)


def text_problems(text: str, pool: Pool) -> list[str]:
    """Numbers and dates in one piece of prose that trace to nothing a tool returned."""
    bad = []
    today = clock.today()
    for d in _ISO.findall(text):
        try:
            ok = dt.date.fromisoformat(d) in pool.dates or dt.date.fromisoformat(d) == today
        except ValueError:
            ok = False
        if not ok:
            bad.append(d)
    bad += [f"{m.group().strip()} (write dates as YYYY-MM-DD)" for m in _LOOSE_DATE.finditer(text)]
    clean = _ISO.sub(lambda m: " " * len(m.group()), text)
    years = {d.year for d in pool.dates} | {today.year}
    for m in _NUM.finditer(clean):
        tok = m.group()
        if tok in pool.names:
            continue
        n, dp = _parse(tok)
        after = clean[m.end():m.end() + 16]
        money = bool(_MONEY.match(after)) or clean[max(0, m.start() - 1):m.start()] == "$"
        pct, count = bool(_PCT.match(after)), bool(_COUNT.match(after))
        if dp == 0 and "," not in tok and 1900 <= n <= 2100 and not (money or pct or count) and int(n) in years:
            continue  # the year of a date a tool returned

        def hit(values: list[float]) -> bool:
            return any(_rounds_to(v, n, dp) for v in values)

        ok = (hit(pool.amounts) if money else
              hit(pool.amounts) or hit(pool.percents) if pct else
              hit(pool.counts) if count else
              hit(pool.amounts) or hit(pool.percents) or hit(pool.counts))
        if not ok:
            bad.append(tok)
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
              "build", "built", "grew", "added", "raised", "lengthened", "bought"}
_CHANGE_DOWN = {"down", "fell", "fallen", "fall", "falling", "decrease", "decreased", "decline", "declined", "dropped",
                "drop", "draw", "drew", "shrank", "lost", "cut", "reduced", "trimmed", "slipped", "shed", "sold"}
_AFTER_UP, _AFTER_DOWN = {"higher", "up"}, {"lower", "down"}
_LEVEL_UP, _LEVEL_DOWN = {"above", "over"}, {"below", "under", "beneath"}
_AVERAGE = {"average", "norm", "usual", "mean"}
_SMALL = {"a", "an", "the", "its", "on", "of", "per", "date"}


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


def direction_problems(answer: DeskAnswer) -> list[str]:
    """Direction words that contradict the data.

    Beside a number: the nearest change word before a change ("fell 1.20") must match its sign, and
    a level word after a gap ("0.62 above WTI") must match which side is higher. The word is read in
    the same sentence as the number and next to it, so a right word elsewhere is no excuse.
    Without a number: a curve called contango when every cited curve is in backwardation, and a
    change described only with falling words when every change in the facts is a rise.
    """
    problems = []
    text = answer.summary.lower()
    shapes = {r.note.split(" ")[0] for r in answer.readings if r.key.startswith("curve:")} & {"backwardation", "contango"}
    if len(shapes) == 1:
        right = shapes.pop()
        wrong = "contango" if right == "backwardation" else "backwardation"
        if wrong[:9] in text and right[:9] not in text:
            problems.append(f"the summary says {wrong}; the curve is in {right}")
    signs = {c > 0 for f in answer.facts if (c := f.change_abs) is not None and c != 0}
    all_words = set(re.findall(r"[a-z]+", text))
    if len(signs) == 1:
        rose = signs.pop()
        right_set, wrong_set = (_CHANGE_UP, _CHANGE_DOWN) if rose else (_CHANGE_DOWN, _CHANGE_UP)
        if all_words & wrong_set and not all_words & right_set:
            problems.append(f"the summary uses {sorted(all_words & wrong_set)} but every change in the facts is "
                            f"{'a rise' if rose else 'a fall'}; say so in plain words")
    moves, levels = _signed(answer)
    clean = _ISO.sub(lambda m: " " * len(m.group()), answer.summary)
    for sentence in re.split(r"(?<=[.!?;:])\s+", clean):
        found = list(_TOKEN.finditer(sentence))
        toks = [("num", m.group()) if m.lastgroup == "num" else ("word", m.group().lower()) for m in found]
        commas = [m.start() for m in re.finditer(r",(?!\d)", sentence)]
        for i, (kind, tok) in enumerate(toks):
            if kind != "num":
                continue
            n, dp = _parse(tok)
            move_signs = {v > 0 for v in moves if _rounds_to(v, n, dp)}
            if len(move_signs) == 1:
                rose = move_signs.pop()
                before = [w for k, w in reversed(toks[max(0, i - 8):i]) if k == "word"]
                said = next((w in _CHANGE_UP for w in before if w in _CHANGE_UP | _CHANGE_DOWN), None)
                if said is None:
                    after = [w for k, w in toks[i + 1:i + 4] if k == "word"]
                    said = next((w in _AFTER_UP for w in after if w in _AFTER_UP | _AFTER_DOWN), None)
                if said is not None and said != rose:
                    problems.append(f"'{tok}' is described as a {'rise' if said else 'fall'}; the data shows a "
                                    f"{'rise' if rose else 'fall'}")
            hits = [(v, a, b) for v, a, b in levels if _rounds_to(v, n, dp)]
            if len(hits) == 1:
                v, a, b = hits[0]
                # A level word and the thing it points at are read only up to the next comma: past it,
                # the words belong to another clause.
                stop = next((c for c in commas if c > found[i].end()), len(sentence))
                rest = [w for (k, w), m in zip(toks[i + 1:], found[i + 1:]) if k == "word" and m.start() < stop]
                at = next((j for j, w in enumerate(rest[:4]) if w in _LEVEL_UP | _LEVEL_DOWN), None)
                if at is None:
                    continue
                target = next((w for w in rest[at + 1:at + 7] if w in a | b), None)
                if target is None:
                    continue
                expect_above = (v > 0) if target in b else (v < 0)
                if (rest[at] in _LEVEL_UP) != expect_above:
                    problems.append(f"'{tok} {rest[at]} ...' points the wrong way; the data has it "
                                    f"{'above' if expect_above else 'below'}")
    return list(dict.fromkeys(problems))
