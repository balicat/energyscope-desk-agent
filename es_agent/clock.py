"""One place that says what day it is, so the frozen test data can pin it."""

from __future__ import annotations

import datetime as dt
import os


def today() -> dt.date:
    """LIBRARIAN_TODAY=YYYY-MM-DD pins the date (used with the fixture data in CI)."""
    pinned = os.environ.get("LIBRARIAN_TODAY")
    return dt.date.fromisoformat(pinned) if pinned else dt.date.today()
