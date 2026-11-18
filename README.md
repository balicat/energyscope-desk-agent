# EnergyScope desk agent: a Pydantic AI spike

**Live as The Librarian: [thelibrarian.energy](https://thelibrarian.energy).** Ask an oil or gas market question;
the page shows the answer, the series and values behind it, the tool calls, and whether the numbers passed a
recomputation from the data.

Built 10 Nov 2026, first run on a live model 18 Nov 2026, against the live [EnergyScope](https://energyscope.io) Parquet lake on my own server
(Pydantic AI 2.66, pydantic-evals 2.66, Python 3.14).

A desk analyst asks a question in plain English ("How do US commercial crude
stocks compare with a year ago?"). The agent finds the series, pulls the
numbers through tools, and returns a typed answer. Every number in the answer
has to trace back to a tool result, or the answer is sent back.

## What it shows

| Pydantic AI feature | Where |
|---|---|
| Tools as typed Python functions (`@agent.tool`) | `es_agent/agent.py`: `search_series`, `get_latest`, `get_change`, `get_spread`, `get_curve`, `get_crack_spread`, `get_seasonal`, `get_positioning` |
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
- **The model cites, code copies.** Curves, crack spreads, seasonal comparisons and positioning come back as a
  keyed reading (`curve:brent`, `crack:3-2-1`). The model lists the keys it used; the validator copies the
  readings into the answer, so a twelve-month curve cannot be mistyped, and the key is enough to recompute it.
- **Budgets live in the tools.** `search_series` stops after four calls in a run and says so. An instruction to
  "stop after two failed searches" did not hold: one model searched 18 times on a question it should decline
  ($0.21 for one answer). The budget in code brought that to six calls.
- **The same check runs on live traffic.** `verify()` is the `Grounded` evaluator's logic; `serve.py` runs it on
  every answer after it is written, logs the result and returns it to the page.
- **Abstain, don't guess.** Asked for something the lake does not hold (EU
  carbon allowances), the right answer is no facts plus a caveat, and that is
  scored.
- **Storage is swappable.** `ParquetLakeSource` reads the lake on disk;
  `FlightSource` makes the same calls over Arrow Flight with the public
  `energyscope-client` package.

## Results (offline, scripted model, real data)

Ten cases, four evaluators each: `Grounded`, `SummaryTraceable`,
`RightSeries`, `MaxToolCalls(6)`.

| Run | Assertions | Notes |
|---|---|---|
| guard on (`python run_evals.py`) | **40/40** | `wti_30d` is deliberately sloppy: its first answer misquotes WTI by 5%. The validator rejects it (on 10 Nov: "latest is 2026-11-03 = 99.64, you wrote 104.62"), the retry fixes it: `retries: 1` |
| guard off (`--no-guard`) | **38/40** | the same bad number gets through the run, and `Grounded` + `SummaryTraceable` both fail it |

The control run is the point: it shows the evals catch the error on their own,
so a green run means something. Full reports: `results/`.

## Results (live models, 18 Nov 2026)

| Run | Assertions | Notes |
|---|---|---|
| first live run, five cases | **19/20** | every number matched the source and the carbon question was declined; `us_crude_yoy` used 8 tool calls against a budget of 6, because "commercial" is not in the publisher's series names and the all-words search returned nothing five times |
| after the search fix, five cases | **20/20** | search now falls back to names holding most of the query words; 2.6 tool calls and 5.5 s a question on average |
| with `get_spread`, six cases | **24/24** | 3.2 tool calls and 8.0 s a question on average, about $0.025 each. Report: `results/live-claude-sonnet-5-5.txt` |
| eight tools, ten cases, first run | **39/40** on both models | the carbon question took 7 to 8 tool calls against a budget of 6 before the model declined |
| eight tools, ten cases, with the search budget | **40/40** on both models | see the comparison below |

### Two models, one suite

The model is a run-time string, so changing it is one flag; the suite says what the change cost or bought.

| Model | Assertions | Tool calls / question | Seconds / question | Cost / question |
|---|---|---|---|---|
| `anthropic:claude-sonnet-5-5` | 40/40 | 2.8 | 7.1 | $0.034 |
| `anthropic:claude-haiku-5-5` | 40/40 | 2.5 | 5.5 | $0.0017 |

On these ten cases the smaller model scores the same at about a twentieth of the cost, so the public service
runs on it. What this does not show: ten cases is a small suite, and it scores numbers, series choice,
abstention and tool budget, not the quality of the prose. Reports: `results/live-*.txt`.


Five questions outside the suite, asked through `serve.py`: Henry Hub over a month and US gasoline stocks
against last year were answered with the series and dates; an election question and a request for the system
prompt and API key were declined with no tool calls; asked for the Brent-WTI spread, it quoted both prices
and said it does not compute numbers itself. That gap became the fourth tool, `get_spread` (one series minus
another on the latest date both have, computed in code), and the sixth eval case. Five questions is a smoke
test, not a measurement. Seven more, asked of the smaller model after the new tools went in (arbitrage, gasoline
margins, gas positioning, seasonal stocks, curve shape, a prompt-injection attempt, a two-part question), all
passed the live recomputation.

What the offline run does and does not prove: it exercises the real tools,
data, typed output, validator, retry path and evaluators. It does not measure
model judgement (series choice, when to abstain), because the scripted model
follows a fixed plan. That is what the live run above is for.

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
es_agent/readings.py  curve, crack spread, seasonal comparison, positioning; `compute(source, key)` rebuilds any of them
es_agent/verify.py    recompute an answer from the data (the Grounded eval and the live check)
es_agent/agent.py     the agent, eight tools, the output validator
es_agent/scripted.py  offline FunctionModel
run_evals.py          the eval suite
ask.py                one question, prints the tool trail and the typed answer
serve.py              HTTP front (POST /ask): per-address, per-day and per-question limits, and the live check
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
