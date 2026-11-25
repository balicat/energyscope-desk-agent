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

from es_agent.leads import call_text, continuous, deeper
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
    ids = set(reading["series_ids"]) | {continuous(i) for i in reading["series_ids"]}
    for ld in d["leads"]:
        check(ld["tool"] in MCP_TOOLS, f"{name}: tool {ld['tool']} exists (every lead runs today)")
        bad = set(ld["args"]) - MCP_TOOLS.get(ld["tool"], set())
        check(not bad, f"{name}: {ld['tool']} args are real", str(bad))
        named = [s for s in strings(ld["args"]) if "." in s and not s[:4].isdigit() and not s.startswith("<")]
        check(all(s in ids for s in named), f"{name}: step {ld['step']} {ld['tool']} names only series of the reading",
              str([s for s in named if s not in ids]))
        check(not any("{" in s for s in strings(ld)), f"{name}: step {ld['step']} has no unfilled slot")
        check(call_text(ld) in d["for_your_agent"], f"{name}: for_your_agent holds step {ld['step']}'s call")
    check(d["for_your_agent"].startswith("Needs the EnergyScope data tools (MCP server energyscope-mcp 2.16.0 or later). A free key: https://energyscope.io/signup\n"),
          f"{name}: for_your_agent starts with the key line")
    check("proposed" not in d["for_your_agent"] and all(x["tool"] + "(" not in d["for_your_agent"] for x in d["planned"]),
          f"{name}: planned tools are not shown as calls")
    check(all(x["tool"] not in MCP_TOOLS for x in d["planned"]), f"{name}: planned tools are ones the server lacks")
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
check(d is not None and {ld["args"].get("series_b") for ld in d["leads"] if ld["tool"] == "spread"} == {"NYMEX.WTI.FRONT.D", "ICE.BRENT.M1.D"},
      "brent-wti: each spot price against its own future (continuous series)")
check(d is not None and not any("2027" in json.dumps(ld["args"]) for ld in d["leads"] if ld["tool"] == "spread"),
      "brent-wti: history leads never name a dated contract")
check(d is not None and d["planned"] == [] and {ld["tool"] for ld in d["leads"]} == {"spread", "gap_breakpoints", "jumps", "get_data"}, "brent-wti: no planned tools, the two new tools are real leads")
check(d is not None and any("2027-01" in json.dumps(ld["args"]) for ld in d["leads"] if ld["tool"] == "get_data"),
      "brent-wti: the short-window lead keeps the dated contracts")
for dated, cont in [("ICE.BRENT.2027-01.D", "ICE.BRENT.M1.D"), ("NYMEX.WTI.2027-01.D", "NYMEX.WTI.FRONT.D"),
                    ("GME.OMAN.2027-01.D", "GME.OMAN.M1.D"), ("PET.RWTC.D", "PET.RWTC.D"), ("ICE.BRENT.M1.D", "ICE.BRENT.M1.D")]:
    check(continuous(dated) == cont, f"continuous({dated}) = {cont}")
check(d is not None and sorted((ld["args"]["series_id"], ld["args"].get("series_b") or "") for ld in d["leads"] if ld["tool"] == "jumps") == [("PET.RBRTE.D", ""), ("PET.RBRTE.D", "ICE.BRENT.M1.D"), ("PET.RWTC.D", ""), ("PET.RWTC.D", "NYMEX.WTI.FRONT.D")], "brent-wti: jumps on each spot series and on each spot-against-front gap")
check([x["tool"] for x in deeper(ANSWERS["what-changed-this-week"])["planned"]] == ["consensus_expectations"], "what-changed: consensus_expectations stays planned")
# --- adversary round (26 Nov 2026): no pair of different commodities or units, honest label, short histories
from es_agent.playbooks import OWN_FUTURE, SHORT_HISTORY  # noqa: E402

PAIR_TOOLS = ("spread", "gap_breakpoints")


def pair_leads(d):
    """(a, b) of every lead that pairs two series: spread, gap_breakpoints, and jumps with a series_b."""
    out = []
    for ld in d["leads"]:
        a = ld["args"]
        if ld["tool"] in PAIR_TOOLS:
            out.append((a["series_a"], a["series_b"]))
        elif ld["tool"] == "jumps" and a.get("series_b"):
            out.append((a["series_id"], a["series_b"]))
    return out


def same_commodity(a, b):
    return a in OWN_FUTURE and OWN_FUTURE[a]["future"] == b


CRACK = ["PET.RWTC.D", "PET.EER_EPMRU_PF4_RGC_DPG.D", "PET.EER_EPD2F_PF4_Y35NY_DPG.D"]
dc = deeper({"summary": "s", "cites": ["crack:3-2-1"], "readings": [reading("crack:3-2-1", CRACK)]}, "q")
check(dc is not None and pair_leads(dc) == [], "crack: no lead pairs two series")
check(dc is not None and any(ld["tool"] == "crack_spread" and ld["args"]["crude"] == CRACK[0] and ld["args"]["gasoline"] == CRACK[1]
                             and ld["args"]["distillate"] == CRACK[2] and ld["args"]["ratio"] == "3-2-1" for ld in dc["leads"]),
      "crack: a crack_spread lead with the reading's own three series")
check(dc is not None and dc["done"] == [], "crack: no step is claimed done")
FC = ["NYMEX.WTI.2026-12.D", "NYMEX.RBOB.2026-12.D", "NYMEX.HO.2026-12.D"]
df = deeper({"summary": "s", "cites": ["fcrack:3-2-1"], "readings": [reading("fcrack:3-2-1", FC)]}, "q")
check(df is not None and pair_leads(df) == [] and all(ld["tool"] != "jumps" for ld in df["leads"]),
      "fcrack: no pair, gap or jumps lead (a continuous front is never paired with a dated contract)")
check(df is not None and df["done"] == [], "fcrack: no step is claimed done")

golden = json.load(open("results/golden.json", encoding="utf8"))
n_leads = n_pairs = 0
for qid, ans in golden.items():
    d = deeper(ans, "q")
    if not d:
        continue
    n_leads += len(d["leads"])
    for a, b in pair_leads(d):
        n_pairs += 1
        check(same_commodity(a, b), f"golden {qid}: pair lead {a} / {b} is a spot and its own future")
check(True, f"golden: deeper() ran over {len(golden)} answers, {n_leads} leads, {n_pairs} pair leads, every one same commodity and unit")

ok_ans = {"summary": "s", "caveats": [], "cites": ["seasonal:PET.WCESTUS1.W:5"], "checked": True, "degraded": False,
          "readings": [reading("seasonal:PET.WCESTUS1.W:5", ["PET.WCESTUS1.W"])]}
check("(checked by code against the data)" in deeper(ok_ans, "q")["for_your_agent"], "label: checked and not degraded says checked")
bad = deeper({**ok_ans, "checked": False, "check_problems": ["a number did not match"]}, "q")["for_your_agent"]
check("checked by code" not in bad and "NOT fully checked: a number did not match" in bad, "label: a failed check says so")
deg = deeper({**ok_ans, "degraded": True, "degraded_reason": "no summary passed the checks"}, "q")["for_your_agent"]
check("checked by code" not in deg and "NOT fully checked: no summary passed the checks" in deg, "label: a degraded answer says why")
check("checked by code" not in deeper({k: v for k, v in ok_ans.items() if k != "checked"}, "q")["for_your_agent"],
      "label: an answer that does not say it was checked is not called checked")
src = open("serve.py", encoding="utf8").read()
check(src.index("deeper(out, question)") > src.index("degraded_reason=degraded"), "serve: deeper is built after checked and degraded are set")

bw = {"summary": "s", "caveats": [], "cites": ["percentile:SHIP.BWET.D:5"], "checked": True,
      "readings": [reading("percentile:SHIP.BWET.D:5", ["SHIP.BWET.D"])]}
db = deeper(bw, "q")
check("SHIP.BWET.D" in SHORT_HISTORY and all(ld["tool"] != "seasonal" for ld in db["leads"]), "short history: no seasonal lead for SHIP.BWET.D")
pc = {**ok_ans, "cites": ["percentile:PET.WCESTUS1.W:5"], "readings": [reading("percentile:PET.WCESTUS1.W:5", ["PET.WCESTUS1.W"])]}
check(any(ld["tool"] == "seasonal" for ld in deeper(pc, "q")["leads"]), "long history: a seasonal lead for a weekly stock series")
check(all("holiday shifts the comparison" not in n["text"] for p in PLAYBOOKS for n in p["notes"]), "the ISO-week note no longer says a holiday shifts the week")

if d and "--show" in sys.argv:
    print(json.dumps(d, indent=1)); print(d["for_your_agent"])

print(f"\n{len(FAILS)} failures" if FAILS else "\nall ok")
sys.exit(1 if FAILS else 0)
