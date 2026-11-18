"""Offline stand-in for an LLM.

A FunctionModel that follows a fixed plan of tool calls, then writes the
answer from the tool results it actually received. It exercises the real
tools, the typed output, the validator and the evals with no API key; it
does not measure model judgement (that is what the live run is for).

With sloppy=True the first answer is wrong (one number misquoted, or a curve given the
opposite shape), so the run shows the output validator rejecting it and the retry fixing it.
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
    facts, spreads, cites, lines = [], [], [], []
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
        elif r.tool_name == "get_spread":
            spreads.append(body)
            lines.append(
                f"{body['name_a']} was {body['value_a']:.2f} and {body['name_b']} was {body['value_b']:.2f} "
                f"{body['units']} on {body['period']}: a spread of {body['spread']:.2f}."
            )
        elif r.tool_name in ("get_curve", "get_crack_spread", "get_seasonal", "get_positioning", "get_percentile", "get_arbitrage", "get_surprises", "get_watch", "get_arbitrage_scenario", "get_crack_scenario", "get_futures_spread", "get_futures_crack", "get_evidence"):
            cites.append(body["key"])
            # A change is written with its direction, as the prose rules require of any model.
            shown = ", ".join(f"{k} {'up' if v > 0 else 'down'} {abs(v):.2f}" if "change" in k and v else f"{k} {v:.2f}"
                              for k, v in body["values"].items())
            lead = "If the stated changes happened, hypothetically: " if body.get("hypothetical") else ""
            shape = f" The curve is in {body['note'].split(' ')[0].rstrip(':')}." if r.tool_name == "get_curve" else ""
            lines.append(f"{lead}{body['title']} on {body['period']}: {shown}.{shape}")
    if not facts and not spreads and not cites:
        return {"facts": [], "summary": "No EnergyScope series matched the question.",
                "caveats": [f"The data does not hold this: {question}"]}
    return {"facts": facts, "spreads": spreads, "cites": cites, "summary": " ".join(lines), "caveats": []}


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
        elif sloppy and not rejected:  # no facts: a curve reading, described with the opposite shape
            flip = {"in backwardation.": "in contango.", "in contango.": "in backwardation."}
            for a, b in flip.items():
                if a in answer["summary"]:
                    answer["summary"] = answer["summary"].replace(a, b)
                    break
        return ModelResponse(parts=[ToolCallPart(output_tool, answer)])

    return FunctionModel(fn, model_name="scripted")
