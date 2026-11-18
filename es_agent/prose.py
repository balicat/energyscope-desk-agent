"""What is left of the prose checks after slots.

Until 18 Nov 2026 this file held the rules that read the model's sentences: every number traced to a
tool result, direction words compared with signs, dates, units. An adversarial review showed the rules
did not converge (each round of unseen wrong sentences found new gaps, and right sentences began to be
refused), so the sentences are now built the other way round: the model places slots and code writes
every figure (slots.py). Two things remain here.
"""

from __future__ import annotations

import re

_UNIT_WORDS = {"usd": "dollars", "$": "dollars", "us$": "dollars", "/": " per ", "bbl": "barrel", "barrels": "barrel",
               "gal": "gallon", "gallons": "gallon", "mt": "tonne", "tonnes": "tonne", "ton": "tonne", "mmbtu": "million btu"}


def unit_key(units: str) -> str:
    """Publishers label the same unit differently ('USD/bbl', 'Dollars per Barrel'); compare on this."""
    text = units.lower().replace("/", " per ")
    return " ".join(_UNIT_WORDS.get(w, w) for w in text.split())


def echoes(text: str, asked: str, words: int) -> bool:
    """Does `text` repeat `words` or more consecutive words of what the visitor wrote? A visitor who
    asks for a sentence "exactly" must not see it come back as The Librarian's own, under the tick."""
    mine = re.findall(r"[a-z0-9']+", text.lower())
    theirs = " " + " ".join(re.findall(r"[a-z0-9']+", asked.lower())) + " "
    return any(" " + " ".join(mine[i:i + words]) + " " in theirs for i in range(len(mine) - words + 1))


ECHO_SUMMARY = 12  # a summary may restate the question's terms, not hand a sentence of it back
