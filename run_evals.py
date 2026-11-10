"""Eval suite: five desk questions scored on grounding, series choice,
abstention and tool budget.

    python run_evals.py                                  # offline, scripted model, Parquet lake
    python run_evals.py --no-guard                       # control: validator off, the evals must catch the bad number
    python run_evals.py --model anthropic:claude-sonnet-5-5
    python run_evals.py --model openai:gpt-5 --source flight

"Grounded" recomputes every fact from the data source, independently of the
run, so a number that drifted between tool and answer fails even if the
validator missed it.
"""

from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import dataclass

from pydantic_ai.messages import ToolCallPart
from pydantic_evals import Case, Dataset, increment_eval_metric
from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext, MaxToolCalls

from es_agent import metrics
from es_agent.agent import Deps, agent
from es_agent.models import DeskAnswer
from es_agent.sources import DataSource, FlightSource, ParquetLakeSource
from es_agent.scripted import is_rejection, scripted

WTI, BRENT = "PET.RWTC.D", "PET.RBRTE.D"
US_CRUDE = ["PET.WCESTUS1.W", "PET.WCRSTUS1.W"]  # excl. or incl. SPR: both are defensible readings
CUSHING = "PET.W_EPC0_SAX_YCUOK_MBBL.W"

# name, question, expected series (each inner list = acceptable alternatives), scripted plan, sloppy first answer
SUITE = [
    ("wti_30d", "Where is WTI spot now, and how has it moved over the last 30 days?", [[WTI]],
     [("search_series", {"query": "WTI spot price"}), ("get_change", {"series_id": WTI, "lookback_days": 30})], True),
    ("brent_vs_wti", "Latest Brent and WTI spot prices, please.", [[BRENT], [WTI]],
     [("search_series", {"query": "Brent spot price"}), ("search_series", {"query": "WTI spot price"}),
      ("get_latest", {"series_ids": [BRENT, WTI]})], False),
    ("us_crude_yoy", "How do US commercial crude oil stocks compare with a year ago?", [US_CRUDE],
     [("search_series", {"query": "US ending stocks excluding SPR crude oil"}),
      ("get_change", {"series_id": US_CRUDE[0], "lookback_days": 365})], False),
    ("cushing_4w", "Cushing crude stocks: latest level and the four-week change.", [[CUSHING]],
     [("search_series", {"query": "Cushing ending stocks crude"}), ("get_change", {"series_id": CUSHING, "lookback_days": 28})], False),
    ("abstain_carbon", "What did EU carbon allowances (EUA) settle at yesterday?", [],
     [("search_series", {"query": "EU carbon allowance EUA"})], False),
]
PLANS = {q: (plan, sloppy) for _, q, _, plan, sloppy in SUITE}
SOURCE: DataSource | None = None


@dataclass
class Grounded(Evaluator[str, DeskAnswer]):
    """Every fact equals a fresh recomputation from the source."""

    def evaluate(self, ctx: EvaluatorContext[str, DeskAnswer]) -> EvaluationReason:
        for f in ctx.output.facts:
            hit = SOURCE.meta(f.series_id)
            if hit is None:
                return EvaluationReason(False, f"{f.series_id} does not exist")
            lb = f.lookback_days or 0
            hist = SOURCE.history(f.series_id, start=dt.date.today() - dt.timedelta(days=lb + 400))
            truth = metrics.change_over(hit, hist, lb) if lb else metrics.latest_obs(hit, hist)
            tv = truth.latest_value if lb else truth.value
            tp = truth.latest_period if lb else truth.period
            if f.latest_period != tp or not metrics.close(f.latest_value, tv):
                return EvaluationReason(False, f"{f.series_id}: source says {tp}={tv}, answer says {f.latest_period}={f.latest_value}")
            if lb and not (metrics.close(f.change_pct, truth.change_pct) and metrics.close(f.base_value, truth.base_value)):
                return EvaluationReason(False, f"{f.series_id}: change differs from source")
        return EvaluationReason(True, f"{len(ctx.output.facts)} facts match the source")


@dataclass
class SummaryTraceable(Evaluator[str, DeskAnswer]):
    """No number in the prose that is not in the facts."""

    def evaluate(self, ctx):
        bad = metrics.untraceable_numbers(ctx.output)
        return EvaluationReason(not bad, f"untraceable: {bad}" if bad else "all summary numbers trace to facts")


@dataclass
class RightSeries(Evaluator[str, DeskAnswer]):
    """Picked an acceptable series for each thing asked about, or abstained when nothing fits."""

    def evaluate(self, ctx):
        want, got = ctx.metadata["expect"], {f.series_id for f in ctx.output.facts}
        if not want:
            ok = not got and bool(ctx.output.caveats)
            return EvaluationReason(ok, "abstained with a caveat" if ok else f"should abstain, answered with {sorted(got)}")
        missing = [alts for alts in want if not got & set(alts)]
        return EvaluationReason(not missing, f"missing one of {missing}" if missing else f"used {sorted(got)}")


def build_dataset() -> Dataset:
    cases = [Case(name=n, inputs=q, metadata={"expect": e}) for n, q, e, _, _ in SUITE]
    return Dataset(name="energyscope-desk", cases=cases, evaluators=[Grounded(), SummaryTraceable(), RightSeries(), MaxToolCalls(max_calls=6)])


def make_task(model_name: str, enforce: bool = True):
    async def task(question: str) -> DeskAnswer:
        model = scripted(*PLANS[question]) if model_name == "scripted" else model_name
        result = await agent.run(question, model=model, deps=Deps(source=SOURCE, enforce=enforce))
        parts = [p for m in result.all_messages() for p in m.parts]
        increment_eval_metric("retries", sum(is_rejection(p) for p in parts))
        increment_eval_metric("tool_calls", sum(isinstance(p, ToolCallPart) and p.tool_name != "final_result" for p in parts))
        increment_eval_metric("tokens", result.usage.total_tokens or 0)
        return result.output

    return task


def main() -> None:
    global SOURCE
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="scripted", help="'scripted' (offline) or a Pydantic AI model string")
    ap.add_argument("--source", default="lake", choices=["lake", "flight"])
    ap.add_argument("--lake", default="/opt/energyscope/data")
    ap.add_argument("--no-guard", action="store_true", help="switch the output validator off (control run)")
    args = ap.parse_args()

    try:  # local-only tracing so the span-based evaluators (MaxToolCalls) can see tool calls
        import logfire

        logfire.configure(send_to_logfire=False, console=False)
        logfire.instrument_pydantic_ai()
    except ImportError:
        pass

    SOURCE = ParquetLakeSource(args.lake) if args.source == "lake" else FlightSource()
    report = build_dataset().evaluate_sync(make_task(args.model, not args.no_guard), name=args.model + (" (guard off)" if args.no_guard else ""), max_concurrency=1, progress=False)
    report.print(include_input=False, include_output=False, include_durations=True)


if __name__ == "__main__":
    main()
