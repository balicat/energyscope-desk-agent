# The Librarian: a desk agent that shows where every number came from

**Live: [thelibrarian.energy](https://thelibrarian.energy).** Ask an oil or gas market question in plain English.
The page shows the answer, the series and values behind it, each tool call as it happens, and whether the
numbers passed a recomputation from the data.

Built on [Pydantic AI](https://ai.pydantic.dev) over the [EnergyScope](https://energyscope.io) data lake
(22 datasets: EIA, ICE, CFTC, GIE, IMF PortWatch, Baker Hughes, NOAA and others). It is a personal lab with no
customers. First version 10 Nov 2026 (offline only); first run on a live model and public launch 18 Nov 2026.

Named after 'The Librarian' in Neal Stephenson's *Snow Crash* (1992), the novel that also gave us 'The
Metaverse'. In the book The Librarian is a piece of software inside The Metaverse that knows a vast library,
cites it, and does not speculate.

## The rules it is built on

- **The model chooses tools and writes sentences; code does the sums.** Changes, spreads, percentiles, crack
  spreads and the arbitrage score are computed in `metrics.py` and `readings.py`, never by the model.
- **Every number must trace to a tool result.** An output validator rejects an answer whose facts differ from
  what the tools returned, or whose prose holds a number that appears in no fact, and sends the model back.
- **The model cites, code copies.** Curves, cracks, arbitrage, seasonal comparisons, percentiles and positioning
  come back as a keyed reading (`curve:brent`, `arb:us_crude_to_europe`). The model lists the keys it used; the
  validator copies the readings into the answer. A twelve-month curve cannot be mistyped, and the key alone is
  enough to recompute it.
- **History is written by code, not by the model.** A reading that ranks a level against its own past also says
  whether the level is beyond its 10th or 90th percentile line, since when, and when it was last so ("above the
  90th percentile line since 2026-07-30, 110 days; the previous spell was ..."). The sentence and its numbers are
  computed in `readings.spell()`, recomputed by the check, and the model may only restate them.
- **A what-if is labelled as one.** Scenario tools apply stated price changes to the latest observed prices and
  recompute in code. The reading is marked hypothetical, the page shows a badge, and an evaluator fails any
  answer that states a scenario number without its condition.
- **Charts come from the data, never from the model.** After the answer is written, `charts.py` builds the series
  behind it (with the percentile lines where they apply) and the page draws them.
- **The check does not trust the run.** `verify()` rebuilds every fact, spread and reading from the data source,
  independently of the agent's ledger. The eval suite uses it, and the public service runs it on every answer
  before showing the tick.
- **Budgets live in the tools, not the prompt.** `search_series` stops after four calls in a run and says so.
  An instruction to "stop after two failed searches" did not hold: one model searched 18 times on a question
  it should decline ($0.21 for one answer). The service also caps model requests per question, questions per
  address per hour, questions per day and dollars per day.
- **Memory holds conclusions, not tool output.** A follow-up question is given the earlier questions and the
  sentences that answered them. Any number it quotes must be fetched again in the current run, so a stale
  number cannot come through with a clean trace.
- **Abstain, don't guess.** Asked for something the data does not hold (EU carbon allowances), or something
  that is not an energy question, the right answer is no facts plus a stated reason, and that is scored.
- **The model is a run-time string.** Changing it is one flag; the suite says what the change cost or bought.

## Tools

| Tool | Returns |
|---|---|
| `search_series` | series by keyword, optionally within one dataset; four calls a run |
| `get_latest`, `get_change` | latest value; latest against N days earlier |
| `get_spread` | one series minus another on the latest shared date; refuses if units differ |
| `get_curve` | Brent futures M1 to M12, front spread, backwardation or contango |
| `get_crack_spread` | 3-2-1, gasoline or distillate margin in dollars per barrel |
| `get_watch` | flags for the week or month: unusual moves, stretched fund positioning, a curve that changed shape, stocks outside their five-year range, related prices that parted ways |
| `get_arbitrage_scenario`, `get_crack_scenario` | what-if: the arbitrage score or a crack spread recomputed with changed prices, marked hypothetical |
| `get_surprises` | the five most unusual moves over a week or month across an 18-series watchlist, by z-score against each series' own two years |
| `get_arbitrage` | the price side of a transatlantic route: spread and its three-year percentile, a freight proxy, curve slope, a score |
| `get_seasonal` | latest against the same time of year in the previous N years |
| `get_percentile` | where the latest value ranks in its own last N years |
| `get_positioning` | managed-money net, long, short, change on the week, three-year percentile |

What it cannot do: there are no route freight rates or physical differentials in the data (the arbitrage reading
says so and uses a tanker ETF as a proxy), no WTI futures curve, and no news.

## Evaluation

Twenty-three questions, five evaluators each (115 assertions): `Grounded` (recompute from source),
`SummaryTraceable` (no stray number in the prose), `RightSeries` (an acceptable series for each thing asked, or
a correct refusal), `ScenarioLabelled` (a what-if is stated as a condition), `MaxToolCalls(6)`. The questions cover prices, stocks, spreads, the curve, cracks, the
arbitrage and a what-if on it, the week's surprises and watch list, "when was it last this high", seasonal and
percentile comparisons, positioning, European gas storage, rig counts, tanker transits,
a follow-up, a cross-unit "spread" that must not be computed, a prompt injection and two out-of-scope questions.

| Run | Assertions | What it shows |
|---|---|---|
| scripted model, frozen data (`--source fixture`) | **115/115**, answers equal `results/golden.json` | tools, arithmetic, validator and evaluators agree with the recorded answers; no lake, no key, no cost. Runs in GitHub Actions on every push |
| scripted model, validator off (`--no-guard`) | **113/115** | the control: one case misquotes a price by 5% on purpose. With the validator on, the run rejects it and retries; with it off, `Grounded` and `SummaryTraceable` both fail it. A green run means something |
| `anthropic:claude-haiku-5-5`, live lake | **115/115** | 2.6 tool calls and 6.1 s a question, $0.0027 each. On the earlier 20-case suite the same model scored 78 to 80 of 80 across five runs; the misses were one question, traced to a bug (below) |
| `anthropic:claude-sonnet-5-5`, live lake (19 cases, before `get_surprises`) | **74/76** | 4.1 tool calls and 8.1 s, $0.057 each. It made 17 tool calls on the EU gas storage question and gave no series on the cross-unit question |

The public service runs on the smaller model: on this suite it scores higher at about a twenty-fifth of the
cost. What the suite does not measure: the quality of the prose, whether a market interpretation is economically
right, and anything outside twenty-three questions.

How the suite got here, including the failures:

| Date | Result | What changed |
|---|---|---|
| 10 Nov | 20/20 offline (5 cases) | first version, scripted model only |
| 18 Nov | 19/20 live | first live run: 8 tool calls on "commercial crude stocks", a word the publisher does not use |
| 18 Nov | 20/20, then 24/24 | search falls back to names holding most of the words; `get_spread` added |
| 18 Nov | 39/40 on both models | four reading tools added; both models over-searched before declining the carbon question |
| 18 Nov | 40/40 on both | search budget enforced in the tool |
| 18 Nov | 76/76 Haiku, 74/76 Sonnet | 22 datasets, arbitrage and percentile tools, 19 cases |
| 18 Nov | release blocked at 75/76 | the gate stopped a one-line prompt change that failed one live assertion |
| 18 Nov | 78, 79, 80 of 80 on Haiku | `get_surprises`, added after a visitor asked "what are this week's surprises" and the agent had to improvise. The unstable case was a bug, not noise: one run in six the model compared a Brent future with WTI spot and `get_spread` refused because one dataset writes "USD/bbl" and the other "Dollars per Barrel". Units are now compared on a normalised form |
| 18 Nov | 115/115 on Haiku | history sentences, what-if scenarios, the weekly watch and charts; 23 cases, a fifth evaluator |

## Release gate

`deploy.sh` is how a change to the code, the prompt or the model reaches the public service. The candidate must
pass the frozen-data suite with golden answers, the control run, the suite on today's lake with the scripted
model, and the suite on today's lake with the live model. Only then does the service restart. A live model does
not make the same choices twice (the same suite scored 78, 79, 80, 78 and 80 of 80 in five runs on one day), so
the live step is split: every number check must pass, and at most two behaviour checks (series
choice, tool budget) may miss. It blocked two releases on its first day. Trying another
model is the same command with `LIBRARIAN_MODEL=...`.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# No lake, no key, no cost: frozen data and a scripted stand-in for the model
.venv/bin/python run_evals.py --source fixture --gate --golden check
.venv/bin/python run_evals.py --source fixture --no-guard --expect-failures 2
LIBRARIAN_SOURCE=fixture .venv/bin/python serve.py          # the service, offline, on :8790

# Live model (any Pydantic AI model string)
export ANTHROPIC_API_KEY=...
.venv/bin/python run_evals.py --model anthropic:claude-haiku-5-5 --gate
.venv/bin/python ask.py "Is the Brent curve in backwardation?" --model anthropic:claude-haiku-5-5
```

The Parquet lake (`--lake /opt/energyscope/data`) lives on my server and is not in this repo. `--source flight`
makes the same calls over Arrow Flight with the public `energyscope-client` package and an EnergyScope API key
([sign up](https://energyscope.io/signup)).

The service is also the interface for other programs: `POST https://thelibrarian.energy/api/ask` with
`{"question": "..."}` returns the typed answer as JSON; `/api/ask/stream` returns the same as server-sent
events with one `tool` event as each tool starts.

## Files

```
es_agent/agent.py     the agent: instructions, fourteen tools, the output validator
es_agent/models.py    typed shapes: tool returns and the answer
es_agent/metrics.py   change and spread arithmetic, the number-tracing rule
es_agent/readings.py  curve, crack, arbitrage, scenarios, surprises, watch, seasonal, percentile, positioning; compute(source, key) rebuilds any of them
es_agent/verify.py    recompute an answer from the data (the Grounded eval and the live check)
es_agent/charts.py    the series behind an answer, for the page to draw
es_agent/memory.py    what a follow-up is allowed to remember
es_agent/sources.py   DataSource protocol: Parquet lake, Arrow Flight, frozen fixture, recorder
es_agent/scripted.py  offline stand-in for the model (Pydantic AI FunctionModel)
es_agent/clock.py     today's date, pinnable for the frozen data
run_evals.py          the suite, the gates, golden answers, fixture recording
serve.py              HTTP service: JSON and streaming answers, limits, live check, stats
deploy.sh             the release gate
fixtures/series.json  frozen copy of the series the suite reads (18 Nov 2026)
results/              eval reports and golden answers
```

## Pydantic AI features used

Typed tools (`@agent.tool`), structured output (`output_type`), dependency injection (`deps_type`,
`RunContext`), output validator with `ModelRetry`, `UsageLimits`, provider-agnostic model strings,
`FunctionModel` for offline runs, and pydantic-evals (`Dataset`, `Case`, custom `Evaluator`s, `MaxToolCalls`).

Notes from the build: in Pydantic AI 2.66+ a rejected output comes back as a `ToolReturnPart` on the output tool
with `outcome="retried"` (earlier releases used `RetryPromptPart`; `is_rejection()` handles both). The span-based
evaluators need tracing on: `logfire.configure(send_to_logfire=False)` plus `logfire.instrument_pydantic_ai()`
gives them a span tree with nothing leaving the machine. Year-ago changes on weekly series compare against the
last observation on or before the date 365 days earlier, since weekly dates drift by a day a year.

MIT licence.
