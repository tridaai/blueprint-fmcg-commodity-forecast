<p align="center">
  <img src="https://trida.ai/logos-rounded/trida-rounded.png" alt="Trida AI" width="96">
</p>

# Blueprint — Commodity Price Forecasting & Procurement Intelligence Agent

A working prototype of the forecasting desk a large food buyer in India actually
needs. The fictional buyer is **Verdanta Foods**, whose trading desk buys wheat,
basmati rice, soybean, groundnut, chili, cumin and coffee at national scale and
today works entirely by phone — no forecasting tool, no sentiment feed, no way to
ask "what happens to soybean if the tariff stays?" and get an answer it can defend.
This blueprint builds that answer as a governed agent: **the forecast is computed
by a stated statistical engine in code, every number carries its driver
contributions and its measured backtest accuracy, and the language model only
explains, structures sentiment and parses scenarios.** It is decision support for
a procurement desk — it never places a trade and never publishes a number a named
human has not approved.

> **Work in progress** — this blueprint is built and passing its automated test and eval gates, but it has not yet finished hands-on local testing, and its companion blog post is not yet published. Expect changes. This notice comes off when both are done.

## The laws (enforced in code, as the rounds land)

1. **Forecasts are computed, never narrated.** A stated statistical engine produces
   every figure: trend/seasonal baseline + per-driver contributions, each a
   recorded line. The LLM explains; it never originates a price.
2. **Every forecast carries its measured accuracy.** A rolling-origin backtest
   scores the engine per commodity and horizon; a degraded forecast is flagged,
   never hidden.
3. **Sentiment is a scored pack with provenance.** Each item is data — source,
   date, commodity, direction, strength — and the index is computed in code.
4. **Shocks are declared events, not silent adjustments.** The event registry
   holds each shock with its stated transmission; a shocked forecast shows the
   event as separate contribution lines.
5. **Scenarios are pinned forks.** A what-if parses into named, bounded levers;
   a scenario is a new run pinned to its base forecast, and becoming the desk's
   official view takes a named human approval act.
6. **Dashboards are assembled from artefacts only.** A prompt becomes a stated
   dashboard spec whose every figure traces to a computed artefact.
7. **Thin data means wide bands + named gaps.** Coffee-class commodities
   forecast with honest intervals and the missing drivers named — never fake
   precision.

## Product lineage

This blueprint follows the shapes of the group's own products — pattern
references, with all code here original to this repo:

- The data layer — mandi prices, arrivals, stocks, trade, weather, policy and
  sentiment in one ontology — is the **Farmioc DataStore** shape
  ([farmioc.com](https://farmioc.com)).
- The forecast + price surface for buyers is the **Farmioc PriceHub** shape,
  extended with contributions, sentiment and scenarios.
- Prompt-to-dashboard is the **AgentSQL** pattern (natural language → governed
  query → dashboard) on a **TridaPad**-shaped surface, from Trida Labs
  ([tridalabs.com](https://tridalabs.com)).

## The stack

Python 3.12 · FastAPI · Pydantic · LangGraph state machines (ingest → compute →
explain → scenario → human gate → publish) · PostgreSQL 16 as the system of
record (monthly range partitioning, Timescale-ready) with SQLite for the
offline dev/test profile · DuckDB for backtesting and analytical scans ·
numpy/pandas + statsmodels primitives under the stated in-repo forecast
engine · model port with an offline deterministic default and fail-closed
hosted profiles (Anthropic, Amazon Bedrock, NVIDIA NIM) · uv with exact pins
and a frozen `constraints.txt` · multi-stage non-root Docker.

## What Round 1 builds

- **A gold-by-construction dataset generator** — one deterministic, seeded pass
  builds ~3 years of daily series (2023-01-01 .. 2025-12-31) for seven
  commodities across 14 market series: modal price, arrivals, stock level,
  import/export flow and a weather index, with planted seasonality on each
  commodity's harvest calendar, two planted trend breaks, one planted tariff
  shock (soybean, Jun 2025), one planted export ban (basmati rice, Sep-Oct
  2024) and a planted chili drought. Everything planted is restated in a
  **generator manifest** the eval gate grades against.
- **The sealed grading truth** — the generator also emits the next 90 days of
  every series. Those rows live behind a separate truth store; the forecast
  package is structurally forbidden from reading them (graded by test + eval).
- **Coffee as the thin-data case** — reports Tue/Fri only, a planted three-week
  reporting disruption in Aug 2025, and no stock or trade-flow drivers at all:
  named gaps in the manifest, never zero-filled rows.
- **The store port** — insert-only observations (a duplicate write is an
  error, not an overwrite), the event registry and the manifest, behind one
  port with SQLite and Postgres dialects; numbered migrations with a runner.
- **The model port** — offline deterministic default; anthropic / bedrock /
  nim profiles that refuse loudly until configured.
- **A LangGraph ingest workflow** — generate → persist → verify as explicit
  graph state; re-loading the same seed verifies and stops.
- **The operations API** — `/series`, `/events`, `/manifest`, `/coverage`,
  `/catalogue`, `/health`, `/readiness`, with structured JSON logs and a
  request id on every response.

## What Round 2 adds

- **The forecast engine v1** — for any (commodity × market) series, a 90-day
  daily forecast by a stated method, recorded in full on the artefact:
  a trend + day-of-year-seasonality **baseline** (OLS on log price), plus
  **per-driver contributions** — arrivals pressure, stock cover, trade flow,
  weather — each estimated by a stated regression on history and projected
  forward as its last observed pressure decaying at its measured
  persistence. Contributions are attributed sequentially in a stated order,
  so **baseline + contributions + events equals the forecast total exactly,
  to the paisa**, and a re-performance verifier re-adds every day and
  recomputes the artefact's content address: a tampered line or total fails.
- **Honest intervals** — P10/P90 from rolling residual quantiles, propagated
  by the residuals' own persistence and widened by a measured **sparsity
  multiplier** (√(calendar days ÷ observed days)). Coffee's multiplier is
  1.89 against wheat's 1.08, its missing drivers (stock, imports, exports)
  are named on the artefact, and its realised band is wider — thin data
  gets wide bands and named gaps, never borrowed precision (Law 7).
- **Sealed-window discipline** — the engine estimates on history only. An
  `as_of` inside the sealed grading window is refused unless the caller
  explicitly invokes the backtest path (the harness lands in R3); the
  engine structurally cannot read the sealed rows.
- **The events slot** — forecasts carry a declared-event adjustment line,
  zero in R2; the event registry fills it in R5 so a shock shows as its
  own contribution instead of being absorbed silently (Law 4).
- **Draft → official is a human act** — a forecast is born a draft; making
  it the desk's official view takes a recorded approval by a named
  approver with a named role (placeholders refused, a second approval
  refused). Runs are idempotent: the artefact is content-addressed.
- **Figure-verified commentary** — the model port drafts commentary over
  the artefact; every decimal figure in the draft must appear in the
  artefact or the draft is refused wholesale and nothing is stored.
- **Surfaces** — migration 0002 (forecasts, approvals, commentaries);
  `POST /forecasts/run`, `GET /forecasts/{id}` (+ `/contributions`,
  `/verify`, `/approval`, `/commentary`), `POST /forecasts/{id}/approve`;
  the demo walks a wheat forecast from run to official view, and coffee's
  honest band.

## What Round 3 adds

- **The backtest harness** — rolling-origin evaluation over observed
  history: monthly origins through 2025 (first-of-month, Jan–Oct), the
  engine run at each origin through its `via_backtest` seam and scored
  at 7/30/90 days against the realised prices in the observations
  table — never the sealed store. The grid is stated in a versioned
  **accuracy pack** (origins, horizons, ledger window, degraded bar)
  and bounded: 135 engine runs, 405 stored results. Origins the
  engine cannot yet state its method for are recorded as skips with
  the refusal named — coffee's first five origins (it needs 250
  reporting days; it has 209 in January) — never silently dropped.
- **Scored days, counted exactly** — a result's days are the days in
  the horizon window carrying a realised observation (Sundays are
  excluded, never imputed); per day, error, absolute error, absolute
  percentage and band coverage are summed as the primitive record,
  and MAE / MAPE / bias / coverage derive from those sums by stated
  formulas. A verifier re-performs every figure from the artefact
  alone, and the hand-computed fixtures in the tests pin the
  arithmetic.
- **The accuracy ledger** — one record per series × horizon, pooled
  day-weighted over the most recent 6 origins (never a mean of
  means). Rebuilding the ledger re-performs the aggregation from the
  result artefacts of record; a verifier detects any drift between
  the ledger and its results.
- **Forecasts carry their accuracy (Law 2)** — a run pins the
  ledger's current records onto the forecast as a self-contained
  snapshot (part of its content address). The pack's bar is pooled
  MAPE above 5.0%: exactly one series crosses it — **chili at
  Guntur, the dataset's noisiest series over its planted drought,
  at 5.16% (30d) and 5.06% (90d)** — and its forecasts are stamped
  **degraded** on the artefact, in the accuracy read, and in their
  commentary. The flag is the ledger's judgement copied, never
  re-judged by a caller, and no read path offers a view without it.
  A series with no coverage yet reads **unmeasured**, named on the
  artefact — never a blank.
- **The sealed-boundary dry run** — the eval gate additionally
  scores the boundary forecasts (wheat and coffee at the last
  history day) against the sealed future it hands to the harness's
  scoring function: forward MAPE under 3.6% at every horizon,
  coverage 1.00 — the engine's forward accuracy is measurable end
  to end, and product code still never reads the truth store.
- **Surfaces** — migration 0003 (backtest results, accuracy
  records); `POST /backtests/run`, `GET /backtests` (+ `/{id}`),
  `GET /accuracy`, `GET /accuracy/{commodity}/{market}/{horizon}`,
  `GET /forecasts/{id}/accuracy`; the demo runs the harness and
  prints the ledger; the HTTP harness checks the whole surface.

## What Round 4 adds

- **The sentiment corpus as data** — 583 planted news/policy items
  across the seven commodities (migration 0004), each with a generic
  source label, a date and a headline, loaded as a dataset artefact
  with a digest-stamped manifest. The corpus is deliberately uneven,
  like the real desk's feed: five commodities carry a rich weekly
  stream, groundnut is sparse (12 items), coffee thinnest (4). What
  each item was planted to *mean* — its intended direction and
  clarity — is grading-side truth behind its own store; the scoring
  code never reads it (an isolation scan enforces that, mirroring
  the truth store's law).
- **Extraction through the model port** — the offline profile
  performs the **sentiment pack's** stated lexicon rule (27 phrases
  across policy / supply / demand / weather / trade, read from the
  buying desk's side of the price); hosted profiles produce the same
  structured reading through structured outputs, fail-closed as
  usual. Every reading is a content-addressed `SentimentExtraction`:
  direction on the stated ladder (−1 / −0.5 / +0.5 / +1 — there is
  no classified zero), strength by the stated formula, per-aspect
  signed sums. An item the rule cannot classify is **unclassified
  with the reason on record** — signalless, or signals cancelling —
  never forced into a direction. Graded against the planted intent,
  the extraction is exact on all 583 items: every clear item's
  direction, strength, score and aspects, and every ambiguous or
  signalless item landing unclassified.
- **The weekly index, computed in code** — per commodity × ISO week,
  the strength-weighted, age-decayed mean direction over the
  trailing 14 days (half-life 7 days), with aspect sub-indices by
  the same formula. A week whose window holds no classified item
  has **no index — absent, never zero-filled**. Every stored index
  re-performs exactly from the stored extractions.
- **The forecast gains the driver — where it is earned** — the
  engine treats the index as one more driver (estimated by the same
  residual regression, future path = last index value at its
  measured persistence) only when the pack's estimation floors are
  met: ≥200 index-covered price days, spanning ≥500 calendar days,
  the newest covered day within 28 days of the forecast date. Wheat,
  basmati, soybean, chili and cumin clear the floors; groundnut and
  coffee do not, and their forecasts carry a **named
  `not_estimable` sentiment line** — zero contribution, the failing
  floors stated, `sentiment_not_estimable` in `missing_drivers` —
  the coffee pattern applied to sentiment. The decomposition
  identity (baseline + lines = P50) holds exactly either way.
- **Sentiment is cited, never asserted** — commentary may state a
  sentiment direction only with the item ids behind it, and a claim
  verifier checks the pairing against the stored extractions before
  a draft may be stored: an uncited claim, a claim citing another
  commodity's or an unclassified item, or a direction the cited
  readings do not support refuses the whole commentary. The offline
  drafter's reading sentence carries the strongest agreeing items
  behind the latest index.
- **Surfaces** — migration 0004 (items, extractions, indices,
  corpus manifest, grading-side intent); `POST /sentiment/run`,
  `GET /sentiment/manifest`, `GET /sentiment/items` (+ `/{id}` with
  its extraction), `GET /sentiment/extractions`,
  `GET /sentiment/index/{commodity}` (+ `/{week}`),
  `GET /sentiment/verify`, `GET /forecasts/{id}/sentiment`; serve
  loads the corpus and runs the pipeline at boot; the demo grades
  the extraction against the intent and walks the estimated and
  not-estimable lines; the HTTP harness checks the whole surface.

## What Round 5 adds

- **The governed event registry** — shocks exist only as
  declarations (migration 0005): a named analyst act records each
  event's class from the **event pack** (tariff change, export
  restriction, import policy, weather shock, logistics disruption,
  demand shock), its commodity scope, its effective window (open
  while still in force), and its **stated transmission** — which
  driver it moves, the estimated peak log-price effect, and the
  named basis it rests on (an announced measure, a measured
  analogue, or a desk estimate, stated concretely). Placeholder
  declarers, channels outside the class, zero peaks and inverted
  windows are refused. Declarations are content-addressed and
  insert-only; a correction is a new declaration, never an edit.
  The system never "detects" an event from a price move — the
  registry is declared, the measurement layer only checks it.
- **Historical events, checked against measurement** — the
  dataset's planted shocks are seeded from the manifest as
  historical entries (the 2025 oilseed tariff at +0.16 log through
  the import channel, the 2024 basmati export ban at −0.11 through
  the export channel, the 2025 chili drought at +0.036 through the
  weather channel), and every entry's claimed transmission is
  **verified against history** by the pack's stated measurement:
  the seasonally-matched year-over-year ratio of ratios per
  market, medianed across the commodity's markets, judged inside
  the pack's [0.5, 1.5] band. All three planted claims verify
  (measured ×1.110, ×0.918, ×1.045). A claim that disagrees — a
  forged +0.60 over the real tariff window, a wrong-sign claim —
  is flagged **`transmission_unverified` on the event's face**,
  in every read. An event whose window cannot be measured yet
  reads `not_measurable`, named, never estimated.
- **Shocked forecasts show separate lines** — the engine's events
  slot is filled by the registry: the pack's stated path rule
  (3-day ramp to the peak inside the window, linear decay over
  the event's stated decay days after it closes) becomes a per-day
  log path, and each event telescopes into the decomposition as
  **its own named line** — the events line records every event's
  log path and INR contribution path, the verifier checks the
  per-event paths compose the day adjustments, and the
  decomposition identity (baseline + lines = P50) holds exactly.
  Outside an event's window and decay tail there is no line: a
  hand-computed fixture (wheat, +0.10 over ten January days,
  decay 10) grades the path day by day — ramp thirds, peak,
  decay tenths — in the tests and the eval gate.
- **Honestly wider bands on shocked days** — on any day an event's
  adjustment is non-zero, the forecast's interval growth factor is
  multiplied by the pack's stated widening factor (×1.25), and
  only on those days: graded exactly, by comparing a shocked
  run's log band width against the plain run's, day by day.
- **The what-happened view** — per event and market, the measured
  price path against a no-event baseline (the engine's baseline
  method fitted on pre-window history only, projected through the
  window and its decay tail): the tariff's review at Indore shows
  78 observed days, mean effect ×1.078, peak exactly the planted
  step. A window that has not begun, or has too little history
  before it, reads not measurable with the reason named.
- **Surfaces** — migration 0005 (both dialects); `POST
  /market-events` (the analyst act), `POST
  /market-events/seed-historical`, `GET /market-events` (+
  `/{id}`, each read carrying its transmission verdict), `GET
  /market-events/{id}/verify`, `GET
  /market-events/{id}/impact`, `GET /market-events/verify`
  (registry re-performance), `GET /forecasts/{id}/events`; serve
  seeds the planted shocks at boot; forecasts run through the API
  carry the registry wired in; the demo seeds, verifies, reviews
  and then declares a new February tariff and re-forecasts with
  and without it; the HTTP harness checks the whole surface.

## What Round 6 adds

- **The bounded lever catalogue** — a scenario may move only what
  the **scenario pack** (versioned data) states: arrivals shift
  (±40% of the level), stock-cover change (±30 days), trade-flow
  shift (±60%), weather-index deviation (±0.5), a sentiment index
  override (within [−1, 1], and only where the base's sentiment
  line is estimated), a declared event from the registry, an
  extension of an event the base already applies (≤ 90 days), or
  a hypothetical event of an event-pack class with a stated
  transmission (peak within ±35%). A request outside a bound is
  refused with the bound named — the catalogue is the desk's
  whole vocabulary, never a suggestion.
- **Plain-language intake, shown back verbatim** — a typed
  what-if ("what if arrivals drop 10% and the tariff stays
  another month?") goes through the model port: offline, the
  pack's stated deterministic grammar; hosted, the same lever
  schema via structured outputs, failing closed. The result is a
  content-addressed `ScenarioRequest` artefact carrying the exact
  clauses and the levers they became. A clause the catalogue
  cannot state is refused with the clause named — never silently
  reinterpreted, never improvised.
- **Pinned forks through the same machinery** — a `ScenarioRun`
  pins (base forecast, request, author). The fork is a fresh
  engine run on the base's own estimation with the levers applied
  to the driver **input paths** — a level shift becomes a
  log-standard-deviation shift by the pack's stated conversion
  (arrivals −10% becomes ln(0.9)/sd(log arrivals) on the arrivals
  path; stock cover ±N days becomes N/sd(stock level); the
  sentiment override replaces the sentiment path's start). The
  baseline is shared, the decomposition identity holds on the
  fork exactly, and the fork's accuracy attachment is the
  ledger's, like any desk run. The fork lives on the run; it is
  never inserted into the desk's forecast record, and the base
  artefact is never mutated — the eval gate compares its stored
  payload byte-for-byte before and after all scenario activity.
  Scenario events (an extension, a hypothetical) are
  scenario-local artefacts in the events slot; the registry is
  never written by a scenario.
- **An exact diff** — base vs fork, per driver per day, computed
  in integer paise: the per-driver differences plus the events
  difference re-add to the P50 difference on every day, and the
  view reports driver totals and the P50 difference at 7/30/90
  days. Telescoping shows honestly: moving arrivals also moves
  the stock and weather lines' attributed shares, and the diff
  shows those too.
- **The adoption gate** — a scenario becomes the desk's adopted
  view for its series only by a named adopter's act with a named
  role (placeholders refused, as at the approval gate). Adoption
  supersedes the series' previously adopted scenario by link;
  adopting an adopted or superseded scenario is a state error.
  Every read is labelled: the base forecast is the desk's
  forecast, an unadopted scenario reads `scenario_draft`,
  the adopted one `adopted_scenario`, a superseded one
  `superseded_scenario` — a draft can be shared, but no read
  dresses it up as the desk's view.
- **Surfaces** — migration 0006 (both dialects); `GET
  /scenarios/pack`, `POST /scenarios/requests` (typed intake),
  `POST /scenarios/requests/structured`, `POST /scenarios`
  (run), `GET /scenarios/{id}`, `GET /scenarios/{id}/diff`,
  `GET /scenarios/{id}/verify`, `POST /scenarios/{id}/adopt`,
  `GET /scenarios/adopted/{commodity}/{market}`; the
  `fmcg-agent-scenarios` CLI with the same verbs (parse, create,
  run, show, diff, verify, adopt, adopted); the demo walks the
  typed what-if from parse to adoption; the HTTP harness checks
  the surface end to end. What the studio still cannot do: a
  lever outside the catalogue, a scenario on a series whose
  named gaps leave a lever nothing to move (coffee's stock
  lever is refused, naming the missing line), and adoption by
  anyone but a named human act.

## What Round 7 adds

- **Prompt-to-dashboard** — a plain-language prompt ("wheat
  forecast at delhi and soybean sentiment and the coffee stock
  position") goes through the model port — offline, the
  **dashboard pack's** stated deterministic grammar; hosted,
  fail-closed — and compiles to a stated, content-addressed
  **dashboard spec** artefact: panels, each bound at ask time to
  the artefacts behind it. The pack states the whole vocabulary:
  five panel kinds (forecast paths, measured accuracy, the
  sentiment index, declared events, scenario diffs), the head
  rule that picks a series' current forecast, the reference-market
  default, and the subjects the catalogue honestly cannot state.
  A clause asking for a figure that does not exist — rainfall,
  a standalone stock or arrivals figure, an unknown commodity —
  becomes a **named gap panel** on the spec and on the rendered
  page: never an invented number, never a silently dropped
  request. R6's hypothetical discipline carries into the grammar:
  a scenario panel exists only when the prompt names the scenario,
  by id or as a series' adopted scenario.
- **Artefact-only rendering, verified before it exists** — a spec
  assembles by re-resolving every panel to the current head of
  its artefact family and reading figures off the artefacts. The
  candidate page then passes an assembler-level verifier —
  panels re-resolve and compare figure for figure, each family's
  own verifier re-performs the artefacts behind them, the stored
  HTML must re-render byte-for-byte — before it is stored. One
  mismatch refuses the whole dashboard; nothing partial exists.
  Specs save as **named views** (a name pointing at a spec, not a
  copy) and re-run against fresh data: an identical re-assembly
  returns the stored artefact, and a re-run whose inputs have
  superseded carries a **computed diff** — figure changes,
  binding supersessions, gap↔rendered flips.
- **The provenance appendix** — every dashboard page carries an
  appendix, and every figure in it walks figure → artefact id →
  input facts → source + date, terminating at stored facts:
  observation series (with row count and last date), sentiment
  items, event declarations, the dataset manifest. The verifier
  re-checks every walk against the store; a figure without a
  complete lineage cannot render — the dashboard refuses,
  naming the figure. This is the trust feature that lets a desk
  head defend a number in a meeting.
- **The morning desk board** — one opening screen, itself a
  content-addressed artefact derived from artefacts only:
  degraded series first (chili/Guntur appears), then pending
  gates (draft forecasts awaiting approval, draft scenarios
  awaiting adoption), active declared events with their verdict
  on the row's face, forecast changes between a series' two most
  recent run dates, and named data gaps (coffee's, on its head
  forecast). Ranked exceptions, not a chart gallery; every row
  links to its artefact id; a clean series does not appear.
- **Surfaces** — migration 0007 (both dialects); `GET
  /dashboards/pack`, `POST /dashboards/ask`, `GET
  /dashboards/specs` + `/{id}`, `POST /dashboards/specs/{id}/save`,
  `GET /dashboards/views`, `POST /dashboards/specs/{id}/assemble`,
  `GET /dashboards/assemblies/{id}` + `/html` + `/appendix` +
  `/verify`, `GET /board` + `/board/html`; the
  `fmcg-agent-dashboards` CLI with the same verbs (ask, specs,
  save, views, assemble, show, appendix, verify, board,
  board-html); the demo walks prompt → dashboard → appendix and
  the morning board. What dashboards still cannot do: a panel
  kind outside the pack's catalogue, a figure no artefact
  carries, and a "clean" read of a degraded series — the flag
  rides on every surface, API included.

## What Round 8 adds

- **Buy-window signals** — per series, one computed call —
  **buy_now / phased / wait** — derived in code from the pinned
  head forecast under a **versioned signal pack** that states
  every threshold: the 30-day horizon, the rise/fall bars the
  path must clear against spot (the last observed modal price),
  and the band width beyond which one commitment is too
  exposed. The decision table is the pack's, applied in order,
  and the **reasoning lines ride on the signal's face** — the
  inputs, the bars, what decided it. Hard rules, graded by the
  eval gate: a **degraded series can never produce a strong
  buy** (the pack caps it at phased; an unmeasured series is
  capped the same way), a series inside a **declared
  shock/event window has that event named on the signal**, the
  forecast's named missing drivers carry onto the signal, and
  every signal **re-performs exactly** from its pinned forecast
  artefact — the verifier recomputes the whole call and
  compares field for field. A signal places no trade;
  procurement execution is out of scope by design, and every
  artefact says so.
- **Coverage & exposure planner** — the desk enters **its own
  requirement plan** (tonnes by month, its stated opening
  stock) as a **desk-entered artefact**: labelled desk-entered
  on every surface, with a lineage terminal class of its own —
  provenance walks resting on the desk's statement terminate
  at `desk_entered`, never at market data, and the planner's
  verifier counts desk facts on every figure's walk (desk
  figures rest on the desk fact alone; market figures contain
  none; mixed figures carry exactly one). Against a plan, the
  planner computes **coverage days** at the plan's own burn
  rate, allocates stock first-in-first-out by month, prices
  each month by the planning pack's stated month rule (the
  pinned forecast's mean daily P50 over covered days; months
  past the horizon are **named, never valued**), and values the
  **uncovered exposure paise-exact**, re-performed by its
  verifier. Three stated **purchase options** (cover now /
  staged / phased) are ranked **only** by the pack's criteria —
  expected cost, then adverse (P90) cost, then name — each
  carrying its schedule arithmetic. The series' buy signal is
  pinned as context (an option running against it says so) but
  never enters the ranking. Where the desk has **adopted a
  scenario** (R6), an assessment may price on the adopted fork
  instead — pinned, badged **scenario-based**, never blended
  with the official view.
- **Surfaces** — migration 0008 (both dialects); `GET
  /signals/pack`, `POST /signals/compute`, `GET /signals` +
  `/{id}` + `/{id}/verify`; `GET /planning/pack`, `POST
  /planning/plans`, `GET /planning/plans` + `/{id}`, `POST
  /planning/plans/{id}/assess`, `GET /planning/assessments` +
  `/{id}` + `/{id}/verify`; the `fmcg-agent-signals` and
  `fmcg-agent-planning` CLIs; the **morning board gains a
  signals section** — actionable signal rows (buy_now and
  phased; a wait is the absence of an exception) appended after
  the dashboard pack's sections under their own heading, ranked
  strong buys first, every row backed by its signal artefact.
  One deliberate non-fit: signals do **not** become dashboard
  panels — the dashboard pack's panel catalogue is closed
  versioned data, and a signal is a computed call, not a
  catalogue figure; it surfaces through its own API, CLI and
  the board instead. The demo walks a rising series to its buy
  signal with reasoning, the degraded chili series with its
  state named on the signal's face, and a requirement plan to
  exposure + ranked options on both price bases.

## What Round 9 adds

- **Subscriptions** — the desk's own stated watch, entered as
  **desk-entered artefacts** in the plan idiom: a named
  subscriber and role, catalogue scope (commodities, markets),
  the alert kinds watched and a **severity floor**. A change
  is a new artefact **superseding by link**; re-entering the
  standing statement is a no-op. There is no silent edit and
  no code config.
- **Alerts, derived never authored** — a sweep derives alerts
  from artefacts of record under a **versioned alert pack**
  and stores only the ones that do not exist yet. An alert's
  content address is its (subscription, kind, triggering
  artefact), so **a crossing fires exactly once**, however
  many times the sweep runs. Five kinds: **buy signals**
  (severity from the pack's value map, raised to critical
  when a buy_now's drift clears the critical drift bar);
  **event windows** (one alert per declared event per
  subscription, however many signals reference it — the
  event-window dedup); **price moves** (crossings *computed*
  from the observation series: a stated 7-day window move
  clearing the pack's bar where the preceding window did
  not — one crossing per excursion, pinned to the pair of
  observations that decided it); **accuracy degradation**
  (a ledger record over the degraded bar) and **coverage
  collapse** (a record under the pack's coverage floor),
  both raised **once per open episode** — a still-degraded
  replacement record does not re-fire, and the episode
  reopens only when a named act closes the alert as
  resolved or the record itself recovers. A trigger dated
  before the subscription was entered never raises. Signals
  matching no subscription raise nothing and are **counted
  in the sweep's own summary** — absence is a reported
  outcome, not an oversight. Every alert carries the
  signal-only scope note on its face: no trade is placed.
- **Acts and the escalation clock** — acknowledgement and
  closure are **attributed insert-only acts**; closure must
  name a reason from the pack's stated vocabulary. An
  alert's state is **never stored**: reads fold the acts
  plus the pack's escalation windows — an unacknowledged
  alert climbs the stated ladder (subscriber → desk head →
  procurement lead) as each window fully elapses, an
  acknowledgement **stops the clock at the rung it had
  reached**, and escalation is provable from the acts, not
  a background job's say-so. An alert over a superseded
  signal is **marked superseded on read**, never quietly
  dropped. A **daily digest** artefact carries exactly its
  subscriber's alerts for its date — re-derived from the
  stored alerts, never assembled by hand. The verifier
  re-performs every alert against a fresh derivation, field
  for field, and grades the episode discipline across the
  set. Degradation badging itself rides on the accuracy
  artefact as it already did (board rows, dashboard badges)
  — R9 adds the subscriber notification, not a second badge.
- **Surfaces** — migration 0009 (both dialects); `GET
  /alerts/pack`, `POST /alerts/subscriptions`, `GET
  /alerts/subscriptions`, `POST /alerts/sweep`, `GET
  /alerts/crossings`, `GET /alerts` + `/{id}` +
  `/{id}/verify`, `POST /alerts/{id}/acknowledge`, `POST
  /alerts/{id}/close`, `POST /alerts/digests`, `GET
  /alerts/digests/{id}`; the `fmcg-agent-alerts` CLI. Alerts
  do **not** become dashboard panels — the R7 catalogue
  stands closed, by the same reasoning as signals in R8.
  The demo enters two watches, sweeps, and walks one alert
  acknowledged in time (its clock stops) and one left
  untouched (escalated to the procurement lead a month
  later), closing on a digest and a whole-set
  re-performance.

## Honest status

- **Built and gated in R1:** the spine, generator + manifest, store port +
  migration 0001 (both dialects), truth store, model port, ingest workflow,
  API reads, demo, harness, eval gate v1 (data integrity: planted shock/ban
  bands, seasonality, coverage completeness, coffee sparsity, truth
  isolation, manifest agreement — all zero-tolerance).
- **Built and gated in R2:** the forecast engine (stated decomposition,
  contribution lines, sparsity-honest intervals, sealed-window refusal,
  events slot), migration 0002, the re-performance verifier, the approval
  gate, figure-verified commentary, forecast API surfaces, demo + harness
  walks. Eval gate v2 adds zero-tolerance counters for decomposition sums,
  contribution signs on the planted harvest window, coffee gaps/widening,
  tamper detection, sealed-window acceptances, commentary figure
  violations and the events slot.
- **Built and gated in R3:** the backtest harness (accuracy pack as
  versioned data, monthly 2025 origins, 405 scored results, coffee's
  five unstatable origins skipped with the refusal named), the accuracy
  ledger (pooled over the recent 6 origins, re-performable), forecast
  accuracy attachments (degraded stamped exactly on chili/Guntur at
  30/90 days; unmeasured named before coverage exists), the
  sealed-boundary dry run in the eval gate, migration 0003, backtest +
  accuracy API surfaces, demo + harness walks. Eval gate v3 adds
  zero-tolerance counters for the grid, hand-computed metric fixtures,
  result/ledger re-performance, degraded-flag correctness and
  suppression, unmeasured naming and the sealed check; the truth
  isolation scan now covers the backtest package too.
- **Built and gated in R4:** the sentiment pack (lexicon, direction
  ladder, index formula and estimation floors as versioned data), the
  planted corpus (583 items; intent grading-side only, isolation-scanned),
  extraction through the model port graded exact against the planted
  intent on the whole corpus, the weekly index (absent-never-zero,
  re-performable), the forecast sentiment line (estimated for the five
  rich-corpus commodities; a named not-estimable line for groundnut and
  coffee), claim-verified commentary citations, migration 0004,
  sentiment API surfaces, demo + harness walks. Eval gate v4 adds
  zero-tolerance counters for extraction-vs-intent, index
  re-performance, per-commodity contribution state as planted, accepted
  claim violations and intent isolation.
- **Built and gated in R5:** the event pack (classes, channels,
  bases, path rule, measurement rule, widening factor as versioned
  data), the governed registry (content-addressed declarations,
  insert-only, named-analyst act with refusals), historical seeding
  from the manifest with every planted transmission verified
  against the seasonally-matched measurement (forged and
  wrong-sign claims flagged unverified on the event's face; future
  events named not measurable), per-event forecast lines with the
  decomposition identity intact, interval widening exactly per
  pack on shocked days only, the baseline-projection impact view,
  migration 0005, registry API surfaces, demo + harness walks.
  Eval gate v5 adds zero-tolerance counters for the registry
  mapping, transmission verification, the hand-computed fixture
  line, widening, registration refusals and the impact view; the
  truth-isolation scan now covers the events package too.
- **Built and gated in R6:** the scenario pack (the bounded lever
  catalogue, stated conversions and grammar as versioned data),
  the deterministic grammar with named-clause refusals, pinned
  forks through the engine's shift slot (identity intact, base
  artefact byte-identical after all scenario activity), the
  integer-paise diff, scenario-local events (extensions and
  hypotheticals; the registry untouched), the adoption gate with
  supersession by link and labelled reads, migration 0006,
  scenario API + CLI surfaces, demo + harness walks. Eval gate
  v6 adds zero-tolerance counters for parse fixtures, lever
  bounds, fork pinning, diff sums, scenario-event locality and
  adoption discipline; the truth-isolation scan now covers the
  scenarios package too.
- **Built and gated in R7:** the dashboard pack (panel
  catalogue, head rule, grammar vocabulary, board sections as
  versioned data), the deterministic prompt grammar (catalogue
  panels or named gap panels; scenarios rendered only when
  named), specs + saved views + verified assembly (re-resolution,
  family re-performance, the lineage walk, byte-exact
  re-rendering — any problem refuses the whole dashboard), the
  computed re-run diff, the provenance appendix (100% of figures
  walked to stored facts), the morning desk board as an
  artefact, migration 0007, dashboard + board API surfaces and
  the `fmcg-agent-dashboards` CLI, demo walk. Eval gate v7 adds
  zero-tolerance counters for lineage completeness, gap
  suppression, re-run diffs and board rows; the truth-isolation
  scan now covers the dashboards package too.
- **Built and gated in R8:** the signal pack (horizon, rise/fall
  bars, wide-band bar, accuracy caps as versioned data), the
  buy-window signal engine + re-performance verifier (the
  degraded and unmeasured caps are hard rules, graded on
  hand-computed fixtures: rising / falling / degraded /
  in-event-window), the planning pack (month price rule, FIFO
  allocation, coverage rule, option shapes, ranking criteria as
  versioned data), desk-entered requirement plans with their own
  lineage terminal class, coverage assessments (paise-exact
  exposure, ranked options, scenario-basis assessments pinned
  to adopted forks), the board's signals section, migration
  0008, signal + planning API surfaces and the
  `fmcg-agent-signals` / `fmcg-agent-planning` CLIs, demo walk.
- **Built and gated in R9:** the alert pack (kinds, severity
  judgements, the price-move window and bar, the coverage
  floor, the escalation ladder and windows, the close-reason
  vocabulary — all versioned data), desk-entered subscriptions
  with supersession by link, computed price crossings, derived
  alerts pinned to their triggers with exact-once dedup,
  accuracy episodes, attributed acknowledge/close acts, the
  escalation fold, daily digests, the whole-set re-performance
  verifier, migration 0009, the alerts API surface and the
  `fmcg-agent-alerts` CLI, demo walk.
  Eval gate v8 adds zero-tolerance counters for degraded-series
  strong signals, signal re-performance, exposure arithmetic,
  desk/market provenance mixing and off-criteria ranking; the
  truth-isolation scan now covers the signals and planning
  packages too. Migration 0008's Postgres dialect is written to
  the same shape as 0007's (which was itself not live-applied);
  the Postgres profile remains verified by parity of the SQL,
  not by a live cluster run in this round.
- **Not yet built:** the console (R13). The round map runs to
  R20 and continues past it until the production bar is met.
- **The dataset in this repo is generated in-repo for the blueprint** — gold
  by construction, so the engine can be graded against a known future.
- **Live models are stub-tested until configured:** hosted profiles fail
  closed; nothing here has called a hosted model.
- **Docker image build was not run** in the build sandbox (no daemon); the
  Dockerfile and compose file follow the portfolio's verified pattern and
  are reviewed statically.

## Quickstart

```bash
make install        # uv sync (or: make install-pip)
make demo           # generate the dataset, print the planted checks
make harness        # boot the API and exercise it over HTTP
make test           # pytest
make evals          # the eval gate
make serve          # the operations API on :8000
```

Configuration is environment-only (see `.env.example`): model-port profiles
first, SQLite unless `DATABASE_URL` points at Postgres.

## Layout

```
src/fmcg_forecast/
  catalogue.py     the seven commodities, markets, planted parameters
  generator.py     the gold-by-construction dataset generator
  models.py        observations, events, manifest
  store.py         store port: SQLite / Postgres, insert-only writes
  truth.py         the sealed grading-truth store (forecast may not read)
  migrations.py    numbered migration runner (both dialects)
  workflow.py      LangGraph ingest graph: generate -> persist -> verify
  modelport.py     offline default; anthropic/bedrock/nim fail-closed
  api.py           FastAPI surfaces (reads + the forecast surface)
  forecast/        the forecast engine package (truth-isolated):
    models.py      forecast / approval / commentary artefacts;
                   backtest results, accuracy records, attachments (R3)
    engine.py      the stated decomposition engine
    verify.py      re-performance verification of stored artefacts
    commentary.py  figure extraction + verification for drafts
    service.py     run / approve / explain — the one workflow
  backtest/        the harness package (truth-isolated):
    pack.py        the accuracy pack: grid, window, degraded bar
    metrics.py     scored-day sums, derived metrics, aggregation
    verify.py      re-performance of results and ledger records
    harness.py     rolling-origin runs + ledger rebuild
  sentiment/       the sentiment package (intent-isolated, R4):
    pack.py        the sentiment pack: lexicon, ladder, floors
    models.py      item / extraction / index / corpus manifest
    extract.py     the pack's lexicon rule, performed offline
    index.py       the weekly index, computed in code
    verify.py      re-performance + commentary claim verification
    service.py     pipeline, forecast input, reads
    corpus.py      the planted corpus (load/grading side only)
    grading.py     the intent store (grading side only)
    load.py        corpus load (idempotent, digest-checked)
  events/          the event registry package (truth-isolated, R5):
    pack.py        the event pack: classes, channels, bases, rules
    models.py      market event / verification / impact artefacts
    paths.py       the pack's path rule, performed
    measure.py     transmission measurement + the impact view
    verify.py      re-performance of stored declarations
    service.py     declare / seed / verify / forecast provider
  scenarios/       the scenario studio package (truth-isolated, R6):
    pack.py        the scenario pack: lever catalogue, bounds,
                   conversions, the stated grammar
    models.py      request / run / adoption / diff artefacts
    parse.py       the deterministic grammar, performed offline
    shifts.py      lever values -> driver-input shifts, in code
    diff.py        the integer-paise fork-vs-base diff
    verify.py      re-performance of stored runs
    service.py     parse / fork / diff / adopt — one workflow
    cli.py         the fmcg-agent-scenarios command line
  dashboards/      the dashboard package (truth-isolated, R7):
    pack.py        the dashboard pack: panel catalogue, head
                   rule, grammar vocabulary, board sections
    models.py      spec / view / assembly / board artefacts
    parse.py       the deterministic prompt grammar, offline
    lineage.py     figure -> artefact -> facts provenance walks
    assemble.py    panel resolution + the computed re-run diff
    verify.py      whole-dashboard re-performance + lineage walk
    render.py      static HTML pages (dashboards + the board)
    board.py       the morning desk board, from artefacts only
    service.py     ask / save / assemble / board — one workflow
    cli.py         the fmcg-agent-dashboards command line
  signals/         the buy-window signal package (truth-isolated, R8):
    pack.py        the signal pack: horizon, rise/fall bars,
                   wide-band bar, accuracy caps, decision table
    models.py      the buy-signal artefact (reasoning on its face)
    engine.py      the pack's decision table, performed in code
    verify.py      whole-signal re-performance + the hard caps
    lineage.py     signal -> forecast -> facts provenance walks
    service.py     compute / read / verify — one workflow
    cli.py         the fmcg-agent-signals command line
  planning/        the coverage planner package (truth-isolated, R8):
    pack.py        the planning pack: month price rule, FIFO
                   allocation, coverage rule, option shapes,
                   ranking criteria
    models.py      desk-entered plan / coverage assessment
    engine.py      coverage, exposure and ranked options, in code
    verify.py      re-performance + provenance separation checks
    lineage.py     the desk_entered terminal fact
    service.py     enter / assess / verify — one workflow
    cli.py         the fmcg-agent-planning command line
  alerts/          the alerting package (truth-isolated, R9):
    pack.py        the alert pack: kinds, severity judgements,
                   price-move window/bar, coverage floor,
                   escalation ladder + windows, close reasons
    models.py      subscription / crossing / alert / act / digest
    engine.py      crossings, derivation, the state fold
    verify.py      per-alert + whole-set re-performance
    service.py     subscribe / sweep / act / digest — one workflow
    cli.py         the fmcg-agent-alerts command line
migrations/        0001-0009 SQL, sqlite + postgres dialects
scripts/           demo.py, local_harness.py
evals/             the eval gate
docs/              architecture.md
```

Apache 2.0. A Trida AI blueprint — patterns are the point; the fictional
buyer's data is ours, generated for this repo.
