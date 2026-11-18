"""Offline stand-in for an LLM.

A FunctionModel that follows a fixed plan of tool calls, then writes a draft from the slots the
tools actually offered. It exercises the real tools, the slot table, the validator and the evals
with no API key; it does not measure model judgement (that is what the live run is for).

With sloppy=True the first draft is wrong in the two ways a model can still be wrong: it types a
figure instead of placing a slot, or it writes a curve's shape in its own word. The run shows the
validator rejecting it and the retry fixing it; with the validator off, the evaluators must catch it.
"""

from __future__ import annotations

import json

from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, RetryPromptPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel


def _plain(x):
    if hasattr(x, "model_dump"):
        return x.model_dump(mode="json")
    if isinstance(x, list):
        return [_plain(i) for i in x]
    if isinstance(x, str):
        try:
            return json.loads(x)
        except ValueError:
            return x
    return x


def _sheets(returns: list[ToolReturnPart]) -> list[tuple[str, dict]]:
    out = []
    for r in returns:
        body = _plain(r.content)
        for sh in body if isinstance(body, list) else [body]:
            if isinstance(sh, dict) and "figures" in sh:
                out.append((r.tool_name, sh))
    return out


# Which of a reading's slots a code-written answer places, by kind of reading. A trailing * matches any ending.
_PICK = {
    "curve": ("shape", "M1_minus_M2", "M1_minus_M1*", "move"),
    "crack": ("crack", "crack_percentile"), "fcrack": ("crack", "crack_percentile"),
    "fspread": ("brent_minus_wti", "spread_percentile", "spot_brent_minus_wti", "spot_spread_percentile"),
    "seasonal": ("latest", "difference", "difference_pct", "range"),
    "positioning": ("managed_money_net", "net_change_on_week", "net_percentile"),
    "percentile": ("latest", "percentile"),
    "arb": ("verdict", "score", "brent_minus_wti", "spread_percentile", "freight_percentile", "europe_minus_us_per_gallon",
            "difference_percentile"),
    "surprises": ("*: change",), "watch": ("flag_*",), "evidence": ("balance", "groups", "line_*"),
    "scenario": ("*_change", "*_change_pct", "observed_score", "observed_crack", "scenario_score", "scenario_crack", "verdict"),
}
_WITH_HISTORY = ("crack", "fcrack", "fspread", "positioning", "percentile", "arb")


def _picked(src: str, offered: dict) -> list[str]:
    """The slots of one reading that a brief places, in the order of _PICK; every slot when the kind is not listed."""
    wanted = _PICK.get(src.split(":", 1)[0])
    if wanted is None:
        return list(offered)
    out = []
    for w in wanted:
        for address in offered:
            field = address[len(src) + 2:-1]
            hit = field == w or (w.endswith("*") and field.startswith(w[:-1])) or (w.startswith("*") and field.endswith(w[1:]))
            if hit and address not in out and not field.endswith("_a_week_earlier"):
                out.append(address)
    return out or list(offered)


def _answer(returns: list[ToolReturnPart], sloppy: bool) -> dict:
    lines = []
    for tool, sh in _sheets(returns):
        src, offered = sh["source"], {**sh["figures"], **sh["statements"]}

        def slot(field: str) -> str:
            return "{" + src + "." + field + "}"

        if tool == "get_latest":
            lines.append(f"From the data: {slot('value')}.")
        elif tool == "get_change":
            lines.append(f"From the data: {slot('value')}; {slot('change')}.")
        elif tool == "get_spread":
            lines.append("From the data: " + "; ".join(a for a in (slot("gap"), slot("percentile")) if a in offered) + ".")
        else:
            lead = "If the assumed changes happened: " if any("(hypothetical)" in t for t in offered.values()) else "From the data: "
            lines.append(lead + "; ".join(_picked(src, offered)) + ".")
            history = next((a for a in ("{" + src + ".context.1}", "{" + src + ".context}") if a in sh["sentences"]), None)
            if history and src.split(":", 1)[0] in _WITH_HISTORY:
                lines.append(history)
            if sloppy and slot("shape") in offered:  # the curve's shape in the model's own word, and the wrong one
                wrong = "the curve is in contango" if "backwardation" in offered[slot("shape")] else "the curve is in backwardation"
                lines[-1] = lines[-1].replace(slot("shape"), wrong)
    if not lines:
        return {"summary": "No EnergyScope series matched the question.", "limits": ["not_in_data"]}
    if sloppy and "value}" in lines[0]:  # a figure typed, not placed
        lines[0] = "From the data: about 99.50 dollars per barrel" + lines[0].partition(".value}")[2]
    return {"summary": " ".join(lines), "cites": [], "limits": []}


def is_rejection(p) -> bool:
    """A retry request. Pydantic AI has used three shapes for it: RetryPromptPart, a ToolReturnPart with
    outcome/retry set, and RetryFeedbackPart for a rejected text output. Until 18 Nov 2026 the third was
    not recognised here, so a live model's retries were counted as none; the validator's own record
    (Deps.rejections) is now the count, and this is the cross-check."""
    if isinstance(p, RetryPromptPart) or getattr(p, "retry", None):
        return True  # RetryFeedbackPart: how a rejected text output comes back (the live model answers in text, not by tool)
    return isinstance(p, ToolReturnPart) and getattr(p, "outcome", None) not in (None, "success")


def scripted(plan: list[tuple[str, dict]], sloppy: bool = False) -> FunctionModel:
    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        parts = [p for m in messages if isinstance(m, ModelRequest) for p in m.parts]
        output_tool = info.output_tools[0].name
        returns = [p for p in parts if isinstance(p, ToolReturnPart) and p.tool_name != output_tool]
        rejected = [p for p in parts if is_rejection(p) and p.tool_name == output_tool]
        if len(returns) < len(plan):
            name, args = plan[len(returns)]
            return ModelResponse(parts=[ToolCallPart(name, args)])
        return ModelResponse(parts=[ToolCallPart(output_tool, _answer(returns, sloppy and not rejected))])

    return FunctionModel(fn, model_name="scripted")
