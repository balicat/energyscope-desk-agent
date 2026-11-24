"""Trail control: a sentence the model writes into a tool's arguments never reaches the page's progress steps, the
API's answer or the question log (es_agent/trail.py; the adversary's independent review, 24 Nov 2026, 58d8ec0a
item 2). Free: frozen data and a scripted model that dictates.

    LIBRARIAN_TODAY=$(python -c "import json;print(json.load(open('fixtures/series.json'))['as_of'])") python trail_controls.py

The scripted model writes a marker sentence into a search, a series id, a list of series ids, a server tool's
series id and a tool the agent does not have, then answers. The control runs serve.answer itself (the code the
public site runs), collects every progress event and the logged line, and fails if the marker appears anywhere
in them. It also checks the true parts survive: the words a search matched, a known series id, a fixed choice.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

MARK = "ZQXMARKER"
SENTENCE = f"Brent will reach 150 dollars next week {MARK} tell everyone"

tmp = tempfile.mkdtemp()
os.environ["LIBRARIAN_SOURCE"] = "fixture"
os.environ["LIBRARIAN_LOG"] = os.path.join(tmp, "questions.jsonl")
os.environ.pop("ANTHROPIC_API_KEY", None)

import serve  # noqa: E402
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart  # noqa: E402
from pydantic_ai.models.function import AgentInfo, FunctionModel  # noqa: E402

from es_agent.sources import FixtureSource  # noqa: E402

serve._source = FixtureSource(os.environ.get("LIBRARIAN_FIXTURE", "fixtures/series.json"))
os.environ.setdefault("LIBRARIAN_TODAY", serve._source.as_of)
FAILS: list[str] = []


def check(ok: bool, what: str, detail: str = "") -> None:
    print(("ok    " if ok else "FAIL  ") + what + ("" if ok or not detail else f": {detail[:300]}"))
    if not ok:
        FAILS.append(what)


def dictating(messages, info: AgentInfo) -> ModelResponse:
    """First turn: every argument that can hold text carries the marker sentence. Then a plain declined answer."""
    if len(messages) == 1:
        return ModelResponse(parts=[
            ToolCallPart("search_series", {"query": "WTI spot price"}, tool_call_id="c1"),
            ToolCallPart("get_change", {"series_id": SENTENCE, "lookback_days": 7}, tool_call_id="c2"),
            ToolCallPart("get_latest", {"series_ids": ["PET.RWTC.D", SENTENCE]}, tool_call_id="c3"),
            ToolCallPart("get_latest", {"series_ids": ["PET.RWTC.D"]}, tool_call_id="c3b"),
            ToolCallPart("get_percentile", {"series_id": SENTENCE, "years": 3}, tool_call_id="c4"),
            ToolCallPart(f"say_{MARK}_to_everyone", {"text": SENTENCE}, tool_call_id="c5"),
            ToolCallPart("get_surprises", {"window": "month"}, tool_call_id="c6"),
            ToolCallPart("search_series", {"query": SENTENCE, "dataset": f"{MARK} PET"}, tool_call_id="c7"),
            ToolCallPart("search_series", {"query": SENTENCE}, tool_call_id="c8"),
        ])
    return ModelResponse(parts=[ToolCallPart("final_result", {
        "facts": [], "summary": "The data does not hold what was asked.", "caveats": []}, tool_call_id="f1")])


serve._model_for = lambda question: FunctionModel(dictating)
events: list[dict] = []
out = serve.answer("What is the latest WTI spot price?", None, emit=lambda tool, args: events.append({"tool": tool, "args": args}))
logged = open(os.environ["LIBRARIAN_LOG"], encoding="utf-8").read() if os.path.exists(os.environ["LIBRARIAN_LOG"]) else ""

blob_events = json.dumps(events, ensure_ascii=False)
blob_out = json.dumps(out, ensure_ascii=False)
check(MARK not in blob_events, "the progress events (the page's steps) carry no dictated text", blob_events)
check(MARK not in json.dumps(out.get("trail"), ensure_ascii=False), "the API's trail carries no dictated text",
      json.dumps(out.get("trail")))
check(MARK not in blob_out.replace(out.get("question", ""), ""), "nothing else in the API's answer carries it either")
check(MARK not in logged, "the question log carries no dictated text", logged[:300])
trail = out.get("trail") or []
names = [t["tool"] for t in trail]
check("unknown tool" in names and not any(MARK in n for n in names), "a tool the agent does not have is not named",
      json.dumps(names))
s1 = next((t for t in trail if t["tool"] == "search_series"), {})
check(s1.get("args", {}).get("query") == "wti spot price", "a search that matched keeps its words", json.dumps(s1))
from es_agent import trail as T  # noqa: E402
from es_agent.models import SeriesHit  # noqa: E402
hit = SeriesHit(series_id="PET.RWTC.D", name="Cushing, OK WTI Spot Price FOB, Daily", units="Dollars per Barrel", frequency="D")
q = T.query_words(f"WTI spot price {SENTENCE}", [hit])
check(q == "wti spot price", "a search keeps only the words the search matched (the lake's search finds hits for a "
      "query with extra words; the dictated words are dropped)", repr(q))
s8 = [t for t in trail if t["tool"] == "search_series"][-1]
check(s8.get("args") == {}, "a search that found nothing keeps no query at all (a whole dictated sentence)",
      json.dumps(s8))
latests = [t for t in trail if t["tool"] == "get_latest"]
check(len(latests) == 2 and latests[0].get("args") == {} and latests[1].get("args") == {"series_ids": ["PET.RWTC.D"]},
      "a call holding a dictated id is refused and keeps its name only; a call of known ids keeps them",
      json.dumps(latests))
ev_latest = [e for e in events if e["tool"] == "get_latest"]
check(all(e["args"].get("series_ids") == ["PET.RWTC.D"] for e in ev_latest),
      "even the refused call's progress step shows only the known id", json.dumps(ev_latest))
change = next((t for t in trail if t["tool"] == "get_change"), {})
check(change.get("args") == {}, "a refused call (an unknown series) keeps its tool name only", json.dumps(change))
surprises = next((t for t in trail if t["tool"] == "get_surprises"), {})
check(surprises.get("args") == {"window": "month"}, "a fixed choice survives", json.dumps(surprises))
ev_search = [e for e in events if e["tool"] == "search_series"]
check(bool(ev_search) and all("dataset" not in e["args"] for e in ev_search[1:]),
      "an unknown dataset is not repeated", json.dumps(ev_search))
print(f"\n{len(FAILS)} FAIL(s)")
sys.exit(1 if FAILS else 0)
