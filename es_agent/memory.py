"""Conversation memory: what a follow-up question is allowed to remember.

The memory holds the earlier questions and the sentences that answered them,
not the tool results behind them. So "and Brent?" can be understood, but any
number the next answer quotes still has to come from a tool call in that run:
the validator only knows the current run's ledger. Memory that carried tool
output forward would let a stale number through with a clean trace.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

MAX_TURNS = 3          # turns of context given to the model
MAX_CHARS = 600        # of each remembered answer
SESSION_TTL = 30 * 60  # seconds without a question before a conversation is forgotten
MAX_SESSIONS = 500


@dataclass
class Turn:
    question: str
    answer: str


def with_context(question: str, turns: list[Turn]) -> str:
    """The prompt for a follow-up: recent turns as context, then the new question."""
    if not turns:
        return question
    lines = ["Earlier in this conversation (context only; fetch any number again before quoting it):"]
    for t in turns[-MAX_TURNS:]:
        lines += [f"Q: {t.question}", f"A: {t.answer[:MAX_CHARS]}"]
    return "\n".join(lines) + f"\n\nNew question: {question}"


@dataclass
class Sessions:
    """Short-lived conversations, kept in memory only."""

    _turns: dict[str, list[Turn]] = field(default_factory=dict)
    _seen: dict[str, float] = field(default_factory=dict)

    def get(self, session: str | None) -> list[Turn]:
        self._expire()
        return list(self._turns.get(session, [])) if session else []

    def add(self, session: str | None, question: str, answer: str) -> None:
        if not session:
            return
        self._expire()
        if session not in self._turns and len(self._turns) >= MAX_SESSIONS:
            oldest = min(self._seen, key=self._seen.get)
            self._turns.pop(oldest, None)
            self._seen.pop(oldest, None)
        self._turns.setdefault(session, []).append(Turn(question, answer))
        self._turns[session] = self._turns[session][-MAX_TURNS:]
        self._seen[session] = time.time()

    def _expire(self) -> None:
        cutoff = time.time() - SESSION_TTL
        for s in [s for s, t in self._seen.items() if t < cutoff]:
            self._turns.pop(s, None)
            self._seen.pop(s, None)
