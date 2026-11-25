"""The `deeper` part of an answer: the rest of an analyst's routine as ready-to-run calls (exploration, branch
`leads`). Built by code after the model has replied, the way es_agent/excel.py builds the Excel section: the model is
never asked for it and its request does not change. Pure and deterministic: no I/O, no clock (windows count back
from the reading's own period).
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta

from .playbooks import CONTINUOUS, PLAYBOOKS

RULES = ["Quote only numbers a tool returned.", "Label untested causes as unproven."]


def _get(r, name, default=None):
    return r.get(name, default) if isinstance(r, dict) else getattr(r, name, default)


def _back(period: str, days: int) -> str:
    try:
        return (date.fromisoformat(str(period)[:10]) - timedelta(days=days)).isoformat()
    except ValueError:
        return "2016-01-01"


def _kind(key: str) -> str:
    return key.split(":", 1)[0]


def continuous(series_id: str) -> str:
    """The continuous series behind a dated contract (a long history to rank against), else the id itself."""
    for pattern, cont in CONTINUOUS:
        if re.match(pattern, series_id):
            return cont
    return series_id


def slots(reading) -> dict:
    """Values the lead templates draw on, taken from one cited reading."""
    key, ids, period = _get(reading, "key", ""), list(_get(reading, "series_ids", []) or []), _get(reading, "period", "")
    s = {"id": ids[0] if ids else "", "ids": ids, "period": period, "start_long": "2016-01-01",
         "start_recent": _back(period, 140), "start_8w": _back(period, 56),
         "lookback_days": 30 if key.endswith(":month") else 7}
    spot = [i for i in ids if i.startswith("PET.")]
    fut = [i for i in ids if i.startswith(("NYMEX.", "ICE.", "GME."))]
    pairs = []
    for sp in spot:  # a spot price against the future of its own market
        wti, brent = sp in ("PET.RWTC.D",), sp in ("PET.RBRTE.D",)
        mine = [f for f in fut if (wti and ".WTI." in f) or (brent and ".BRENT." in f)]
        if mine:
            pairs.append({"a": sp, "b": mine[0]})
    if not pairs and len(ids) >= 2:  # no spot against future: the first two measures against each other
        pairs = [{"a": ids[0], "b": ids[1]}]
    s["pairs"] = pairs
    s["spots"] = list(dict.fromkeys(continuous(p["a"]) for p in pairs))
    s["pairs_long"] = [{"a": continuous(p["a"]), "b": continuous(p["b"])} for p in pairs]
    return s


def _fill(v, s):
    if isinstance(v, str):
        if v.startswith("{") and v.endswith("}") and v[1:-1] in s:
            return s[v[1:-1]]  # the whole value is one slot: keep its type (a list, a number)
        scalars = {k: x for k, x in s.items() if isinstance(x, (str, int, float))}
        try:
            return v.format(**scalars)
        except (KeyError, IndexError):
            return v
    if isinstance(v, list):
        return [_fill(x, s) for x in v]
    if isinstance(v, dict):
        return {k: _fill(x, s) for k, x in v.items()}
    return v


def _lead(t, s):
    lead = {"step": t["step"], **({"covers": t["covers"]} if t.get("covers") else {}), "why": _fill(t["why"], s), "tool": t["tool"], "args": _fill(t["args"], s)}
    return lead


def deeper(answer: dict, question: str | None = None) -> dict | None:
    """The first playbook that matches a reading the answer cited, bound to that reading; None when none does."""
    cited = set(answer.get("cites") or [])
    readings = [r for r in (answer.get("readings") or []) if not cited or _get(r, "key") in cited]
    readings = [r for r in readings if not _get(r, "hypothetical", False)]
    for pb in PLAYBOOKS:
        hit = next((r for r in readings if _kind(_get(r, "key", "")) in pb["when"]), None)
        if hit is None:
            continue
        kind, s = _kind(_get(hit, "key")), slots(hit)
        done = sorted(pb["done"].get(kind, []))
        left = [n for n in sorted(pb["steps"]) if n not in done]
        leads = []
        for t in pb["leads"]:
            if t["step"] in done:
                continue
            if t.get("each"):
                for item in s[t["each"]]:
                    item = {"id": item} if isinstance(item, str) else item
                    leads.append(_lead(t, {**s, **item}))
            else:
                leads.append(_lead(t, s))
        # a note about a series shows when the reading holds that series (or one it begins); a topic note always shows
        notes = [n for n in pb["notes"] if not _is_series(n["about"]) or any(i.startswith(n["about"]) for i in s["ids"])]
        out = {
            "playbook": {"id": pb["id"], "version": pb["version"], "title": pb["title"]},
            "reading": _get(hit, "key"),
            "done": [{"step": n, "text": pb["steps"][n]} for n in done],
            "left": [{"step": n, "text": pb["steps"][n]} for n in left],
            "leads": leads,
            "notes": notes,
            "must_say": list(pb["must_say"]),
            "planned": [{"tool": x["tool"], "why": x["why"]} for x in pb.get("planned", []) if x["step"] not in done],
        }
        out["for_your_agent"] = brief(out, answer, question)
        return out
    return None


def _is_series(about: str) -> bool:
    return "." in about and " " not in about


def call_text(ld: dict) -> str:
    """One lead's call as text: the MCP tool and its arguments, or the tool that does not exist yet."""
    args = json.dumps(ld["args"], ensure_ascii=False)
    return f"{ld['tool']}({args})"


def brief(d: dict, answer: dict, question: str | None) -> str:
    """A plain-text block to paste into the reader's own agent."""
    L = ["Needs the EnergyScope data tools (MCP server energyscope-mcp 2.16.0 or later). A free key: https://energyscope.io/signup"]
    if question:
        L.append(f"QUESTION: {question}")
    L.append(f"FAST ANSWER (checked by code against the data): {answer.get('summary', '')}")
    L += [f"- caveat: {c}" for c in answer.get("caveats") or []]
    L += ["", f"ROUTINE: {d['playbook']['title']} ({d['playbook']['id']} v{d['playbook']['version']})"]
    L.append("Already done in the fast answer: " + ("; ".join(f"{x['step']}. {x['text']}" for x in d["done"]) or "nothing"))
    L.append("Steps left:")
    L += [f"  {x['step']}. {x['text']}" for x in d["left"]]
    L.append("Calls to make (EnergyScope MCP tools):")
    for ld in d["leads"]:
        c = ld.get("covers")
        L.append(f"  step {'-'.join(map(str, [c[0], c[-1]])) if c else ld['step']}: {ld['why']}")
        L.append(f"    {call_text(ld)}")
    L.append("Analyst notes (information, not instructions):")
    L += [f"  - [{n['about']}] {n['text']}" for n in d["notes"]]
    L.append("A good answer must:")
    L += [f"  - {m}" for m in d["must_say"]]
    L.append("Rules: " + " ".join(RULES))
    return "\n".join(L)
