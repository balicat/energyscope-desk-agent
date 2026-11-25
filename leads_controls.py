"""Leads control (exploration, branch `leads`): the `deeper` part of an answer (es_agent/leads.py, playbooks.py).
Free: no model, no data.

    python leads_controls.py

Each playbook: an answer citing a triggering reading yields leads whose tools exist on the EnergyScope MCP server
(or say plainly they do not) and whose arguments name series of that reading; an answer citing nothing yields None;
`for_your_agent` holds every lead's call. The Brent-WTI case is the real answer saved on 25 Nov 2026.
"""

from __future__ import annotations

import json
import sys

from es_agent.leads import call_text, deeper
from es_agent.playbooks import MCP_TOOLS, PLAYBOOKS

FAILS: list[str] = []


def check(ok: bool, what: str, detail: str = "") -> None:
    print(("ok    " if ok else "FAIL  ") + what + ("" if ok or not detail else f": {detail[:300]}"))
    if not ok:
        FAILS.append(what)


def strings(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, list):
        for x in v:
            yield from strings(x)
    elif isinstance(v, dict):
        for x in v.values():
            yield from strings(x)


def audit(name: str, d: dict | None, reading: dict) -> None:
    check(d is not None, f"{name}: a playbook matches")
    if not d:
        return
    check(d["leads"] != [], f"{name}: has leads")
    ids = set(reading["series_ids"])
    for ld in d["leads"]:
        if ld["tool"]:
            check(ld["tool"] in MCP_TOOLS, f"{name}: tool {ld['tool']} exists")
            bad = set(ld["args"]) - MCP_TOOLS.get(ld["tool"], set())
            check(not bad, f"{name}: {ld['tool']} args are real", str(bad))
        else:
            check(bool(ld.get("proposed_tool")) and ld["proposed_tool"] not in MCP_TOOLS,
                  f"{name}: a missing tool is named as proposed ({ld.get('proposed_tool')})")
        named = [s for s in strings(ld["args"]) if "." in s and not s[:4].isdigit() and not s.startswith("<")]
        check(all(s in ids for s in named), f"{name}: step {ld['step']} {ld['tool'] or ld['proposed_tool']} names only series of the reading",
              str([s for s in named if s not in ids]))
        check(not any("{" in s for s in strings(ld)), f"{name}: step {ld['step']} has no unfilled slot")
        check(call_text(ld) in d["for_your_agent"], f"{name}: for_your_agent holds step {ld['step']}'s call")
    check(all(m in d["for_your_agent"] for m in d["must_say"]), f"{name}: for_your_agent holds the must-say lines")
    check({x["step"] for x in d["done"]} | {x["step"] for x in d["left"]} == set(next(p for p in PLAYBOOKS if p["id"] == d["playbook"]["id"])["steps"]),
          f"{name}: done and left cover every step")


def reading(key, ids, period="2026-11-20"):
    return {"key": key, "series_ids": ids, "period": period, "hypothetical": False, "values": {}}


ANSWERS = {
    "two-measures-disagree": {"summary": "s", "caveats": [], "cites": ["fspread:brent_wti"],
                              "readings": [reading("fspread:brent_wti", ["ICE.BRENT.2027-01.D", "NYMEX.WTI.2027-01.D", "PET.RBRTE.D", "PET.RWTC.D"])]},
    "high-or-low-for-the-season": {"summary": "s", "caveats": [], "cites": ["seasonal:PET.WCESTUS1.W:5"],
                                   "readings": [reading("seasonal:PET.WCESTUS1.W:5", ["PET.WCESTUS1.W"])]},
    "what-changed-this-week": {"summary": "s", "caveats": [], "cites": ["surprises:week"],
                               "readings": [reading("surprises:week", ["PET.RWTC.D", "PET.WCESTUS1.W", "PET.RBRTE.D"])]},
}
for pb in PLAYBOOKS:
    a = ANSWERS[pb["id"]]
    d = deeper(a, "a question")
    audit(pb["id"], d, a["readings"][0])
    check(d is not None and d["playbook"]["id"] == pb["id"], f"{pb['id']}: the right playbook")
    check(deeper(a, "a question") == d, f"{pb['id']}: deterministic")

check(deeper({"summary": "s", "cites": [], "readings": []}) is None, "no reading cited: None")
check(deeper({"summary": "s", "cites": ["curve:brent"], "readings": [reading("curve:brent", ["ICE.BRENT.M1.D"])]}) is None,
      "a reading no playbook wants: None")
check(deeper({"summary": "s", "cites": ["fspread:brent_wti"], "readings": [dict(reading("fspread:brent_wti", ["A.B"]), hypothetical=True)]}) is None,
      "a hypothetical reading does not trigger")

real = json.load(open("fixtures/brent_wti_answer.json", encoding="utf8"))
d = deeper(real, "Why do the two Brent-WTI spreads disagree?")
audit("brent-wti", d, real["readings"][0])
check(d is not None and [x["step"] for x in d["done"]] == [1, 2] and [x["step"] for x in d["left"]] == [3, 4, 5, 6],
      "brent-wti: steps 1-2 done, 3-6 left")
check(d is not None and {ld["args"].get("series_b") for ld in d["leads"] if ld["tool"] == "spread"} == {"NYMEX.WTI.2027-01.D", "ICE.BRENT.2027-01.D"},
      "brent-wti: each spot price against its own future")
if d and "--show" in sys.argv:
    print(json.dumps(d, indent=1)); print(d["for_your_agent"])

print(f"\n{len(FAILS)} failures" if FAILS else "\nall ok")
sys.exit(1 if FAILS else 0)
