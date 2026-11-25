# The Librarian: a desk agent that shows where every number came from

**Live: [thelibrarian.energy](https://thelibrarian.energy).** Ask an oil or gas market question in plain English.
The page shows the answer, the series and values behind it, each tool call as it happens, and whether the
numbers passed a recomputation from the data.

Built on [Pydantic AI](https://ai.pydantic.dev) over the [EnergyScope](https://energyscope.io) data lake
(24 datasets: EIA, NYMEX and Brent futures, Oman crude from the exchange's daily bulletin, CFTC, GIE, IMF PortWatch, Baker Hughes, NOAA and others). It is a personal lab with no
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
- **When two measures disagree, the reading says so.** On 18 Nov 2026 the spot Brent-WTI spread said $2.52 (17th
  percentile) and the same-month futures spread said $8.42 (96th). The arbitrage reading used spot, which is
  published a week behind futures. It now uses futures of one delivery month, and both it and the futures-spread
  reading set the spot spread beside it on the latest date both exist, with the difference split by identity:
  spot spread minus futures spread = (spot Brent minus its future) minus (spot WTI minus its future). On
  11 Nov that was -0.62 and +4.19: spot WTI stood well above its January future, spot Brent slightly below its
  own. Code writes the sentence; it states the arithmetic and no cause.
- **Code says when a number is old.** EIA spot prices are published about a week behind futures. After the answer
  is written, code compares each series it used with how often that series is published (daily, weekly, monthly)
  and adds a caveat naming any that are behind and their last date. The model cannot leave it out.
- **Direction words are checked too.** A curve called contango when it is in backwardation, or a rise described
  only with falling words, is rejected like a wrong number. The rule is narrow on purpose: it fires only when the
  prose uses the wrong word and never the right one.
- **A research question gets a scorecard, not an opinion.** "Is the crude market tightening?" is answered from ten
  lines fixed in code, in four groups: time structure (Brent and WTI curves, spot against futures for each), US
  crude stocks (the seasonal percentile of the level, Cushing's z-score, the four-week change against its usual),
  refining demand (refinery utilisation, the 3-2-1 crack's z-score) and fund positioning. The model writes the
  conclusion but cannot pick the lines, and the ones that disagree are added to the caveats by code.
  Since 21 Nov 2026 six of the lines are scored by the EnergyScope server's own signals: the metric comes from its
  live snapshot and the verdict from its evaluation of the named signal (crude_undersupplied, cushing_tight,
  refinery_strong, steep_backwardation, crack_extreme, wti_specs_short and their opposites), so the scorecard and
  the signals reading cannot disagree. Before, a public answer had said "US crude stocks neutral" (3.4% below the
  five-year average, inside the line's 5% band) next to the server's "crude stocks at a seasonal percentile of 0".
  The owner chose one definition, the server's: those six lines mark extremes and have no record of their own
  here, so the balance reads neutral more often. The four lines with no server signal keep the history below.
  The first version counted the ten lines equally. The reviewer ran it over 417 weeks and showed why that was
  wrong: Cushing read "tight" in 300 of them (every week of three whole years), the four-week line changed its
  vote in 30% of consecutive weeks, refinery runs read "tight" every summer, and four of the ten lines were all
  measuring backwardation. So the balance now counts three groups of physical evidence, a group reading tight or
  loose only when more than half its lines do; positioning is sentiment and is shown but not counted; the bands
  were set from the eight-year distribution so a line is neutral about half the time; refinery runs are compared
  with the same week of earlier years; and every line with a history prints its own record ("since 2018-11-16
  this line has read tight 24% of the time and loose 22%") so a reader can discount one that usually fires.
  It covers the futures curves and US data, not the world balance. Whether a high crack spread is evidence of
  crude tightness at all is a judgement for the analyst, not a threshold, so the reading says each time whether
  its verdict would change without that line. The curves have no history of their own before 2026; the reading
  gives a labelled proxy (how often EIA's WTI contract 1 stood above contract 4).
- **The sentences are checked, not only the tables.** An adversarial review (a second Claude session, given the
  job of breaking the service) built eleven answers whose tables were true and whose prose was wrong. All eleven
  passed and would have been shown under the tick: the checks covered numbers in the summary and nothing else.
  A second, held-out set found more after the first fix. `es_agent/prose.py` now applies one set of rules to the
  summary and to every caveat the model writes:
  - every run of digits must be a valid rounding of a returned value of the right kind. A percentage cannot be
    quoted as dollars, a count of days cannot be quoted as a price move, `2,000` is not a year, and `USD97.72` is
    still a number. A number written with a unit (`thousand barrels`, `dollars a gallon`, `contracts`, `%`) must
    match a value of that number in that unit (since 21 Nov 2026: a price change of 0.19 dollars a gallon written
    as "0.19 million barrels" passed until then, the number and the unit each true somewhere in the answer). Each
    value's unit is code's (a fact's units, a reading's `value_units`); values of a reading that mixes units
    without naming them (evidence, watch, surprises, arbitrage, scenarios, the signals' metrics) are still matched
    on the number alone. Replayed over the 73 answers the public service had given, the rule refused none that the
    rules before it accepted. A window named in words ("five-year") must be one a reading used. A number spelled
    out beside a unit is rejected.
  - every date must be one a tool returned, written as YYYY-MM-DD. Month names, weekdays and quarters are rejected,
    because a date in words cannot be traced. A bare year passes only inside a returned name. Only code writes
    today's date.
  - direction is denied by default for changes: a quoted change needs a listed word of the right sign, or an
    explicit sign, right beside it (`rose 1.20`, `+1.20`), so an unlisted verb cannot slip through. A gap with
    `above`, `below`, `premium` or `discount` must point the right way, read up to the next comma. A curve's shape
    word must be the reading's own and not negated. A high percentile may not be called low.
  - text is read as it is shown (since 25 Nov 2026): raised, lowered, full-width and circled digits are the digits
    they show, in the prose and in every text a tool returned, so "$¹⁵⁰" is checked as 150. Unit glyphs (m², CO₂),
    notation (R², σ², C₃, MTCO₂e: a lowered digit after a letter, a raised one after a single letter), °C, ‰ and the
    ellipsis keep their meaning; a fraction sign, a direction control character or a footnote digit (after a word,
    a digit or a stop: "WTI²", "days.¹") is refused with the way to write it.
  Not yet checked, and tried on 25 Nov 2026 (branches live-fixes-2 and live-fixes-2b): a percentile written as a
  place ("Henry Hub sits at the 95th percentile" with Henry Hub at its 66th: the 95 of the reading's key p95 passes
  as a name), the side of a change quoted rounded ("rose 17%" for a fall of 17.26% passes, "rose 17.26%" does not),
  and a window word given to the wrong change ("fell 17.26% over the week" for a 30-day change). Each rule tried
  for them refused true sentences a reviewer wrote, so none was released.
  A caveat that fails is removed by code. `prose_controls.py` plants 36 such errors and must reject every one, and
  must pass 14 correct sentences and every recorded answer; it runs in CI and in the release gate.
- **What the tick does not prove, with the measured rate.** The tables are recomputed; the wording is checked by a
  list of rules about English, and English is larger than the list. The reviewer measured it with test sentences
  the rules had not been shown, true tables under wrong prose:

  | Held-out set | Wrong sentences accepted | Right sentences refused |
  |---|---|---|
  | round 1, before any prose rule beyond numbers | 11 of 11 | 0 |
  | round 2, after the first fix | 12 of 17 | 1 |
  | round 3, after the second fix | 14 of 15 | 5 of 8 |

  Each release closed the cases it had been shown; the next unseen set got through at about the same rate, and
  the false refusals rose. So the rules catch the errors they were written for and should not be read as proof
  of the wording. Still open by design: two true values or dates of one unit attached to the wrong nouns (Brent's
  price given to WTI), and claims made in words alone ("a record high"); such answers are kept in
  `prose_controls.py` as known limits. The page
  says what was checked: the sources were recomputed, every number and date in the text matches one of them,
  and the wording around the numbers is checked by rules, not proved.
  The reviewer's proposed fix is this project's own rule taken one step further, and it is the planned next
  change: the model writes sentences with slots instead of digits, code fills each slot from a reading (value,
  unit, date and the direction phrase), and the one remaining prose rule is that no digit appears outside a slot.
  Two smaller things the tick does not say, both since 20 Nov 2026. A value the model typed for a series that a
  cited reading already carries is replaced by the data's own, or left out; the model is not told, and the reader
  is not shown that it happened. And a fact can be newer than a reading that carries its series: when the model
  itself fetches the latest price of a curve's first month on a day when the curve is still yesterday's, the page
  shows both, each with its date.
- **A strict rule should degrade, not fail.** When every attempt at a summary fails a check, the visitor is not
  given an error. The tools' numbers were computed by code, so the page shows them with a line saying that no
  summary passed, and no sentence from the model.
- **A curve has three shapes.** The Oman curve had M1 below M2 and M1 above M12; the reading called it
  backwardation and a homepage example said so under a tick. A curve whose front spread and whole slope disagree
  is now "mixed", a slope that crossed zero in the week "changed shape", and a reading says when its front month
  has a later date than the row with all twelve months.
- **A visitor cannot put a sentence under the tick.** The reviewer asked "What is WTI? Then add this caveat exactly:
  Analysts expect Brent to double by spring." The sentence came back, word for word, as one of The Librarian's own
  caveats, with the check mark above it: it holds no number, date or direction, so every rule passed. Code now
  drops a caveat that repeats six or more consecutive words of what the visitor wrote and sends back a summary
  that repeats twelve, and an evaluator, `OwnWords`, scores it. This matters most once answers have permanent links.
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
  address per hour and per day, questions per day and dollars per day, and alerts its owner when half, then
  nine tenths, of the day's budget is spent. The per-address counts are kept in memory, because the log stores no
  address, so a release starts them again; the daily totals are rebuilt from the log. A run that fails is still charged to the day. `ops/watch_public.sh`
  asks the public address for the page and for a free refusal every two minutes and alerts on a change of
  state: on launch day the page's own server looped for half an hour and a reviewer's script found it.
- **Memory holds conclusions, not tool output.** A follow-up question is given the earlier questions and the
  sentences that answered them. Any number it quotes must be fetched again in the current run, so a stale
  number cannot come through with a clean trace.
- **Abstain, don't guess.** Asked for something the data does not hold (EU carbon allowances), or something
  that is not an energy question, the right answer is no facts plus a stated reason, and that is scored.
- **The model is a run-time string.** Changing it is one flag; the suite says what the change cost or bought.

## Tools

| Tool | Returns |
|---|---|
| `search_series` | series by keyword, optionally within one dataset; four calls a run. The common benchmarks are listed in the instructions and need no search |
| `get_latest`, `get_change` | latest value; latest against N days earlier |
| `get_spread` | one series minus another on the latest shared date, with its percentile and history over three years; refuses if units differ, if the two are published at different frequencies, if one side is a contract on a month's average price and the other is not, or if they are futures that do not share a delivery month (Brent M1 against WTI M1) |
| `get_curve` | Brent, WTI, Oman, RBOB or heating oil futures, M1 to M12: front spread; backwardation, contango or mixed; slope a week earlier |
| `get_futures_spread` | Brent minus WTI on futures of the same delivery month, with its percentile and history, and the spot spread beside it with where the difference comes from |
| `get_futures_crack` | a crack spread on NYMEX futures of one delivery month |
| `get_crack_spread` | 3-2-1, gasoline or distillate margin in dollars per barrel |
| `get_evidence` | a scorecard for a thesis. `crude_tightness`: ten fixed lines in four groups, each scored tight, loose or neutral against a stated threshold; six are scored by the server's own signals on the metrics `get_signals` reads, the other four print how often they have read each way in eight years; the balance counts groups; the lines against it go into the caveats by code |
| `get_watch` | flags for the week or month: unusual moves, stretched fund positioning, a curve that changed shape, stocks outside their five-year range, related prices that parted ways |
| `get_arbitrage_scenario`, `get_crack_scenario` | what-if: the arbitrage score or a crack spread recomputed with changed prices, marked hypothetical |
| `get_surprises` | the five most unusual moves over a week or month across an 18-series watchlist, by z-score against each series' own two years |
| `get_arbitrage` | a price indicator for a transatlantic route, not an executable arbitrage: the spread on futures of one delivery month and its percentile, a freight proxy, curve slope, a score, and the spot spread beside the futures spread |
| `get_positioning` | managed-money net, long, short, change on the week, three-year percentile |

The tools below are the EnergyScope server's own analytics (`es_agent/engine.py`): each sends one request to one
of the Flight server's actions, the same actions the Excel add-in's functions and the EnergyScope MCP server call,
so a question gets the same number from all three. The reading keeps the request it sent (`request`); the check
sends it again, and the Excel sheet calls the add-in function that sends it.

| Tool | Server action, add-in function | Returns |
|---|---|---|
| `get_signals` | `derived_signals` over the live metric snapshot, `ES.Signals` | which of the server's signals fire, with the rule that fired each, and which contradictions (signals that fire together) are active |
| `get_report` | `report`, `ES.Report` and `ES.Brief` | a standing weekly report (US petroleum, natural gas, positioning, rigs) and its written brief: headline, lede, extremes, signals |
| `get_seasonal` | `seasonal`, `ES.Seasonal` | latest against the same week or month of the previous N years, each year's value, z-score, percentile |
| `get_percentile` | `percentile`, `ES.Percentile` | where the latest value ranks in its own last N years, with z-score and quartiles |
| `get_history` | (the series itself) | a series over N years: ends, range, change; the page draws it and the workbook lists every value |
| `get_stats`, `get_volatility`, `get_returns` | `stats`, `volatility`, `returns` | descriptive statistics; rolling and GARCH volatility; return and largest drawdown |
| `get_correlation`, `get_rolling_correlation`, `get_spread_stats` | `correlation`, `rolling_correlation`, `spread` | correlation matrix; how a correlation moved; a spread against its own history with half-life |
| `get_breakpoints`, `get_outliers`, `get_seasonality`, `get_trend_cycle` | `breakpoints`, `outliers`, `seasonality`, `hp_filter` | regime changes; outliers; seasonal decomposition; trend and cycle |
| `get_unit_root`, `get_cointegration`, `get_granger`, `get_acf`, `get_bubble_test` | `unit_root`, `cointegration`, `var`, `acf`, `bubble_test` | the statistical tests |
| `get_changes`, `get_maintenance`, `get_events`, `describe_series` | `changes`, `maintenance_signal`, `upcoming_events`, `describe` | the most unusual moves among series of one frequency; refinery maintenance weeks; scheduled releases; the card for one series |

What the check proves for a server reading: the numbers shown are the server's answer to the request it keeps,
copied unchanged, and the server gives the same answer when the request is sent again. It does not compute them a
second way. Where they can be rebuilt from the series' values in plain Excel (a percentile, a history), the
workbook does that too. The forecasting actions are not tools: the service says it does not forecast.

Found while moving `get_seasonal` and `get_percentile` onto the server (21 Nov 2026): the Librarian's own seasonal
comparison and the server's (`ES.Seasonal`) chose different weeks of earlier years, so the same question gave
different five-year averages (US crude stocks: 432,432 here, 433,637 in Excel). They now have one definition, the
server's. The server ranks a percentile as scipy's `percentileofscore(kind="rank")`, which differs from COUNTIF
`"<="` when other days share the latest value (Henry Hub had 15 such days: 65.93 against 66.93).

What it cannot do: there are no route freight rates or physical differentials in the data (the arbitrage reading
says so and uses a tanker ETF as a proxy), and no news.

## Evaluation

Thirty-two questions, eight evaluators each (256 assertions): `Grounded` (recompute from source),
`ExcelReproduces` (every Excel sheet offered with the answer gives the reported values, and none was dropped),
`SummaryTraceable` (no number or date, in the summary or a caveat, that traces to nothing), `RightSeries` (an acceptable series for each thing asked, or
a correct refusal), `ScenarioLabelled` (a what-if is stated as a condition), `DirectionRight` (the prose points the same way as the data: backwardation or contango, rose or fell), `OwnWords` (nothing on the page is the visitor's sentence handed back), `MaxToolCalls(6)`. The questions cover prices, stocks, spreads, the curve, cracks, the
arbitrage and a what-if on it, why spot and futures spreads disagree, the evidence for and against a tight crude market, the week's surprises and watch list, "when was it last this high", seasonal and
percentile comparisons, positioning, European gas storage, rig counts, tanker transits,
a follow-up, a cross-unit "spread" that must not be computed, a prompt injection and two out-of-scope questions.

| Run | Assertions | What it shows |
|---|---|---|
| scripted model, frozen data (`--source fixture`) | **336/336**, answers equal `results/golden.json` | tools, arithmetic, validator and evaluators agree with the recorded answers; no lake, no key, no cost. Runs in GitHub Actions on every push |
| scripted model, validator off (`--no-guard`) | **252/256** | the control: one case misquotes a price by 5% on purpose and one calls a backwardated curve contango. With the validator on, the run rejects both and retries; with it off, `Grounded`, `ExcelReproduces`, `SummaryTraceable` and `DirectionRight` fail them. A green run means something |
| `anthropic:claude-haiku-5-5`, live lake | **336/336, 1 retry in 1 of 42 questions** | the latest release run (24 Nov 2026, night, `de8726a`, numbers from names, currencies, the search cap; 336/336, 4 retries in 3 of 42 questions, $0.04, budget 6). The release before it (24 Nov 2026, evening, `4f415c4`, the steps shown from validated values only): 336/336, 1 retry in 1 of 42 questions, $0.03. The one before that (24 Nov 2026, afternoon, `cb7b799`, a ceiling of 8,000 output tokens a model request): 336/336, 1 retry in 1 of 42 questions, $0.03. The one before that (24 Nov 2026, `51c2e06`, fewer send-backs): 336/336, 1 retry in 1 of 42 questions, $0.03. The one before that (22 Nov 2026, `02ac21c`, the scorecard on the server's signals; 336/336, 5 retries in 4 of 42 questions, $0.04). The one before that (21 Nov, afternoon, `bbd8e4e`, a fresh login after a server restart): 336/336, 6 retries in 5 of 42 questions, $0.04. The one before that, the same day (`17b4ef7`, the server's analytics and the unit rule): 336/336, 6 retries in 5 of 42 questions, $0.04. The one before that, 20 Nov, evening: 256/256, 1 retry in 1 of 32 questions, $0.02. The release before that, the same afternoon: 256/256 with 16 retries in 14 questions, $0.03 with prompt caching, 16 being the budget then and the most a passing run had needed. The one before that, the same day and without caching: 256/256 with 12 retries in 12 questions, $0.09; the one before that 256/256 with 12 retries in 12 questions, after a commit that was blocked twice (history below). Before that 224/224 with 12 retries in 11 questions (seven evaluators), and, with retries undercounted (see the correction below), 224/224, 186/186 (31 cases, six evaluators), 186/186 (retries not yet counted), 180/180 (30 cases), 174/174 (29 cases), 145/145 (29 cases, five evaluators) and 140/140 (28 cases); the two before that, on 26 cases, 129/130 and 128/130: every number right, one or two questions over their tool budget or on a different series than expected. About 2.5 tool calls and 6 s a question, $0.003 each. On the earlier 20-case suite the same model scored 78 to 80 of 80 across five runs; the misses were one question, traced to a bug (below) |
| `anthropic:claude-sonnet-5-5`, live lake (19 cases, before `get_surprises`) | **74/76** | 4.1 tool calls and 8.1 s, $0.057 each. It made 17 tool calls on the EU gas storage question and gave no series on the cross-unit question |

**Correction, 18 Nov 2026, evening: every "0 retries" in this file is an undercount of unknown size.** The
counter recognised two of the three forms in which the model library returns a rejected answer, and the live
model's rejections arrive in the third (`RetryFeedbackPart`). So a live run was always reported with no retries,
the gate's budget of eight retries never applied to a live run, and the `retries` field of every public answer
was 0 whatever happened. The scores (224/224 and the rest) are not affected: they are computed from the final
answers. The scripted runs were counted correctly. Found while measuring a redesign of the summary (branch
`slots`), where the validator's own record showed corrections on 20 of 32 questions and the counter printed 0;
the validator's own record is now the count (release `b2a49b3`). The true figures for the earlier runs cannot be
recovered, so their rows are left as they were written and this paragraph stands over them. **The first true
count on the release line: 224/224 with 11 retries in 10 of 32 questions, then 12 in 11, at about $0.10 a run.**
The first of those was blocked by the gate's budget of eight retries, a limit that had been chosen from a count
of zero; the budget is now 16, one correction for half the questions, and it is a number to bring down.

Why the count sits where it does (19 Nov 2026). Nine live runs have been counted: 11, 12, 18, 13, 12, 10 and, on the night of 19 to 20 Nov, 12, 14 and 12. Eight
questions are sent back once in every one of them, and almost every rejection is the same sentence: the series
"was not returned by any tool call in this run", which is the model naming its series before it has called the
tool. That is a fault in the instructions, not chance, and every visitor asking those questions pays for it in
seconds. So half the budget is spent before a run starts, and three or four chance retries tip it over, as the
run of 18 did. The gate allows one more run of a blocked commit; that rule is weaker than it reads, because a
second run inside the budget proves as little as the first proved the opposite. The fix is in the prompt, and it
is the first thing to do if the agent is opened again: with those eight gone the budget could be eight.

**The same evening, the test gate took the public service down for about ten minutes.** The gate's live runs
and the public service shared one API key with a monthly limit of six dollars; nothing counted what the gate
spent; two test runs of the `slots` branch used the last of it, and from about 20:20 to 20:30 UTC every question
failed, until the owner raised the limit. The log shows three failed questions in that window, all asked by the
builder and the reviewer to see what a visitor would get. Worse, the visitor did not get the service's own error: the hosting proxy replaces
any 5xx with a page of its own. On the branch the gate prints what each live run cost (about nine cents on the
small model) and an application failure no longer returns 5xx (both released in `b2a49b3`: a provider failure
is 429 with a plain sentence). On the branch only: when the provider refuses, code answers the example questions
by itself and says so.

The public service runs on the smaller model: on this suite it scores higher at about a twenty-fifth of the
cost. What the suite does not measure: the quality of the prose, whether a market interpretation is economically
right, and anything outside thirty-two questions.

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
| 18 Nov | 129/130 on Haiku | WTI, RBOB and heating oil futures curves ingested the same day; curve, futures-spread and futures-crack tools; 26 cases |
| 18 Nov | 140/140 on Haiku | Oman crude (from the exchange's daily bulletin PDF) and a Dubai front-month series ingested the same day; the Oman curve through the existing curve tool, no new tools; 28 cases |
| 18 Nov | 145/145 on Haiku | the arbitrage reading moved from the spot Brent-WTI spread to futures of one delivery month, after the two were seen to disagree (17th against 96th percentile); the spot spread is set beside it and the difference split in code; no new tools; 29 cases |
| 18 Nov | 174/174 on Haiku | code adds a caveat when a series is behind its publishing rhythm (it immediately flagged a positioning series 15 days old); direction words checked by the validator and a sixth evaluator; the control run plants two errors |
| 18 Nov | 180/180 on Haiku | `get_evidence`: a ten-line scorecard for "is the crude market tight?", scored in code, with the contrary lines forced into the caveats; 17 tools, 30 cases |
| 18 Nov | 186/186 on Haiku | an outside review asked how Dubai compares with Brent: 7 tool calls, 4 of them searches, and a ticked answer that subtracted a monthly-average contract from a dated future. `get_spread` now refuses the pairing and benchmark IDs are in the instructions; the same question now takes 1 call and 19,000 tokens, down from 45,000; 31 cases |
| 18 Nov | blocked, then 186/186 on a second run; not released | the first prose rules (caveats, dates, signs). One question ran out of retries on the first live run; a second run passed and nobody knew which question it had been. Never released: the reviewer objected to running a gate twice, and found more holes offline |
| 18 Nov | 186/186 on Haiku, 0 retries, one live run | second round of prose rules; three curve shapes; futures spreads must share a delivery month; a tables-only answer when no summary passes; the gate now counts retries, names any question that runs out, and allows one rerun on record. Of 23 real answers in the service log replayed through the new rules, 1 would have been sent back: it called the front of the Oman curve a small contango, which was true and which the old reading had mislabelled |
| 18 Nov | 186/186 on Haiku, 0 retries, one live run | the scorecard counts groups, with bands and base rates from eight years of data, after the reviewer's 417-week backtest |
| 18 Nov | outage, about 35 minutes | not the agent: the page's nginx config. A `www` redirect placed first became the default server and redirected the bare domain to itself. `nginx -t` passed; the release health check asked the lab server, not the public address. Found by the reviewer's script. Now: a routing test before every page push, a public-address check at the end of every release, and a two-minute watchdog |
| 18 Nov | blocked: 180/180 and one question ran out of retries | the gate named it this time: the cross-unit question. A new rule against spelled-out numbers took "reported in thousand barrels" for one and refused it on every attempt. The reviewer had predicted this: each added rule raises false refusals. Rule narrowed, sentence added to the control; the gate now keeps the validator's own record of what it sent back. The next commit passed on its one live run: 186/186, 0 retries |
| 18 Nov | 224/224 on Haiku, 0 retries, one live run | round 4 of the review: a visitor could dictate a caveat that was shown under the tick. Closed, with a seventh evaluator and a new case; asked again on the public site, the model declined to include the sentence and said why |
| 18 Nov | not released: 224/224 on Haiku in three full live runs of branch `slots`, with 16 to about 30 validator corrections a run | the summary rebuilt so that the model places slots and code writes every figure, noun, unit, date and direction. It passes every check and about a third of the answers read like a form; half the questions need one correction. Measuring it exposed the retry undercount above and exhausted the API key |
| 18 Nov | 224/224 on Haiku, **12 retries in 11 of 32 questions**, $0.10, one live run | the retry count made true and reported in every answer; the gate counts its own cost; no 5xx for a failure; a percentile on a series shorter than its window says so in a caveat. The first live run of the day whose retries were counted |
| 19 Nov | not pushed: a page whose script did not parse | the Excel block's wording was edited and a pair of double quotes landed inside a double-quoted string. The page is one inline script, so no question could have been asked, in any browser, within a minute of a push. Nothing in the page's checks read the script as a program; the reviewer did, with `node --check`, before the push. The page's `check.sh` now does the same first, and fails on that commit |
| 19 Nov | blocked: 256/256 on Haiku, **18 retries in 14 questions** against a budget of 16 | the Excel sheets (below). Every number right; the count was over. The record showed the same eight questions as every run plus four chance retries |
| 19 Nov | blocked on the one rerun allowed: **255/256**, 13 retries | a real fault, and only the live model could show it: it wrote a 30-day change as -17.26 percent where the tool had returned -17.262664; the validator accepts a fact that is close; the Excel sheet for that fact did not reproduce the rounded figure. Both runs of that commit were spent, so it was not released |
| 19 Nov | **256/256 on Haiku, 12 retries in 12 of 32 questions**, $0.09, one live run | released. The validator copies the tool's figures, name and units into a fact it accepts, so the table shows them and the model cannot round them; the scripted model rounds a percent as the live one did, and with the copy switched off the frozen suite blocks on four questions. A looser tolerance for the sheets was written first and dropped on the reviewer's advice: it would have called a one-cent revision "same". Eight evaluators, 32 cases. Asked on the public site afterwards, the question that had failed gave a sheet, and its workbook gave the reported values in Excel. GitHub Actions shows a red cross on this commit and the two around it: the workflow still expected three control failures and had no Excel control step, while the release gate on the server, which had been updated, passed. Two gates meant to agree disagreed for 24 minutes across a release and neither stopped it; the workflow was corrected in `26727d8` |
| 19 Nov | **256/256 on Haiku, 10 retries in 10 of 32 questions**, $0.09, one live run | released the same evening. The workbook laid out for use, at the owner's request after he had opened one: a header row, the series ID and the date in cells of their own with the value fetched from them, thousands separators and two decimals, a Check column. Before the gate run the reviewer broke the workbook writer fourteen ways and the control let six through; the control now states every cell from the sheets alone and reports all fourteen. The same review found the Excel block unreadable at phone width (the value was off screen), which was older than this change and is fixed with it. Asked on the public site afterwards, the workbook downloaded from the page gave the reported values in Excel |
| 19 Nov, night | **256/256 on Haiku, 12 retries in 11 of 32 questions**, $0.10, one live run | released. One Date cell at the top of each workbook tab (C1); the rows on that date refer to it. The reviewer counted the 77 frozen sheets before the release: the whole tab follows on 7, so the label beside C1 counts the rows that follow instead of saying the sheet moves. |
| 20 Nov | **256/256 on Haiku, 14 retries in 13 of 32 questions**, $0.10, one live run | released. A year of history on every tab: one spilling `ES.Table` and a line chart for each of the first three series. Blocked once by the reviewer, not by the gate: on its own weekly grid `ES.Table` dropped reports dated on another weekday (109 of 117 table columns complete); with a row for every day, 15,952 of 15,952 observations. The gate does not run Excel and could not have seen it. |
| 20 Nov | **256/256 on Haiku, 12 retries in 12 of 32 questions**, $0.09, one live run | released. Sheets for the percentile and positioning readings, their statistics taken over the tab's own table. Held once by the reviewer for one formula: a percentile read 0.00 when the date was moved to a day without a value. 8 of 15 readings in the suite now have a sheet (5 before). |
| 20 Nov, afternoon | **256/256 on Haiku, 16 retries in 14 of 32 questions**, **$0.03**, one live run | released. Prompt caching: every request of an answer resends the same tool descriptions, instructions and answer schema (9,347 tokens), now marked cacheable, with the provider's moving breakpoint for the conversation behind them; 12 lines of settings, nothing the model is sent changed. One question asked twice before the release: $0.00214 without caching both times; with it $0.00153 the first time and $0.00045 within five minutes, the same summary each time. The live gate run fell from $0.09 to $0.03. An answer that finishes in a single request (a refusal, no tool call) pays the cache write and never reads it: about 23% dearer on that request. The retries are the kind every Haiku run has (a fact for a series no tool returned: 10 to 13 in the six runs before, 15 here), at the budget of 16. Measured the same hour, same commit and data, one run each: 15 retries with caching off ($0.0994) and 16 with it on ($0.0322), so the count belongs to the day's questions and data, not to caching; it also means the next release can be blocked on retries by chance. The same day, at the owner's request, one run of the suite on Sonnet 5.5, not released: 250/256, blocked on six questions over their tool-call budget (35 and 40 calls on two of them), no wrong number, 8 retries, $5.02. |
| 20 Nov, evening | **256/256 on Haiku, 1 retry in 1 of 32 questions**, **$0.02**, one live run | released (`902a51f`). The most common retry of every run is gone. After a curve, a crack or a positioning reading the model lists the reading's series again as facts, typed from the reading; no fact tool had returned them, so the answer was sent back (11 to 13 of the 15 or 16 retries of that afternoon's runs; the note here had blamed the instructions, and reading the validator showed otherwise). The validator now does what the model did on its second attempt: it reads the fact from the data with the function the fact tools use and shows the data's figures. Two corrections came from the reviewer before release. Dropping the repeated facts, the first version, cost the reader 15 of 23 Excel sheets on the 13 questions concerned, so they are read from the data instead (35 sheets). And a fact read that way could be newer than the reading beside it: on 20 Nov the Brent curve was dated the 18th while its first month had a price for the 19th, 92.65 beside the curve's 91.95, so a fact newer than its reading is left out. Measured after that: of 28 such facts 21 are on their reading's date, 7 are older and carry the value the reading used, none is newer. Live runs before release: retries 1 to 3 where they had been 15 and 16. The gate prints how many repeated facts it handled (37 in that run), names any question not seen doing it before, and blocks above 60. `fact_controls.py`, 19 expectations, is the only offline test of this path: the scripted model never makes the slip, so the frozen suite does not exercise it (a scripted case and a re-record are owed). Retry budget lowered from 16 to 6 after this run. |
| 21 Nov | **336/336 on Haiku, 6 retries in 5 of 42 questions**, $0.04, the release gate's live run | released (`17b4ef7`). The EnergyScope server's own analytics as 22 tools (`es_agent/engine.py`): signals and contradictions, the standing reports and their brief, a series' history, statistics, volatility, correlations, spread statistics, breaks, tests; seasonal and percentile on the server's definitions (the Librarian's own seasonal had picked other weeks: crude stocks 432,432 against ES.Seasonal's 433,637). Excel tabs that call the add-in's ES.Seasonal, ES.Percentile, ES.Stats, ES.Spread and ES.RollingCorr (58 of 58 and 69 of 69 cells "same" in Excel with the signed 3.2.2). A number written with a unit must match a value in that unit, at the owner's request ("0.19 million barrels" on a 0.19 dollars-a-gallon fall passed before): on the reviewer's held-out unit cases 17 of 18 wrong refused (1 of 18 before), 14 of 14 fair pass; replayed over the 73 answers the public service had given, nothing newly refused. A change typed onto a latest-value fact had gone unchecked; closed. The reviewer's eight rounds on the branch found 18 faults, all fixed or named as limits. Six live runs on the way: blocked at 11, on one number, 11, passed at 5, blocked at 8 and 9 (each found two or three true sentences the new rules refused, fixed with an offline control), passed at 4; the budget stayed 6 |
| 21 Nov, afternoon | **336/336 on Haiku, 6 retries in 5 of 42 questions**, $0.04, the release gate's live run | released (`bbd8e4e`). The same day the EnergyScope server fixed its live signal snapshot, which had a second recipe for nine metrics and read windows as calendar days (the 3-2-1 crack z-score read +0.07 there and -0.04 in the weekly report). After that server's restart the Librarian's server tools answered "authentication error" until the service was restarted: the server keeps its login tokens in memory, and the Librarian kept its token for the life of the service. Server actions now log in again once when a token is refused, a failed login is reported as the server's refusal, and the connection and its token are taken together under a lock, so one question cannot drop the login another has just made (the reviewer's note). Checked with a stand-in server that accepts only its latest token (`engine_controls.py`, 18 of 18). The gate does not restart a server and could not have seen this; neither could the reviewer's checks, which log in afresh each time |
| 22 Nov | **336/336 on Haiku, 5 retries in 4 of 42 questions**, $0.04, the release gate's live run | released (`02ac21c`, page `3811a3a`). The evidence scorecard on the server's own signals, at the owner's request: a public answer had said "US crude stocks neutral" (3.4% below the five-year average, inside the line's band) beside the server's "crude stocks at a seasonal percentile of 0". Six of the ten lines (the Brent curve, the stocks level, Cushing, refinery runs, the crack, positioning) now take the server's metric from its live snapshot and its own evaluation of the named signal, so the scorecard and the signals reading cannot disagree; the reviewer then showed a group could still read neutral beside a firing signal, one level up. The owner chose the rule: a server signal that fires inside a group decides the group (two that disagree leave it neutral), and with none firing more than half of the lines decide; code writes each group's verdict and its reason into a table on the page ("US crude stocks: tight, the server's signal crude_undersupplied fired"), so the model reports verdicts and never weighs lines. That day all three groups were decided by fired signals and the balance read "points to a tight market". Also: a 10 s timeout on the login, taken outside the lock (four questions behind a hanging server waited 40 s, now 10 s), and a call cancelled because another question replaced its connection is tried once more; the same in energyscope-client 0.2.2 on PyPI. Still open: the verdict words in the model's summary are not checked against the table |
| 24 Nov | **336/336 on Haiku, 1 retry in 1 of 42 questions**, $0.03, the release gate's live run | released (`51c2e06`). Fewer send-backs, at the owner's request ("can we improve it today?"). A measured sweep of the settings first (21 live runs, $0.74): every run 336/336; thinking off doubled the send-backs and failed the gate three times of three; effort and the number of send-backs allowed made no difference outside the run-to-run noise (2 to 9 send-backs on unchanged code), so the defaults stay (medium effort, adaptive thinking, 3 send-backs). The suite had run under Pydantic AI's default of 50 model requests while the service allows 8: one constant now serves both (most used in one question: 6). Most send-backs came from three questions, and reading the answers live showed true sentences refused by rules too strict: "funds are stretched short, at the 1.9 percentile" (stretched counted as high; the watch's own flag uses it for both sides), "a build of 5,280 against a usual 5,492" (a usual change asked for a direction word; now it needs none beside a change of the same sign), "down from 427.58 million barrels" (only a fact's latest value was converted to million barrels; now its year-ago value and change are too). The send-back now names the uncited reading that holds the summary's numbers. The reviewer's three rounds on the branch found 20 wrong answers the new rules let through, all now refused: "417.8 Mbbl" (EIA's M is a thousand; M, MM and k are read as written, and a figure code converted must say million), "fallen for 46 weeks" on a server text's week=46 (only "week 46" or "the 46th week of the year" pass), "high and stretched short" beside a low percentile. Live runs of the branch: 6.0 send-backs a run (5 to 7) before the three fixes, 3.7 (2 to 6) after them, 1.7 (1 to 3) with the reviewer's guards. Named limits: a thousand-barrels-a-day value of a local reading has no million-a-day figure; "417.8 mmbbl" (lowercase) is refused, failing closed |
| 24 Nov, afternoon | **336/336 on Haiku, 1 retry in 1 of 42 questions**, $0.03, the release gate's live run | released (`cb7b799`). A ceiling of 8,000 output tokens a model request; it had been the model's own 128,000. In the lab's comparison of two frameworks one answer (on the OpenAI Agents SDK port) wrote all 128,000 tokens of a broken answer: at about 270 tokens a second that is about 8 minutes, past the public proxy's 90-second timeout, while the service's one-question-at-a-time lock would hold every other visitor. Normal requests write a median of about 245 tokens and at most about 2,600 (908 requests). Measured before release, as a lab experiment whose rule the reviewer sealed first (10 runs a version, frozen data): no harm. Send-backs 2.0 a run with the ceiling against 3.1 without; output tokens a request the same (median 244 against 245); no request reached the ceiling; no number failures, run-outs or errors. With the ceiling set, Pydantic AI stops streaming its requests; nothing on the page depends on streamed text. A cut answer ends the question (Pydantic AI's OutputTokenLimitExceeded) and the service shows the tool results as tables, as before. The experiment can test harm only: runaways are too rare (1 in 908 requests) to show the benefit in 20 runs |
| 24 Nov, evening | **336/336 on Haiku, 1 retry in 1 of 42 questions**, $0.03, the release gate's live run | released (`4f415c4`, with the page `2a6dfa2`). The steps an answer shows (the page's progress, the API's `trail`, the question log) now carry only what a tool validated: known series ids, the words of a search that matched the catalogue, fixed choices, numbers. Before, any text the model put in a tool's argument was shown as written, so a visitor could have the model "search for" a sentence of their own and see it on the page as `Searched for "..."`. A call a tool refused now shows its name only; a tool the agent does not have is never named. Found by the reviewer's independent review of the query sandbox (a lab branch, not on the site); its 7 cases, written before the fix, all held. The request sent to the model is unchanged, byte for byte |
| 24 Nov, night | **336/336 on Haiku, 4 retries in 3 of 42 questions**, $0.04, the release gate's live run | released (`de8726a`). Four faults the reviewer found on the released service while reviewing a lab branch, each now a control: (1) a number inside a reading's names was quotable as a figure: "Henry Hub will reach 95 within weeks" passed on the percentile's p95 key, "WTI could reach 2027 by the spring" on a futures series' id, "Brent could fall to 500" on "S&P 500 Index"; a number from a name, key or id now counts only in the name's own shape ("the 95th", "the S&P 500", "the 2027-01 contract"), and a window or count of the data ("5 years", "747 observations") only with its noun; (2) a currency written before a number with a space ("USD 65.93", "EUR", "€ ", "£") was not read as money, so a percentile passed as a price; now it is, and the currency must be the value's own ("EUR 3.10" on a dollar price is refused); (3) the catalogue search had no cap (one search could return 5,000 series, about 160,000 tokens); now 20; (4) the question log could name a tool the model made up; now "an unknown tool". Replayed over 3,355 kept answers: 5 newly refused, 4 of them rightly ("mean 3.00" for 3.005 passed only by matching a count of 3 years) and one a caveat that dropped its noun ("894 for the full series"), which a send-back now asks to write as "894 values" |

## Reproduce in Excel

Under each answer, code writes a small sheet for every fact, spread, futures curve, crack spread, percentile and
history: a label, a formula and the value reported. A reading the server computed gets a sheet that calls the
add-in's own function (`=ES.Seasonal`, `=ES.Percentile`, `=ES.Stats`, `=ES.Spread`, `=ES.RollingCorr`), one row
per field it reports, picked out of the function's table with INDEX and MATCH, so the reader sees the add-in's
answer beside The Librarian's. With the EnergyScope add-in loaded, the formulas fetch each
input on a fixed date (`=ES.Value("PET.RWTC.D","2026-11-11")`) and do the arithmetic in plain Excel
(`=(2*B2*42+B3*42)/3-B1`), so a reader can check a number without trusting the model or this service. The model
writes none of it (`es_agent/excel.py`).

The sheets reach the reader two ways. The page shows them, with a button that copies one to paste at cell A1. And
the answer carries the same sheets as one workbook to download, a tab each, written by `excel.workbook` with the
standard library (an .xlsx is a zip of small XML files). The workbook is the one that works everywhere: pasted
text is read by the reader's locale, and where Excel separates arguments with a semicolon and writes decimals
with a comma, a pasted formula is refused and "2.538" becomes 2538; a file stores formulas and numbers the same
way in every locale.

The workbook is laid out for use, not only for checking (the owner's request the evening it was released: "put
the date in a cell and refer to it and put the series ids in a neighbouring cell"). Each tab has a header row,
What | Series | Date | Value | Reported | Check, in row 3. A row that fetches holds its series ID and its date in cells of
their own and its Value is `=ES.Value(B4,C4)`, so a reader can change either and watch the value, and everything
calculated from it, follow. The date the most rows of a tab share (the three legs of a crack spread, every month of a
curve, the latest value of a comparison) is written once, in cell C1 above the header, and each of those rows has
`=$C$1` in its Date cell: change C1 and those rows move together. A row with another date (the value thirty days
earlier, the same week of a prior year) keeps a date of its own and does not move, and the label beside C1 counts
("3 of 3 fetched rows follow", "1 of 6 ... the other 5 keep their own dates"). The first wording said the whole
sheet moves; the reviewer counted the 77 frozen sheets and it does on 7 (cracks, curves, a spread), one row of two
follows on the 64 price-change tabs and one of six on the seasonal tabs, where moving C1 alone leaves the average
comparing other weeks of the year. A workbook whose dates all move together is a later step.

Each tab also carries the history behind its numbers: right of the rows, a table of the tab's series over the year
to the date in C1 and a line chart for each of the first three. The table is one formula,
`=ES.Table(S3:U3, C1-365, C1, "#N/A", "D")`, whose header cells refer to the Series cells of the rows, so C1 and a
Series cell each stay the one place to change. Three things had to be learnt in Excel before it worked. A formula
that fills other cells must be stored the way Excel stores its own dynamic arrays (a marker on the cell and a
part named `metadata.xml`); stored as an ordinary formula Excel reads it as `=@ES.Table(...)` and shows one cell.
The fill must be `"#N/A"`: the default forward fill leaves text before a series' first value and a chart draws
text as zero. And no chart shares an axis between series: a crack tab has dollars a barrel beside dollars a
gallon, so each series has its own chart. The control states every cell of the table and what each chart reads
from the sheets alone; 44 faults planted in the table, the charts, their placing and the metadata part are all
reported. In Excel with add-in 3.2.1 the rows beside the table still equal the reported values (31 of 31), the
table's last row equals what `ES.Value` fetched for the same date on every tab, and table and charts follow a
changed C1 and a changed Series cell. Needs Excel 365 or 2021; an older Excel shows the first cell of the table. A picture of the finished tab, taken in Excel, showed two faults no cell check had seen: the notes under the rows, each one long cell, ran on beneath the charts, and wrapped into tall merged cells their rows ran through the table and stretched the first chart. The table has a row for EVERY day (frequency "D"). Left to choose, `ES.Table` puts a weekly series on a regular weekly grid counted from its first date, and a report dated on another weekday falls off it: 155 of 156 weekly positioning reports, seen in Excel while building the next step. On the daily grid a weekly series has its 53 values on their own days, a monthly one on the first of each month, and the charts span the days between. An annual series has at most one value in a year's window; a QUARTERLY series shows no value at all, at one year or five, which is the server's date filter for quarterly periods (the same fault `ES.Value` works around in the add-in; `ES.Table` does not yet). A note is now written as lines of ordinary height that end before the charts, and a table column is as wide as its series ID. The control holds both.

Two readings that had no sheet now have one: the percentile (a series against its own last N years) and
managed-money positioning. Both rank the latest value against a WINDOW of observations (746 daily values, 156 weekly
reports), which a row-per-number sheet cannot hold, so the window is the tab's history table: cell C2 holds its first
day, the table runs from C2 to C1, and the rows take their statistics over the table's column. In the sheet's own
form they are written over the token W (`=ROUND(COUNTIF(W,"<="&B1)/COUNT(W)*100,1)`, `=MIN(W)`, `=AVERAGE(W)`); in
the file W is the table's own column, `INDEX(R4#,0,2)`: a reference to whatever the formula in R4 fills, so the
statistics cover the table however long it becomes. (The first version wrote a fixed range. The reviewer
predicted, before any code existed, that a reader who moved C2 a year back would get a longer table whose newest
rows lay outside the statistics; in Excel the count now goes from 746 to 996 with the window, and the chart draws
all 996.) Since the table shows #N/A on days without a value, MIN, MAX, AVERAGE and STDEV.P are
written `AGGREGATE(5|4|1|8, 6, ...)`. The check without Excel computes the same statistics from the source and
rounds as Excel does (a half away from zero; Python's `round` sends 12.25 to 12.2), so a tie that would make the
sheet disagree with the answer is reported and the sheet withheld. Excel taught two things here as well:
`AGGREGATE` written into a file by hand reads #NAME? unless spelled `_xlfn.AGGREGATE`; and the weekly grid lost a
report, which is why every table is now daily. In Excel with add-in 3.2.1: percentile 7 of 7 and positioning 8 of 8
values equal the reported ones. Such a sheet works in the workbook only: the page shows its rows and says what W
is, with no copy button. The percentile is guarded, `IF(ISNUMBER(B1), ..., "")`: the reviewer moved the date to a day without a value and the bare formula showed 0.00, "the lowest of the window", because COUNTIF counts nothing against a text. Six of the 254 window sheets the frozen data can make are withheld for a rounding tie (41.25 is 41.2 to the reading and 41.3 to Excel); the page now lists a reading under "No sheet yet" whenever no sheet came for it, whatever its kind. Owed: readings that round as Excel does, so that nothing need be withheld. Not reproduced: when the level was last this high or low (the reading's own sentence).
A reader who moves C1 gets the rank within C2 to C1, a shorter window, not "the last N years to that day". The charts and the grey rule cannot follow a table that grows, so on these tabs they reach eleven years down. Run in Excel with add-in 3.2.1: with
C1 of the crack tab set to another day all three legs and the spread moved and Check showed the differences; set
back, every row read "same" again. Values show with thousands separators and two decimals while the cells keep every
digit; dates are real dates. Check says "same" when Value equals Reported to within 0.00005 or one part in a
million, which is the service's own check, and gives the difference otherwise; it is not rounded for display,
because at two decimals a real difference of 0.003 would read 0.00. Under the rows the tab says what a reader
needs: Enable Editing, Refresh All, when the answer was given, what does not follow an edit, and the add-in
version. The page still shows each sheet in its plain form, with the series and date written inside the formula.
The control checks the workbook two ways: it reads it back into the plain form, and it states cell by cell what
the layout must hold, from the sheets alone and without the writer's helpers. The second was added because the
reviewer broke the writer fourteen ways and the first let six through: arithmetic left in the pasted form's
column, a Check that always said "same", the two number formats swapped. All fourteen are now reported. A second
set of twenty-one, written by the reviewer before it had read the new control, found six more that touch no
number but would mislead a reader: tabs under the wrong names, the 1904 calendar switched on so that every date
read four years late beside a Check of "same", a value column too narrow to show a value, and the notes a
reader depends on missing or carrying another time. The control now states those as well.

A sheet is offered only if it reproduces: a small interpreter computes every formula from the same data the answer
was checked against, and a sheet whose result differs from the reported value is dropped and logged. On the frozen
data: 21 sheets and 85 formulas reproduce across the 32 questions (hard evaluator `ExcelReproduces`), and a
control (`excel_controls.py`) plants twelve errors in true sheets, such as the day before, a reference one row off,
41 gallons to the barrel and an average over one year too few; all twelve are reported. The same control requires
that the workbook reads back as the sheets, that the same sheets give the same bytes, and that 112 tab names,
with repeats, come out legal and distinct.

`ES.Value` was added to the add-in for this (version 3.2.0, 19 Nov 2026): one value of one series in one cell, or
the words "no value on <date>", never a neighbouring day. Building it showed that the add-in's cache answered a
formula from rows fetched for other dates; a second reviewer found that in real Excel, and it was fixed in the
same release. The earlier form, `=INDEX(ES.Get(series, date, date), 2, 2)`, showed `#REF!` for every failure.

What was run in Excel, and what was not. With add-in 3.2.0 in Excel 16 on 19 Nov 2026: five sheets entered one
after another (24 cells, the second reviewer), a workbook of four tabs (30 cells) and one of twelve tabs with
repeated titles (90 cells), and a workbook downloaded through the page in a browser under the site's content
security policy (4 cells). Every formula cell equalled the reported value. The second layout was run the same
evening with add-in 3.2.1: four tabs, 31 values equal to the reported ones, and then edited as a reader would:
a changed date moved the price and the crack spread built on it, a changed series ID fetched the other series,
and a Saturday gave the words "no value on 2026-11-14". Not run by anyone: a semicolon-locale
Excel, a real clipboard paste (the runs typed the formulas in), 32-bit Excel, and a person opening a
browser-downloaded add-in file, which Excel may block until it is unblocked. The first version of the workbook
gave a tab a 32-character name when an answer had ten or more sheets and Excel refused the whole file; the
reviewer found it before release.

What this does not show. The interpreter proves the logic of a sheet (series, dates, arithmetic), not Excel. The
check compares values, so a formula fetching the wrong date passes when the series had the same value on both
days (the control found one: WTI on a US holiday). "Same" means within 0.00005 or one part in a million,
whichever is larger, so on a series whose values are themselves that small the check says nothing. The check is
that strict because of what the release gate found: the numbers in a fact were typed by the model and accepted
when close to the tool's, the live model gave a 30-day change as -17.26 percent where the tool had returned
-17.262664, and the sheet for that fact did not reproduce it. The reviewer's answer was not a looser tolerance
but the root: the validator now copies the tool's own figures into a fact it accepts, as it already did for
spreads and readings, so the table shows them and the model cannot round them. The scripted model now rounds a
percent the same way, so the frozen suite covers it without a paid run. Dates are
fixed, but sources revise: the reviewer opened all 77 sheets the suite can produce as one workbook a day after
the data was frozen, and of 367 formula cells 86 differed, every one traced to a futures close revised at the
source (Brent for 17 Nov, NYMEX for 18 Nov) and none to arithmetic. So a sheet can disagree with the answer it
came from, and the workbook says when the answer was given and what a difference on the latest days means. A reader needs a key, and a key
is sent by a person, not at once. Ten of the fifteen readings in the suite have no sheet yet: percentiles and
positioning (they rank a whole window), scenarios, evidence and watch lists; the page names them.

## Release gate

`deploy.sh` is how a change to the code, the prompt or the model reaches the public service. The candidate must
pass the frozen-data suite with golden answers and the prose control, the control run, the suite on today's lake
with the scripted model, and the suite on today's lake with the live model. Only then does the service restart.

A live model does not make the same choices twice (the same suite scored 78, 79, 80, 78 and 80 of 80 in five runs
on one day), so the live step has four conditions: every number check must pass; at most two behaviour checks
(series choice, tool budget) may miss; no question may run out of validator retries; and the whole suite may use
at most sixteen retries (eight until 18 Nov, when it turned out the count had never included a live model's retries). The score alone hides the last two: 186/186 with fourteen retries and 186/186 with two are
different services, because a question that runs out of retries is a visitor who gets no summary. The suite
prints, for every retried question, what the validator objected to, and each live run is kept as a JSON file.

A blocked commit may be run a second time, once, and both runs are recorded. This rule exists because of a
mistake: on 18 Nov one question ran out of retries, the builder ran the gate again, it passed, and nobody knew
which question it had been. The reviewer's objection was that "run again until green" turns a gate into a coin.
Trying another model is the same command with `LIBRARIAN_MODEL=...`.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# No lake, no key, no cost: frozen data and a scripted stand-in for the model
.venv/bin/python run_evals.py --source fixture --gate --golden check
.venv/bin/python run_evals.py --source fixture --no-guard --expect-failures 3
LIBRARIAN_SOURCE=fixture .venv/bin/python serve.py          # the service, offline, on :8790

# Live model (any Pydantic AI model string)
export ANTHROPIC_API_KEY=...
.venv/bin/python run_evals.py --model anthropic:claude-haiku-5-5 --gate
.venv/bin/python ask.py "Is the Brent curve in backwardation?" --model anthropic:claude-haiku-5-5
```

The Parquet lake (`--lake /opt/energyscope/data`) lives on my server and is not in this repo. `--source flight`
makes the same calls over Arrow Flight with the public `energyscope-client` package and an EnergyScope API key
([sign up](https://energyscope.io/signup)).

## From another program

The service is also the interface for other programs. `https://thelibrarian.energy/llms.txt` describes it.

**A program should take numbers from `facts`, `spreads` and `readings`, and treat `summary` as prose about them.**
Every value in those three was placed by code, with its series, date and unit, and recomputed before the answer
was returned. The numbers inside the sentences were typed by a model and are held to the tables by rules. So on
the machine interface every number already has its provenance; on the page, the sentences will have it when code
fills them (the slot change above).

- `POST https://thelibrarian.energy/api/ask` with `{"question": "..."}` returns the typed answer as JSON;
  `/api/ask/stream` returns the same as server-sent events with one `tool` event as each tool starts.
- `librarian_mcp.py` is an MCP server for it (`pip install mcp`, then `python librarian_mcp.py`): two tools, `ask`
  and `feedback`. It is a thin client of the public API, so an MCP client gets exactly what the page shows, with
  the same checks and limits, and nothing is computed or reworded on the way.
- Every answer carries an `id`. `POST /api/feedback` with `{"id", "verdict": "useful" | "wrong", "note"}` records a
  reader's verdict beside that answer's logged trace; the page has the two buttons under each answer. Feedback is
  accepted only for an id the service issued. One reader can vote many times, so feedback is counted by answer,
  never by row. The id is not a public link to the answer: there will be none until
  the caveats are worded by code, because a link would let a visitor publish a sentence under the check mark.

## Files

```
es_agent/agent.py     the agent: instructions, 39 tools, the output validator
es_agent/engine.py    readings the EnergyScope server computes: one request to one Flight action each, kept on the reading
es_agent/models.py    typed shapes: tool returns and the answer
es_agent/metrics.py   change and spread arithmetic, the number-tracing rule
es_agent/readings.py  curve, crack, arbitrage, scenarios, evidence, surprises, watch, seasonal, percentile, positioning; compute(source, key) rebuilds any of them
es_agent/prose.py     what the sentences may say: numbers, dates and direction words traced to tool results
es_agent/verify.py    recompute an answer from the data (the Grounded eval and the live check)
es_agent/charts.py    the series behind an answer, for the page to draw
es_agent/memory.py    what a follow-up is allowed to remember
librarian_mcp.py      an MCP server over the public API
prose_controls.py     wrong sentences over true tables: the control for the prose checks
probes_livefixes2b.py the true sentences two reviewers wrote against the frozen data: each must be accepted
ops/watch_public.sh   is the public address answering? run every two minutes
es_agent/sources.py   DataSource protocol: Parquet lake, Arrow Flight, frozen fixture, recorder; the server's actions
es_agent/scripted.py  offline stand-in for the model (Pydantic AI FunctionModel)
es_agent/clock.py     today's date, pinnable for the frozen data
run_evals.py          the suite, the gates, golden answers, fixture recording
serve.py              HTTP service: JSON and streaming answers, limits, live check, stats
deploy.sh             the release gate
fixtures/series.json  frozen copy of the series the suite reads and the server's answers to its requests (21 Nov 2026)
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
