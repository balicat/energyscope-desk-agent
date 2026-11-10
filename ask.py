"""Ask the desk agent one question and print the typed answer plus the tool trail.

    python ask.py "How has WTI moved over the last 30 days?" --model anthropic:claude-sonnet-5-5
"""

from __future__ import annotations

import argparse

from pydantic_ai.messages import ToolCallPart

from es_agent.agent import Deps, agent
from es_agent.scripted import is_rejection
from es_agent.sources import FlightSource, ParquetLakeSource


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--model", required=True, help="e.g. anthropic:claude-sonnet-5-5 or openai:gpt-5")
    ap.add_argument("--source", default="lake", choices=["lake", "flight"])
    ap.add_argument("--lake", default="/opt/energyscope/data")
    args = ap.parse_args()

    source = ParquetLakeSource(args.lake) if args.source == "lake" else FlightSource()
    result = agent.run_sync(args.question, model=args.model, deps=Deps(source=source))

    for m in result.all_messages():
        for p in m.parts:
            if isinstance(p, ToolCallPart):
                print(f"-> {p.tool_name}({p.args})")
            elif is_rejection(p):
                print(f"<- retry: {str(p.content)[:300]}")
    print()
    print(result.output.model_dump_json(indent=2))
    print(f"\nusage: {result.usage}")


if __name__ == "__main__":
    main()
