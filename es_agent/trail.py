"""What the trail and the progress events may carry: values a tool validated, never text the model (or a visitor,
through the model) wrote into a tool's arguments.

The trail (the API's `trail`, the question log) and the page's progress steps (`tool` events) used to repeat each
call's arguments as the model wrote them. A sentence put into a search, a series id or any free-text argument then
appeared on the page and in the API beside checked numbers (the adversary's independent review, 24 Nov 2026,
58d8ec0a item 2). Now each call is recorded by the tool itself, after its own validation, through `clean`:

  - series ids (series_id, series_ids, series_a, series_b): only ids the data source knows;
  - a search's query: only the words the search itself matched (a word kept only if it occurs in a returned
    series' id or name), at most 8 words and 60 characters; nothing when the search found nothing;
  - a string argument typed as a fixed choice (Literal): only a value of that choice; `dataset` only a known one;
  - numbers and booleans as passed (pydantic checked their type; a number cannot carry a sentence);
  - anything else (free text no tool checks) is left out.

A call that failed (its arguments refused, the tool refused, or a tool the agent does not have) is recorded by its
tool name only, and an unknown tool's name is not repeated at all.
"""

from __future__ import annotations

import inspect
import math
import re
import typing
from typing import Literal, get_args, get_origin

SERIES_KEYS = ("series_id", "series_ids", "series_a", "series_b")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:\-]{0,79}")
WORD = re.compile(r"[^\W_]+")
MAX_QUERY_WORDS, MAX_QUERY_CHARS = 8, 60


def _choices(fn) -> dict[str, tuple]:
    """The fixed choices (Literal values) of a tool function's string arguments."""
    if fn is None:
        return {}
    try:
        hints = typing.get_type_hints(fn)
    except Exception:
        return {}
    out = {}
    for name, t in hints.items():
        for a in (t, *get_args(t)):          # Literal[...] or Literal[...] | None
            if get_origin(a) is Literal:
                out[name] = get_args(a)
    return out


def known_id(source, sid) -> bool:
    if not isinstance(sid, str) or not ID.fullmatch(sid):
        return False
    try:
        return source.meta(sid) is not None
    except Exception:
        return False


def query_words(query, hits) -> str | None:
    """The words of a search that the search itself matched, in the order written."""
    if not isinstance(query, str) or not hits:
        return None
    seen = set()
    for h in hits:
        seen.update(WORD.findall(f"{getattr(h, 'series_id', '')} {getattr(h, 'name', '')}".casefold()))
    kept: list[str] = []
    for w in WORD.findall(query.casefold()):
        if w in seen and w not in kept:
            kept.append(w)
    q = " ".join(kept[:MAX_QUERY_WORDS])[:MAX_QUERY_CHARS].strip()
    return q or None


def clean(fn, args: dict | None, source, hits=None, datasets=()) -> dict:
    """The arguments of one call as the trail and the page may show them (see the module docstring)."""
    choices = _choices(fn)
    params = set(inspect.signature(fn).parameters) if fn is not None else set()
    out: dict = {}
    for k, v in (args or {}).items():
        if params and k not in params:
            continue
        if k in SERIES_KEYS:
            if isinstance(v, (list, tuple)):
                ids = [s for s in v if known_id(source, s)]
                if ids:
                    out[k] = ids
            elif known_id(source, v):
                out[k] = v
        elif k == "query":
            q = query_words(v, hits)
            if q:
                out[k] = q
        elif k == "dataset":
            if isinstance(v, str) and v.upper() in {d.upper() for d in datasets}:
                out[k] = v.upper()
        elif isinstance(v, bool):
            out[k] = v
        elif isinstance(v, (int, float)) and math.isfinite(v):
            out[k] = v
        elif k in choices and v in choices[k]:
            out[k] = v
    return out


def build(parts, calls: dict, tools) -> list[dict]:
    """The trail of one run from its message parts: each tool call in order, with the arguments its tool recorded
    after validation (`calls`, by tool_call_id). A call that was sent back or never recorded keeps its tool name
    only; a tool the agent does not have is named "unknown tool". Pydantic AI 2.x returns a refused call as a
    ToolReturnPart with outcome "retried" (and a RetryInfo); older versions as a RetryPromptPart: both are read."""
    from pydantic_ai.messages import RetryPromptPart, ToolCallPart

    def refused(p) -> bool:
        if not getattr(p, "tool_call_id", None):
            return False
        if isinstance(p, RetryPromptPart):
            return True
        return getattr(p, "part_kind", "") == "tool-return" and (
            getattr(p, "outcome", "success") not in (None, "success") or getattr(p, "retry", None) is not None)

    retried = {p.tool_call_id for p in parts if refused(p)}
    trail = []
    for p in parts:
        if not isinstance(p, ToolCallPart) or p.tool_name == "final_result":
            continue
        if p.tool_name not in tools:
            trail.append({"tool": "unknown tool", "args": {}})
            continue
        c = calls.get(p.tool_call_id)
        if c is None or p.tool_call_id in retried:
            trail.append({"tool": p.tool_name, "args": {}})
        else:
            trail.append({"tool": p.tool_name, "args": c["args"]})
    return trail
