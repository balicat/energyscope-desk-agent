# EnergyScope desk agent: a Pydantic AI spike

Built 10 Nov 2026 against the live [EnergyScope](https://energyscope.io) Parquet lake on my own server
(Pydantic AI 2.66, pydantic-evals 2.66, Python 3.14).

A desk analyst asks a question in plain English ("How do US commercial crude
stocks compare with a year ago?"). The agent finds the series, pulls the
numbers through tools, and returns a typed answer. Every number in the answer
has to trace back to a tool result, or the answer is sent back.

## What it shows

| Pydantic AI feature | Where |
|---|---|
| Tools as typed Python functions (`@agent.tool`) | `es_agent/agent.py`: `search_series`, `get_latest`, `get_change` |
| Structured output (`output_type`) | `DeskAnswer` / `SeriesFact` in `es_agent/models.py` |
| Dependency injection (`deps_type`, `RunContext`) | `Deps` carries the data source and a ledger of every number a tool returned |
| Output validator + `ModelRetry` | `grounded()` rejects any fact that differs from the ledger and any summary number that traces to no fact |
| Provider-agnostic models | the model is a run-time string: `anthropic:...`, `openai:...`, or the offline scripted model |
| `FunctionModel` (offline testing) | `es_agent/scripted.py`: follows a fixed tool plan, writes the answer from real tool results |
| pydantic-evals: `Dataset`, `Case`, custom `Evaluator`s, built-in `MaxToolCalls` | `run_evals.py` |

Design rules:

- **The model picks series and writes sentences; code does the sums.** Changes
  and percentages are computed in `metrics.py`, never by the model.
- **One grounding rule, used twice.** `untraceable_numbers()` drives the
  validator (forces a retry during the run) and the `SummaryTraceable` eval
  (measures the final answer).
- **The eval does not trust the run.** `Grounded` recomputes every fact from
  the data source independently of the agent's ledger.
- **Abstain, don't guess.** Asked for something the lake does not hold (EU
  carbon allowances), the right answer is no facts plus a caveat, and that is
  scored.
- **Storage is swappable.** `ParquetLakeSource` reads the lake on disk;
  `FlightSource` makes the same calls over Arrow Flight with the public
  `energyscope-client` package.

## Results (offline, scripted model, real data)

Five cases, four evaluators each: `Grounded`, `SummaryTraceable`,
`RightSeries`, `MaxToolCalls(6)`.

| Run | Assertions | Notes |
|---|---|---|
| guard on (`python run_evals.py`) | **20/20** | `wti_30d` is deliberately sloppy: its first answer quotes WTI at 104.62. The validator rejects it ("latest is 2026-11-03 = 99.64, you wrote 104.62"), the retry fixes it: `retries: 1` |
| guard off (`--no-guard`) | **18/20** | the same bad number gets through the run, and `Grounded` + `SummaryTraceable` both fail it |

The control run is the point: it shows the evals catch the error on their own,
so a green run means something. Full reports: `results/`.

What the offline run does and does not prove: it exercises the real tools,
data, typed output, validator, retry path and evaluators. It does not measure
model judgement (series choice, when to abstain), because the scripted model
follows a fixed plan. That is what the live run is for.

## Run it

The Parquet lake (`--lake /opt/energyscope/data`) lives on my server and is not in this repo. Without it,
use `--source flight` with an EnergyScope API key (sign up at [energyscope.io](https://energyscope.io/signup)):
the agent, tools and evals are identical, only the `DataSource` changes.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/python run_evals.py                 # offline: scripted model, Parquet lake
.venv/bin/python run_evals.py --no-guard      # control run

export ANTHROPIC_API_KEY=...                  # live: any Pydantic AI model string
.venv/bin/python run_evals.py --model anthropic:claude-sonnet-5-5
.venv/bin/python ask.py "Cushing stocks: latest and four-week change?" --model anthropic:claude-sonnet-5-5

export ENERGYSCOPE_API_KEY=...                # over Arrow Flight instead of the local lake
.venv/bin/python run_evals.py --model anthropic:claude-sonnet-5-5 --source flight
```

## Files

```
es_agent/models.py    typed shapes: tool returns and the answer
es_agent/sources.py   DataSource protocol, ParquetLakeSource, FlightSource
es_agent/metrics.py   change calculations + the grounding rule
es_agent/agent.py     the agent, three tools, the output validator
es_agent/scripted.py  offline FunctionModel
run_evals.py          the eval suite
ask.py                one question, prints the tool trail and the typed answer
results/              eval reports
```

MIT licence.

## Notes from the build

- In Pydantic AI 2.66 a rejected output comes back as a `ToolReturnPart` on the
  output tool with `outcome="retried"`; earlier releases used `RetryPromptPart`.
  `is_rejection()` in `scripted.py` handles both.
- `Dataset(...)` now requires `name=`; `result.usage` is a property.
- The span-based evaluators (`MaxToolCalls`, `ToolCorrectness`,
  `TrajectoryMatch`) need tracing on. `logfire.configure(send_to_logfire=False)`
  plus `logfire.instrument_pydantic_ai()` gives them a span tree with nothing
  leaving the machine.
- Year-ago changes on weekly series compare against the last observation on or
  before the date 365 days earlier (2026-10-30 vs 2025-10-24), since weekly
  dates drift by a day a year.
