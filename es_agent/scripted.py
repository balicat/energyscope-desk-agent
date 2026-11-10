"""Offline stand-in for an LLM.

A FunctionModel that follows a fixed plan of tool calls, then writes the
answer from the tool results it actually received. It exercises the real
tools, the typed output, the validator and the evals with no API key; it
does not measure model judgement (that is what the live run is for).

With sloppy=True the first answer misquotes one number, so the run shows the
output validator rejecting it and the retry fixing it.
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


def _answer(returns: list[ToolReturnPart], question: str) -> dict:
    facts, lines = [], []
    for r in returns:
        body = _plain(r.content)
        if r.tool_name == "get_latest":
            for o in body:
                facts.append({k: o[k] for k in ("series_id", "name", "units", "value", "period")})
                facts[-1]["latest_value"] = facts[-1].pop("value")
                facts[-1]["latest_period"] = facts[-1].pop("period")
                lines.append(f"{o['name']} was {o['value']:.2f} {o['units']} on {o['period']}.")
        elif r.tool_name == "get_change":
            c = body
            facts.append({k: c[k] for k in ("series_id", "name", "units", "latest_period", "latest_value",
                                             "lookback_days", "base_period", "base_value", "change_abs", "change_pct")})
            way = "up" if c["change_abs"] >= 0 else "down"
            lines.append(
                f"{c['name']} was {c['latest_value']:.2f} {c['units']} on {c['latest_period']}, {way} "
                f"{abs(c['change_abs']):.2f} ({abs(c['change_pct']):.2f}%) from {c['base_value']:.2f} "
                f"on {c['base_period']}, {c['lookback_days']} days earlier."
            )
    if not facts:
        return {"facts": [], "summary": "No EnergyScope series matched the question.",
                "caveats": [f"search_series found nothing suitable for: {question}"]}
    return {"facts": facts, "summary": " ".join(lines), "caveats": []}


def is_rejection(p) -> bool:
    """A retry request. Pydantic AI 2.x returns a rejected output as a ToolReturnPart
    with outcome/retry set; older versions used RetryPromptPart."""
    if isinstance(p, RetryPromptPart):
        return True
    return isinstance(p, ToolReturnPart) and (bool(getattr(p, "retry", None)) or getattr(p, "outcome", None) not in (None, "success"))


def scripted(plan: list[tuple[str, dict]], sloppy: bool = False) -> FunctionModel:
    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        parts = [p for m in messages if isinstance(m, ModelRequest) for p in m.parts]
        question = next((p.content for p in parts if p.part_kind == "user-prompt"), "")
        output_tool = info.output_tools[0].name
        returns = [p for p in parts if isinstance(p, ToolReturnPart) and p.tool_name != output_tool]
        rejected = [p for p in parts if is_rejection(p) and p.tool_name == output_tool]
        if len(returns) < len(plan):
            name, args = plan[len(returns)]
            return ModelResponse(parts=[ToolCallPart(name, args)])
        answer = _answer(returns, str(question))
        if sloppy and not rejected and answer["facts"]:
            answer["facts"][0]["latest_value"] = round(answer["facts"][0]["latest_value"] * 1.05, 2)
        return ModelResponse(parts=[ToolCallPart(output_tool, answer)])

    return FunctionModel(fn, model_name="scripted")
