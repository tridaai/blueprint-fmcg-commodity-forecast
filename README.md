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

## What Round 10 adds

Thin-data depth and assisted intake — Law 7 made operational
(F20-DI3 on the roadmap). A thin series no longer gets a
padded single number: it gets evidence, an earned confidence
tier, and named gaps on every surface; and a number a person
phones in no longer lands in the data on the enterer's word
alone — it waits for a second named person.

- **Thin-data assessments as artefacts** — under a versioned
  **thin-data pack** (windows, staleness bars, the tier bars
  and caps, the band-width rule: pack v2026.10.1), each
  forecast's pinned assessment states, for its own series:
  **operating-day coverage by window** (7/30/90/365 days,
  on the series' own catalogue reporting pattern — coffee's
  Tue/Fri pattern counts exactly its own days), with **every
  missing operating date named by date**; per-driver states
  — present, missing or stale — with the **last observed
  date** for every gap; and per-horizon **confidence tiers**
  (`established` / `guarded` / `thin` / `unproven`) computed
  in code from the window coverage, the measured accuracy
  (MAPE and band coverage) and the forecast band's width
  against the series' own realised volatility. **Caps never
  raise a tier:** an unreported driver caps at `guarded`, a
  stale driver or a degraded accuracy record caps at
  `thin`, a not-estimable sentiment caps at `guarded`. Every
  failed bar and applied cap is a named reason on the
  horizon's face. Assessments are insert-only and
  content-addressed; the verifier re-performs them field for
  field, and a stored tier above the re-performed tier is an
  **overstatement** — as is any surface claiming a tier the
  series has not earned (`POST /thin-data/claims/verify`
  grades such a claim as a contradiction). The groundnut
  forecast view, the coffee dashboard note and the board's
  gap rows all carry the tiers and name every thin gap.
- **Assisted intake with maker–checker (F20-DI3)** — a
  phoned-in price or arrivals figure is entered as a
  **pending entry** naming its enterer and source note. A
  pending entry is **not a fact**: it lives in its own table
  and no engine read can see it. A second named person —
  never the enterer; the self-check is refused in code,
  case-insensitively — confirms or rejects it in an
  attributed act. Confirmation inserts exactly one
  observation through the store's ordinary insert path, and
  the entry's provenance carries both names; rejection lands
  nothing. One natural key (series, date, driver) carries at
  most one entry and at most one fact, so a phoned-in figure
  can never duplicate or overwrite a reported one. The
  verifier re-performs the whole chain: content addresses,
  the no-self-check rule, and the grading that a pending or
  rejected entry with an observation at its key is
  **unconfirmed leakage**.
- **Surfaces** — migration 0010 (both dialects); `GET
  /thin-data/pack`, `POST /thin-data/assessments`, `GET
  /thin-data/assessments` + `/{id}` + `/{id}/verify`, `GET
  /thin-data/forecasts/{forecast_id}`, `POST
  /thin-data/claims/verify`; `POST /intake/entries`, `GET
  /intake/entries` + `/{id}`, `POST /intake/entries/{id}/
  confirm` + `/reject`, `GET /intake/entries/{id}/verify`;
  the `fmcg-agent-thin` and `fmcg-agent-intake` CLIs. The
  forecast view (`GET /forecasts/{id}`) now carries the
  assessment beside the forecast. The demo walks groundnut
  and coffee's thin evidence (coffee's 365-day window naming
  the planted August 2025 disruption days by date), refuses
  an unearned `established` claim, and runs one phoned-in
  coffee price through pending → self-check refused →
  confirmed by a second person into exactly one fact.

Honest positions, stated plainly: a tier is an **evidence
judgement under the stated pack**, not an accuracy claim —
the accuracy itself still rides on the R3 ledger's measured
records, and a tier never changes a forecast number. Intake
covers the two phone-reportable drivers (`modal_price`,
`arrivals`); the intake provenance rides the confirmation
lineage the entry view exposes — the observation schema is
unchanged, so an assisted fact is indistinguishable in the
series itself from a reported one once confirmed, which is
the point of the checker gate.

## What Round 11 adds

The production data plane (F20-DI1, F20-DI2, F20-DI4 on the
roadmap) — how data actually arrives once the generator's
history is in: named sources under a registry, one
validation path for every connector, quarantine instead of
silent drops, corrections that never rewrite history, and
backfill that earns a series its measured accuracy.

- **The source registry (F20-DI1)** — under the versioned
  **ingest pack** (v2026.10.1: the value-range vocabulary,
  the quarantine and refusal reason vocabularies, the
  connector kinds), sources are artefacts: the six built-ins
  (an Agmarknet-style file drop, an exchange bhavcopy drop,
  a trade-flow drop, a weather service pull, a mandi API
  push, the generated-history backfill feed) plus desk
  registrations as named acts under stated terms.
  Registration pins each source's drivers to the canonical
  units — conversion, where it exists, is upstream of this
  port and never performed here. Every delivery names its
  source and its as-of; a delivery that cannot is refused
  whole, and the refusal is itself a stored artefact with
  its reason (`unknown_source`, `unit_mismatch`,
  `batch_missing_provenance`, `empty_batch`).
- **One validation path, quarantine with named reasons
  (F20-DI2)** — file drops and API pushes are judged by the
  same code. A clean row lands through the ordinary insert
  path and gains exactly one **provenance row** naming its
  batch and source. A bad row is quarantined with its exact
  reasons from the pack vocabulary — malformed, unprovenanced,
  unknown commodity or market, a driver the series does not
  report or the source does not carry, a future date, an
  out-of-range value, an in-batch conflict, a conflict with
  what already landed. Re-delivering a batch is the same
  artefact and lands nothing twice; a later delivery of a
  landed fact counts as a duplicate, never a second fact.
- **Corrections as overlays (F20-DI2)** — a landed value that
  turns out wrong is corrected by an attributed, reasoned
  act that supersedes the previous correction by link. The
  stored observation is never rewritten: the **effective
  fact** at a key is the fold of the landed value and its
  correction chain, and a correction can also answer a
  quarantined row — stating what the quarantined value
  should have been, without landing anything.
- **Backfill & replay (F20-DI4)** — a series backfilled
  through the connectors earns its place in the accuracy
  ledger the same way the grid's series did: replay runs the
  engine at chosen origins through the harness's own seams,
  stores each result if absent, and rebuilds the series'
  ledger records in place. Origins the data cannot support
  are skipped with the engine's refusal named on the replay
  artefact — never silently dropped. The verifier
  re-performs batches, correction chains, provenance and
  replays; one mismatch refuses the artefact.
- **Surfaces** — migration 0011 (both dialects); `GET
  /ingest/pack`, `GET`/`POST /ingest/sources`, `POST
  /ingest/batches/file` + `/push`, `GET /ingest/batches` +
  `/{id}`, `GET /ingest/quarantine`, `POST`/`GET
  /ingest/corrections`, `GET /ingest/effective`, `POST
  /ingest/backfill/replay`, `GET /ingest/verify`; the
  `fmcg-agent-ingest` CLI; and `scripts/prod_smoke.py`, the
  production smoke that stands the app on Postgres, applies
  the migration chain, loads the dataset, runs the grid and
  exercises the data plane end to end. The demo loads a
  drop with a quarantined pair, replays it, corrects a
  landed price and replays an origin the grid never ran.

Honest positions, stated plainly: the connector framework
covers file drops and API pushes — the two shapes the desk
actually receives — and not live streaming feeds; a
scheduled pull is a registered kind whose deliveries still
arrive as batches through the same path. Corrections state
the desk's current belief about a fact; the landed record
and its provenance stay exactly as delivered, which is what
makes the fold auditable. Backfill replay computes real
backtests — it is priced in engine runs, and the replay
artefact says plainly which origins were skipped and why.

## What Round 12 adds

Forecast quality & ops analytics (F20-AM1 on the roadmap)
with the planted-shock grading depth the round map pairs
with it — the desk learns which parts of the system to
trust, measured from the artefacts of record rather than
asserted about them.

- **The ops report** — one content-addressed, insert-only
  artefact under a versioned **analytics pack** (v2026.10.1:
  the trend windows and epsilon, the outcome rule, the
  minimum class sample, the shock-window rule — all stated
  as data), naming the accuracy, signal and event pack
  versions its inputs were struck under. Four sections,
  every figure re-performed field for field by the
  verifier; one mismatch refuses the report.
- **Accuracy trends** — per series × horizon, the first
  three stored backtest results pooled against the last
  three by the accuracy ledger's own pooling (error sums
  pooled, metrics derived, day-weighted — never a mean of
  means), judged improving / steady / worsening against
  the pack's epsilon, with the ledger record of record
  riding beside the trend. A series with too few origins
  to tell early from late is named **insufficient** —
  coffee, with five strikable origins, is exactly that,
  on all three horizons.
- **Signal outcomes, measured** — the signal the desk
  would have seen is struck at every accuracy-grid origin
  (a raw engine run, the harness's basis) carrying the
  accuracy attachment pooled from **earlier origins only**,
  so no call is judged with knowledge its origin did not
  have; each is then graded against the last observed
  price inside its horizon: realised drift, drift error
  against the signal's own prediction, the move against
  the signal pack's own bars, and a favourable verdict
  under the pack's stated per-call rule. On the generated
  dataset: 135 origin signals graded, 126 favourable —
  and the five coffee origins the engine refuses are
  named as skips, never dropped. Desk signals whose
  horizons have not landed in observed history are
  **pending**: named with the reason, never graded.
- **Transmission error by event class** — every
  registered event re-measured by the events layer's
  seasonally-matched measurement and aggregated per
  class: mean signed error, mean absolute error, mean
  ratio to claim, verified/unverified counts, sample
  counts on the face. Each planted class (tariff,
  export restriction, weather shock) has exactly one
  measurable event — verified, and named a **small
  sample** against the pack's minimum of three: printed,
  and read as anecdote, not evidence. Classes with no
  registered events are named too.
- **Shock-window grades** — per event × market ×
  horizon, the stored scored days are split at the
  event's window plus its decay tail and both pools are
  re-derived by the backtest metrics' own day formulas:
  the tariff and the drought grade against their
  outside-window rests, while the 2024 export ban —
  over before the grid's first origin — is named
  **no shock-window days** on every row rather than
  silently absent or, worse, graded.
- **Surfaces** — migration 0012 (both dialects); `GET
  /analytics/pack`, `POST /analytics/reports`, `GET
  /analytics/reports` + `/{id}` + `/{id}/verify`; the
  `fmcg-agent-analytics` CLI. The demo builds the report
  over the planted book and prints its sections.

Honest positions, stated plainly: a report is struck from
the artefact set standing at build time. When the set
moves on — a backfilled origin, a newly struck signal, a
newly declared event — the older report's re-performance
names the drift rather than passing silently, and a
rebuild strikes the current record; the superseded report
stays on record, flagged, never edited. Transmission
aggregates over one event are anecdote by the pack's own
rule, and the report refuses to dress them as more.

## What Round 13 adds

The operator console (F20-OW2 + F20-OW3 + F20-OW4 +
F20-MF2 on the roadmap) — the desk day in one place, under
a versioned **console pack** (v2026.10.1: the freshness
windows, the queue order, the rejection-reason
vocabulary, the triage acts and the gate and pin rules —
all stated as data). Every console artefact is
content-addressed and insert-only, and the whole console
re-performs: a tampered rejection, triage act or
pre-flight is flagged, never passed silently.

- **The forecast review queue (F20-OW2)** — every draft
  forecast on the desk in the pack's stated order —
  degraded accuracy first, then unmeasured, then measured
  — each row carrying its per-horizon accuracy states,
  factor contributions, the prior official for the series
  with the 30-day P50 difference against it, and its
  approval blockers on its face. **Rejection is a named
  act**, sibling to approval: a named desk head, a reason
  from the pack's vocabulary (`other_stated_reason`
  requires the reason spelled out), one rejection per
  draft, idempotent on an identical act. A rejected draft
  leaves the queue and can never be approved afterwards —
  the check lives inside the approval act itself, so no
  surface can reopen it; the desk's remedy is a new run.
- **The event triage queue (F20-OW3)** — every declared
  event whose transmission is unverified or not yet
  measurable, plus verified events an analyst has acted
  on, worked through three named acts: **confirm** (a
  named analyst accepts the basis; the event may then
  stand behind official forecasts), **retire** (withdrawn
  — excluded from new runs altogether, and a blocker on
  drafts that already applied it), **amend** (the event is
  superseded by a corrected declaration, recorded by
  link; restating the identical declaration is refused).
  Until an event is officially clear — measured-verified
  or confirmed — it still contributes to draft forecasts
  at its stated amount, labelled on every read, and it
  contributes **zero to the official view**: approval of
  any draft applying it is refused, naming the event.
  The fold of acts is the state; a later confirm revives
  a retired event.
- **The coverage pre-flight (F20-OW4)** — before a run,
  a struck checklist over the raw record: every catalogue
  driver's state (present / stale / missing, with its
  last-observation date and age), the sentiment freshness,
  and the backtest coverage per horizon — and the gap
  list, every gap a named sentence ("Coffee does not
  report it" for a catalogue gap, a different sentence
  for never-reported). A degraded-accuracy horizon is
  coverage, not a gap. Running anyway is one deliberate
  act: the run **pins the checklist** — report id, pack
  version and the gap list verbatim ride inside the
  forecast artefact's own content address — and a pin
  naming another series, another as-of or an unknown
  report is refused.
- **The responsive exception console (F20-MF2)** — the
  morning board, review queue, triage queue, open alerts
  and live pre-flights composed into one read at
  `/console` (HTML at `/console/html`), and a phone page
  at `/console/phone` whose inline forms post to a single
  action door. Parity is graded, not asserted: the same
  act struck through the phone's door and through the
  canonical endpoint is the **identical artefact**, byte
  for byte, on twin stores — over HTTP in the tests and
  at service level in the eval gate.
- **Surfaces** — migration 0013 (both dialects);
  `POST /forecasts/{id}/reject`,
  `GET /forecasts/{id}/rejection`, the enriched
  `GET /forecasts/{id}/events` (per-event verdict and
  triage state plus the draft's official blockers),
  `GET /console/pack`, `POST/GET /console/preflights`
  (+ `/{id}`, `/{id}/verify`), `GET /console/review-queue`,
  `GET /console/triage-queue`,
  `GET/POST /market-events/{id}/triage[/confirm|retire|amend]`,
  `GET /console`, `/console/html`, `/console/phone`,
  `POST /console/actions`, `GET /console/verify`; the
  `fmcg-agent-console` CLI. The demo walks a full desk
  day: pre-flight, a pinned run, a refused approval, the
  triage clear, a rejection.

Honest positions, stated plainly: triage confirm is a
human act with a name on it — the console never upgrades
an event's measured verdict, and the measured verdict
stays on the event's face next to the confirm. A retired
event's drafts keep their original event lines (history
is not rewritten); the retirement blocks their approval
and removes the event from new runs. The phone page is a
rendering of the same composed view as the desktop page —
no second record, no phone-only state.

## What Round 14 adds

Geospatial basis & netting (F20-PO4 + F20-GS1 + F20-GS2
on the roadmap) — the layer that puts the markets on
one map and prices them into one plant, under a
versioned **geo pack** (v2026.10.1: the band window and
quantiles, the paired-days floor, the freshness rule,
the cost-line catalogue, the landed ranking rule, the
weather-overlay rule and the schematic geography — all
stated as data). Every geo artefact is content-addressed
and insert-only, the band re-performs from the raw
series, and a tampered reading, comparison or map is
flagged, never passed silently.

- **Registry benchmarks and basis bands (F20-PO4)** —
  the catalogue now names each commodity's reference
  market (its first-listed market, whose records carry
  the 1.000 price factor). A **basis reading**
  (`BASIS-`) compares every reporting market against it
  over the pack's trailing 365-day band with paise-exact
  arithmetic: the paired spread band (10th / median /
  90th percentiles from same-date pairs only — never
  interpolated, never from unmatched dates), the paired
  days counted on the face, and a classification:
  reference, within, wide, narrow. Below the pack's
  60-paired-day floor the spread is **insufficient
  history** and the band is still stated; a market that
  never pairs reads **no paired history**; a spread
  whose last pair is older than the pack's freshness
  window is flagged **stale** on its face. It is graded,
  not asserted: the eval gate re-pairs the raw series
  itself and re-derives every band edge.
- **The landed comparison and its cost lines (F20-GS1)**
  — freight and handling are entered by the desk as
  **cost-line entries** (`COST-`): a named enterer, an
  entry date, an integer paise rate, `origin:
  desk_entered` on every entry. They are the layer's
  only money inputs — the code assumes nothing, and a
  line outside the pack's catalogue, a negative or
  non-integer rate, or an unnamed enterer is refused.
  The standing rate per line is the fold's latest entry
  (earlier entries stay on the record), scoped to
  entries entered on or before the comparison's as-of,
  so a rate entered later never reprices an earlier
  comparison. A **landed comparison** (`LAND-`) reads
  landed = the market's current stored price + its
  standing lines, ranked cheapest first by the pack's
  rule. A market missing a line reads **not computable**
  with the line named and its rate carried as missing —
  never assumed, never ranked. The scope note rides on
  the artefact: comparison only — no purchase, transfer
  or trade is placed or instructed; procurement
  execution stays out of scope.
- **The market map (F20-GS2)** — a **market map**
  (`MAP-`) lays the commodity's markets on the pack's
  schematic geography — a relative grid read off the
  catalogue, stated as schematic, never surveyed
  coordinates — pinning the standing basis reading by
  id. Each cell composes only artefact reads: the
  current price, the basis classification and spread
  from the pinned reading, the weather overlay (the
  trailing 90-day deviation of the stored weather index
  the engine itself consumes — no second weather
  record), and the open-alert state folded at the
  as-of. Registry events whose windows cover the as-of
  ride above the grid as the event overlay. A market
  with no current price renders as a **named gap,
  never a zero**; the page is stored inside the
  artefact and must re-render byte-for-byte.
- **Surfaces** — migration 0014 (both dialects);
  `GET /geo/pack`, `POST/GET /geo/cost-lines`,
  `POST/GET /geo/basis-readings` (+ `/{id}`),
  `POST/GET /geo/landed-comparisons` (+ `/{id}`),
  `POST/GET /geo/maps` (+ `/{id}`, `/{id}/html`),
  `GET /geo/verify`; the `fmcg-agent-geo` CLI. The demo
  strikes a wheat basis, enters desk cost lines, prices
  a landed comparison with one market left honestly not
  computable, and opens the soybean map inside the
  planted tariff window.

Honest positions, stated plainly: the geography is a
schematic layout for reading, not GIS — positions are
relative, distances are not computed, and nothing here
routes freight. The landed comparison is only as
current as the desk's entries: rates carry the date
they were entered and the comparison names its as-of;
nothing refreshes them automatically. Basis is measured
on modal price only — arrivals-weighted or
quality-adjusted basis is not claimed.

## What Round 15 adds

Desk policy pack, approval chains, annotations
(F20-AD2 + F20-CA2 + F20-CA1 on the roadmap) — the
layer that governs the desk itself: which decisions
need whose approval, and how the desk's own rules are
allowed to change. One scope decision, stated up
front: the rule packs that shape artefacts (backtest
accuracy bars, alert thresholds, scenario lever
bounds) stay **code-versioned packs**, as they have
been since R3 — every artefact they touch already
carries their version. What R15 makes runtime-versioned
is the **desk policy pack**: the approval limits and
chains, the configuration a desk legitimately tunes
without a release.

- **The desk policy pack (F20-AD2)** — a versioned
  pack (`desk/pack.py`, genesis v2026.10.1, fail-closed
  loader) stating the coverage **exposure threshold**
  (₹50,00,000) and exactly one **approval chain** per
  decision kind: pack_change, scenario_adoption,
  forecast_approval, coverage_commitment. A chain is an
  ordered list of steps (role + condition); every
  shipped chain is two-person and bars the requester
  from acting. A new pack version is a **proposal**
  (`POL-`): the whole pack plus a field-by-field
  **diff** against the standing version, both carried
  on the artefact and re-derived by the verifier. A
  proposal that changes nothing, reuses a label, or
  carries an unknown field is refused. A version
  becomes **standing only through its own pack-change
  chain** — there is no activate endpoint; when the
  completing act lands, the service flips the standing
  pointer in the same strike. A version whose status
  was flipped any other way is named by the verifier:
  standing without its chain.
- **Approval chains (F20-CA2)** — a **decision**
  (`DEC-`) pins the pack version it opened under and
  the **resolved steps** for its target, resolved from
  the target's own face: a forecast whose pinned
  accuracy state is degraded or unmeasured needs
  review + desk-head sign-off, a measured one review
  alone; a coverage commitment above the pack's
  exposure threshold needs the sign-off step, at or
  below it does not; scenario adoption always runs its
  two steps (the two-person rule). **Acts** (`DACT-`)
  are struck one at a time and judged in order: out of
  order, in the wrong role, from the decision's opener,
  twice from one actor (names fold — case, spacing and
  punctuation are not identity), or dated before the
  decision opened are all refused, and a rejection
  closes the decision. The decision's state is the
  fold of its acts, never a stored field. The
  **decision log** (`DLOG-`) folds the record's acts
  up to an as-of into a gapless sequence — the desk's
  audit read.
- **Annotations (F20-CA1)** — **comments** (`CMT-`)
  and **follow-up tasks** (`TSK-`) pin to artefacts by
  kind and id — forecasts, scenarios, events, alerts,
  buy signals, dashboards, coverage assessments,
  basis readings, landed comparisons, market maps —
  and are refused over anything not on record. A task's
  state is the fold of its acts (`TACT-` close /
  reopen); a task pinned to a scenario that has since
  been superseded carries `target_superseded` on its
  face — flagged, never quietly moved. Every desk
  artefact is content-addressed and insert-only, and
  the verifier re-derives each one: a rewritten diff,
  a re-stepped act, a dropped log entry or a standing
  version without its chain is flagged, never passed
  silently.
- **Surfaces** — migration 0015 (both dialects);
  `GET /desk/pack` (the standing pack),
  `GET /desk/pack/genesis`,
  `POST/GET /desk/policy-versions` (+ `/{id}`),
  `POST/GET /desk/decisions` (+ `/{id}`, `/{id}/acts`),
  `POST/GET /desk/decision-logs` (+ `/{id}`),
  `POST/GET /desk/comments`, `POST/GET /desk/tasks`
  (+ `/{id}`, `/{id}/acts`), `GET /desk/verify`; the
  `fmcg-agent-desk` CLI. The demo proposes a tightened
  pack, watches its proposer refused, and stands the
  version through two other named people.

Honest positions, stated plainly: the desk pack is
configuration, not code — changing a chain changes who
must approve, never what an engine computes, and every
change is itself a chained, logged act. Decisions
opened under an older pack keep that pack's chains to
their end; nothing re-chains an open decision. Name
folding is a discipline aid, not identity proof — the
desk still runs on named people, and a determined
impersonator is an organisational problem, not one
this layer claims to solve.

## What Round 16 adds

Identity-shaped roles, market scopes and the access
audit (F20-AS1), and master data & market calendars
(F20-AD1) — the two layers the desk's numbers needed
before they travel: who may see which market's
figures, with a record of every read; and a governed
answer to "when did that market actually sit", because
a holiday is what *missing data* means.

- **Role scopes (F20-AS1)** — an **access pack**
  (`access/pack.py`, genesis v2026.10.1, fail-closed
  loader) stating three roles as data: **desk head**
  (every surface, grants, master-data edits, the audit
  read), **trader** (forecast, dashboard and export
  reads inside their grant's market scope), **viewer**
  (forecast and dashboard reads in scope — no export).
  A principal's role and scope stand only as a
  **grant** (`GRT-`): an insert-only act chained over
  the subject's folded name — grant, narrow, repeal —
  where standing is the chain's head, never a stored
  column. Grants are struck by a standing desk head
  over other names; the book's first grant is struck
  by its own subject as desk head over all markets
  and flagged **bootstrap** on its face, because an
  empty book has no one else. A scope names only
  markets the catalogue carries.
- **Governed reads, existence-hiding** — the official
  forecast read, the dashboard assembly read and the
  assembly's rendered page (the **export** surface)
  are governed when a read names its principal in the
  `x-desk-actor` header: judged under the standing
  grant on every market the artefact spans (a
  dashboard hides if *any* panel's market is out of
  scope), recorded as an **access entry** (`ACC-`)
  before the answer, and every refusal — unknown
  principal, role barred from the surface, market out
  of scope — answered **exactly as if the artefact
  did not exist**: the same 404, the same body as a
  missing id. The reason is recorded on the entry,
  never in the answer. The **audit log** (`ALOG-`)
  folds the entries in strike order, numbered from 1
  with no gaps, and the verifier re-derives the whole
  layer: chains, granter discipline re-judged in
  strike order, every entry's outcome re-judged under
  the grant its face names, every log re-folded.
- **Master data & calendars (F20-AD1)** — the
  catalogue's facts restated as versioned data:
  every market's **calendar** (weekly pattern,
  holidays, extra operating days), commodity and
  market display names, and the unit statements
  (INR per quintal, quintals, ten quintals to the
  tonne). The genesis state is the catalogue's own; a
  **version** (`MDV-`) is struck whole by a named
  editor holding a standing desk-head grant, carries
  a field-by-field **diff** against the version it
  supersedes (re-derived by the verifier), and stands
  on strike — authorship and versioning are the gate;
  the AD2 chain governs the desk's policy limits, not
  a market's holiday list. A strike that changes
  nothing is refused, as is a calendar naming one
  date as both a holiday and an extra session.
  **Coverage re-derivation** then answers the
  acceptance question directly: the thin pack's
  windows (7/30/90/365) recomputed under two states,
  with every date whose operating status changed
  named per window — a Christmas closure moves
  kanpur's verdicts by exactly that date and nothing
  else, and a display-name edit moves no verdict at
  all.
- **Surfaces** — migration 0016 (both dialects);
  `GET /access/pack`, `POST/GET /access/grants`,
  `GET /access/standing/{subject}`,
  `GET /access/entries`, `POST/GET /access/logs`
  (+ `/{id}`), `GET /access/verify`;
  `GET /masterdata/pack`, `GET /masterdata`,
  `POST/GET /masterdata/versions` (+ `/{id}`),
  `GET /masterdata/coverage/{commodity}/{market}`,
  `GET /masterdata/verify`; the `fmcg-agent-access`
  and `fmcg-agent-masterdata` CLIs. The demo opens the
  grant book, watches an out-of-scope read hide, and
  re-derives kanpur's coverage under the closure.

Honest positions, stated plainly: a read that names
no principal is the **local posture** — the console's
own reads, the demo, this repo's harness — and
proceeds unjudged and unrecorded, as the desk's reads
always have; the governed surfaces are for reads that
carry a name, and the pack states that boundary
rather than pretending the header is authentication.
It is not: the `x-desk-actor` header is a stated
identity claim, and authenticating it (SSO, signed
tokens) is deployment work this blueprint does not
fake. Name folding remains a discipline aid, not
identity proof. And a calendar is reference data: it
moves what coverage *expects*, never what history
*recorded*.

## What Round 17 adds

Red team: injection & poisoning (F20-AS2 on the
roadmap) — the round that attacks the surfaces the
first sixteen built, fixes what breaks at the root,
and pins every verdict in standing gates. The headline
defect was real: the sentiment pipeline handed every
stored headline to the model port unscreened, and a
headline is text written by someone the desk does not
control.

- **The screening pack and the quarantine (F20-AS2)**
  — a versioned pack (`screening/pack.py`, genesis
  v2026.10.1, fail-closed loader) stating five closed
  categories of instruction-shaped text (instruction
  override, role reassignment, directed verdict, fake
  authority, output directive) and the folding
  discipline they are judged under: lower case,
  zero-width characters removed, separator runs
  collapsed — so case games, punctuation-splitting and
  zero-width splitting are the same text under the
  pack's own reading. The pipeline screens every item
  before any model call; a flagged item is quarantined
  as a content-addressed record (`SRN-`, migration
  0017) carrying the headline **verbatim** — the
  screen routes, it never edits — and it earns no
  extraction, joins no index and is cited by no
  commentary. A headline that merely *reports* about
  instructions, systems or classifications matches no
  construction and passes byte-identical; the planted
  corpus passes whole (583 of 583, graded).
- **The context audit** — the eval gate and tests run
  the pipeline against a recording model port and
  grade the negative space directly: no planted
  instruction's headline is ever offered to the port,
  and every passing headline is offered exactly as
  stored. Nine planted attacks (override, role, fake
  authority, verdict, output directive, and the three
  obfuscations, plus an instruction riding a second
  sentence) are quarantined with their rules named.
- **The poisoning suite's real find** — the corpus
  manifest's digest was asserted once, at load, and no
  verifier ever re-performed it: a flood of items
  planted around the load path verified clean on the
  strength of its surviving extractions. Corpus
  integrity is now re-performed (count, then digest,
  in `verify_stored` and graded in evals): a planted
  flood is named by count and digest.
- **Verdicts that held, pinned not asserted** — an
  event description carrying an instruction never
  enters any model context (the scenario context is
  event id + class, audited over every port call); a
  scenario-text breakout is refused by the grammar
  naming the clause; an injected dashboard clause
  becomes a named gap panel and states no figure;
  lexicon stuffing can counterfeit the strongest
  reading the sentiment ladder allows and no more —
  its direction and strength cap exactly where a
  genuinely strong headline's do.
- **Stated limits** — obfuscation past the pack's
  stated normalisation (leetspeak, homoglyphs) is not
  caught: it travels to the port as inert text, the
  offline lexicon finds no instruction in it, and a
  hosted profile's residual exposure is a deployment
  decision, recorded in the pack. Insert-only remains
  a service discipline, not a storage guarantee —
  records forged around the service are *detected* by
  the verifier (re-performance, completeness both
  ways, quarantine-holds), not prevented. Screening
  covers item headlines; desk-entered request text is
  the desk's own instruction by design and is bounded
  by the scenario/dashboard grammars instead.
- **Surfaces** — `GET /screening/pack`,
  `GET /screening/records` (+ `/{item_id}`),
  `GET /screening/verify`; the sentiment item read now
  carries its screening record; the
  `fmcg-agent-screening` CLI; the demo plants an
  instruction in the corpus and watches it quarantined
  while the ministry item beside it passes.

## What Round 18 adds

Cost, usage & service monitoring (F20-AM2 on the
roadmap) — the layer that answers the operator's three
questions from artefacts: what did the model cost,
what did the feeds do, and what is late.

- **The monitoring pack** — a versioned pack
  (`monitoring/pack.py`, genesis v2026.10.1,
  fail-closed loader) stating the closed purpose
  vocabulary (one purpose per model-port method), the
  token estimator (ceil(characters / 4) over the
  canonical payload — a stated sizing rule, not a
  provider's tokenizer count), a reference rate card
  per profile (pack-stated figures for estimation,
  never a provider quote or a billed amount), and the
  freshness window each registry cadence is owed
  (hourly 3h, daily 36h, weekly 240h; a one-off
  bootstrap owes no window).
- **The run ledger** — a recording model port wraps
  any port and strikes exactly one run record (`RUN-`,
  migration 0018) per **completed** call: profile,
  purpose, the SHA-256 of the canonical request and
  response — **never their text**, so the ledger can
  re-identify and re-price any call without becoming a
  second copy of the desk's words — character counts,
  estimated tokens, and the cost in integer nano-USD.
  A call that raises strikes no record: the ledger
  prices work done, and a refusal consumes nothing it
  prices. The offline profile is **unrated**: its
  records carry cost None — never zero, because a zero
  would silently price the call into a total. The API
  app wraps its port at the factory, so every call the
  served system makes is ledgered. Records flush to
  the store in batches (at 64 pending, before any
  monitoring read, and on close) — the ledger is the
  store's one high-frequency write, and one commit
  per call would tax every pipeline run for no
  reader's benefit; a hard process kill can lose the
  unflushed tail of fewer than 64 records, stated
  here rather than discovered later.
- **The monitoring board** — struck as-of a stated
  instant (`MON-`), folding only records and batches
  at or before it. The usage section folds the ledger
  by profile × purpose; the board's cost total is the
  **exact sum of the rated records folded**, with
  unrated calls counted separately and never priced.
  The freshness section gives every registered source
  a row — job totals folded from the batch artefacts
  (batches, refusals, rows received / loaded /
  quarantined), the last **loaded** batch judged
  against its cadence window: a source past its window
  is a **breach, named** on the board's face; a source
  that has never loaded is named in the never-loaded
  list on every board, never absent; a refusal is job
  history, not freshness — a feed whose latest delivery
  was refused whole has not fed the store, and its
  verdict still reads from its last loaded batch.
- **The verifier re-performs everything** — each
  record's address, estimator figures and pack pricing;
  each board's full fold at its as-of. A rewritten
  cost, a purpose outside the vocabulary, a forged
  address and a board with a quietly dropped breach
  are each named, and the tamper probes are graded in
  the eval gate. A board struck before the artefact
  set moved on names that drift rather than passing
  silently; the remedy is a newly struck board.
- **Surfaces** — `GET /monitoring/pack`,
  `GET /monitoring/runs` (profile / purpose filters),
  `POST /monitoring/boards`, `GET /monitoring/boards`
  (+ `/{board_id}`), `GET /monitoring/verify`; the
  `fmcg-agent-monitoring` CLI; the demo runs its
  pipeline through the recording port, strikes a board
  and reads the reconciliation and the named gaps off
  it.

Honest positions, stated plainly: token figures are
estimates under the pack's stated rule, and costs are
estimates at reference rates — a deployment replaces
the rate card with its contracted rates by striking a
new pack version, and no figure here is a provider
bill. Freshness judges receipt time of loaded batches
against stated windows; it says nothing about whether
a feed's *contents* were right — that is the data
plane's quarantine discipline, one layer down.
Insert-only remains a service discipline, not a
storage guarantee: records forged around the service
are detected by the verifier, not prevented.

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
- **Built and gated in R10:** the thin-data pack (windows,
  staleness bars, tier bars and caps, the band-width rule),
  the assessment engine (operating-day coverage with named
  missing dates, driver states with last-observed dates,
  per-horizon tiers computed in code), the claim verifier
  (an unearned tier stated anywhere is a graded
  contradiction), assisted intake with maker–checker
  (pending entries invisible to engines, the self-check
  refused in code, confirmation landing exactly one fact
  with both names in its lineage), the chain verifier,
  migration 0010, the thin-data and intake API surfaces and
  the `fmcg-agent-thin` / `fmcg-agent-intake` CLIs, demo
  walk. Eval gate v9 adds zero-tolerance counters for tier
  overstatement, window-coverage recomputation, unnamed
  thin gaps, unconfirmed intake leakage, self-checks and
  intake chain breaks; the truth-isolation scan now covers
  the thin and intake packages too.
  Eval gate v8 adds zero-tolerance counters for degraded-series
  strong signals, signal re-performance, exposure arithmetic,
  desk/market provenance mixing and off-criteria ranking; the
  truth-isolation scan now covers the signals and planning
  packages too. Migration 0008's Postgres dialect is written to
  the same shape as 0007's (which was itself not live-applied);
  the Postgres profile remains verified by parity of the SQL,
  not by a live cluster run in this round.
- **Built and gated in R11:** the ingest pack (value ranges,
  the quarantine and refusal vocabularies, connector kinds),
  the source registry (six built-ins plus named-act desk
  registrations with canonical units pinned), the connector
  framework (file drop + API push through one validation
  path), quarantine with exact named reasons, whole-batch
  refusal artefacts, provenance rows for every landed fact,
  correction overlays with the effective-fact fold,
  backfill replay earning a series its ledger through the
  harness's seams, the data-plane verifier (batches,
  corrections, provenance, replays — tamper included),
  migration 0011, the ingest API surface, the
  `fmcg-agent-ingest` CLI, the demo walk, and the Postgres
  production smoke (`scripts/prod_smoke.py`) exercising
  migrations, the dataset load, the backtest grid and the
  data plane on a live cluster. Eval gate v10 adds
  zero-tolerance counters for quarantine exactness,
  provenance, replay idempotence, refusals, correction
  folds and backfill; the truth-isolation scan now covers
  the ingest package too.
- **Built and gated in R12:** the analytics pack (trend
  windows and epsilon, the outcome rule, the minimum class
  sample, the shock-window rule — versioned data), the ops
  report (accuracy trends pooled by the ledger's own rule
  with insufficient history named on coffee; signal
  outcomes struck at grid origins with as-of attachments
  and measured against realised prices, pending desk
  signals named never graded; transmission error per event
  class with small samples named as anecdote; shock-window
  grades split at the planted windows, the 2024 ban named
  ungraded), the whole-report re-performance verifier,
  migration 0012, the analytics API surface, the
  `fmcg-agent-analytics` CLI and the demo walk. Eval gate
  v11 adds zero-tolerance counters for report
  re-performance (tamper included), trend recomputation,
  signal-outcome re-measurement, transmission
  re-measurement and shock-window re-splitting; the
  truth-isolation scan now covers the analytics package
  too.
- **Built and gated in R13:** the console pack (freshness
  windows, queue order, rejection vocabulary, triage acts,
  the gate and pin rules — versioned data), the review
  queue with rejection as a named act inside the approval
  path (a rejected draft can never be approved), the event
  triage queue gating the official view (unverified events
  contribute to drafts, labelled, and zero to official
  forecasts until a named analyst confirms them; retired
  and superseded events leave new runs), the coverage
  pre-flight with run-anyway pinning (gap list verbatim in
  the forecast's content address), the desktop and phone
  consoles with action parity graded byte-for-byte,
  migration 0013, the console API surface, the
  `fmcg-agent-console` CLI and the demo walk. Eval gate
  v12 adds zero-tolerance counters for pre-flight
  re-derivation from the raw record (tamper included),
  queue order and prior-official arithmetic, rejection
  finality, the triage gate in both directions and phone
  action parity; the truth-isolation scan now covers the
  console package too.
- **Built and gated in R14:** the geo pack (band window
  and quantiles, paired-days floor, freshness rule,
  cost-line catalogue, ranking rule, weather-overlay
  rule, schematic geography — versioned data), basis
  readings against the catalogue's reference markets
  with the band re-performed from raw same-date pairs
  (insufficient and unpaired history named, never
  interpolated), desk cost lines as the landed layer's
  only money inputs (catalogue-checked, fold-headed,
  as-of scoped, desk provenance on every entry), landed
  comparisons that name their missing lines instead of
  assuming a rate, market maps whose cells compose
  artefact reads only and render no-data markets as
  named gaps, migration 0014, the geo API surface, the
  `fmcg-agent-geo` CLI and the demo walk. Eval gate v13
  adds zero-tolerance counters for band re-derivation,
  cost-line discipline, landed arithmetic and ranking,
  map-cell composition and the weather/event overlay;
  the truth-isolation scan now covers the geo package
  too.
- **Built and gated in R15:** the desk policy pack
  (exposure threshold and the four approval chains as
  versioned data, genesis v2026.10.1, fail-closed
  loader), pack proposals as insert-only artefacts
  carrying the whole pack and a field-by-field diff
  the verifier re-derives, activation only through a
  completed pack-change chain (a version flipped to
  standing any other way is named), decisions that pin
  their pack and resolved steps at opening (chains read
  off the target's own face — a forecast's graded
  accuracy state, a commitment's exposure against the
  threshold), acts judged in order, in role, never the
  opener, never twice from one folded name, the
  gapless as-of decision log, and comments and
  follow-up tasks pinned to artefacts that exist (a
  task on a superseded scenario flagged on its face),
  migration 0015, the desk API surface, the
  `fmcg-agent-desk` CLI and the demo walk. Scoped
  deliberately: the engine packs stay code-versioned,
  as their artefacts already carry their versions —
  R15 versions the desk's approval limits and chains,
  not the engines. Eval gate v14 adds zero-tolerance
  counters for pack diffs, chain resolution and
  discipline, activation, log folding, annotations and
  the desk verifier; the truth-isolation scan now
  covers the desk package too.
- **Built and gated in R16:** the access pack (the
  trader / desk head / viewer roles and their surfaces
  as versioned data, genesis v2026.10.1, fail-closed
  loader), principal grants as chained insert-only
  acts over a folded name (bootstrap flagged on its
  face, desk-head granters, repeals, catalogue-checked
  scopes), governed reads on the forecast, dashboard
  and export surfaces judged under the standing grant
  and answered existence-hiding (the identical 404 a
  missing artefact gets), access entries struck in
  gapless sequence and the audit log folded from them,
  both layers' verifiers re-deriving chains, granter
  discipline, outcomes and folds; and the master data
  pack with the catalogue restated as a genesis state,
  versions struck whole by named desk-head editors
  with field-by-field diffs, calendar arithmetic
  (pattern minus holidays plus extra operating days),
  and coverage re-derivation that names the changed
  dates per thin-pack window, migration 0016, the
  access and master data API surfaces, the
  `fmcg-agent-access` and `fmcg-agent-masterdata`
  CLIs and the demo walk. Eval gate v15 adds
  zero-tolerance counters for grant discipline, the
  read-judgement walk, the audit fold, master data
  diffs, calendar re-derivation and both verifiers;
  the truth-isolation scan now covers the access and
  masterdata packages too.
- **Built and gated in R17:** the red-team pass — the
  screening pack (five closed categories of
  instruction-shaped text as versioned data, genesis
  v2026.10.1, fail-closed loader) and the folding
  engine shared by the pipeline and the verifier,
  quarantine records content-addressed and insert-only
  (migration 0017), the sentiment pipeline screening
  every item before the model port (a flagged item
  with a standing extraction is a loud conflict, never
  a rewrite), corpus integrity re-performance (count
  and digest against the manifest) inside the
  sentiment verifier, the screening API surfaces and
  the `fmcg-agent-screening` CLI, and the graded
  attack suite: nine injection variants quarantined,
  three reporting-about headlines passed byte-identical,
  the 583-item corpus passed whole, stuffing capped at
  the ladder, the leetspeak limit stated and pinned,
  event/scenario/dashboard text surfaces audited.
  Eval gate v16 adds zero-tolerance counters for
  context leaks, false positives, screening records,
  corpus integrity and the stated bounds; the
  truth-isolation scan now covers the screening
  package too.
- **Built and gated in R18:** the monitoring layer —
  the monitoring pack (closed purposes, the stated
  token estimator, the reference rate card, cadence
  freshness windows; genesis v2026.10.1, fail-closed
  loader), the recording model port striking one run
  record per completed call (hashes and counts, never
  text; cost None for unrated profiles, never zero),
  monitoring boards struck as-of a stated instant with
  cost totals reconciling exactly to the rated records
  folded and per-source freshness verdicts with
  breaches and never-loaded sources named, migration
  0018, the monitoring API surfaces (the app ledgers
  its own calls) and the `fmcg-agent-monitoring` CLI,
  and the graded walks: reconciliation, freshness
  verdicts, as-of discipline, refusal-is-not-freshness,
  and the verifier's tamper probes. Eval gate v17 adds
  zero-tolerance counters for run records, cost
  reconciliation, freshness and boards; the
  truth-isolation scan now covers the monitoring
  package too.
- **Not yet built:** R19 onward on the round map (the
  F20-IA1 + F20-IA2 + F20-DR2 integration and board-pack
  export pass next). The round map runs to R20 and
  continues past it until the production bar is met.
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
  thin/            the thin-data package (truth-isolated, R10):
    pack.py        the thin-data pack: windows, staleness
                   bars, tier bars + caps, band-width rule
    models.py      window coverage / driver state / horizon
                   confidence / assessment artefacts
    engine.py      windows, driver states, tiers — in code
    verify.py      re-performance + tier-claim grading
    service.py     assess / read / verify — one workflow
    cli.py         the fmcg-agent-thin command line
  intake/          the assisted-intake package (truth-isolated, R10):
    models.py      pending entry / check act artefacts
    service.py     enter / confirm / reject — maker–checker
    verify.py      chain re-performance + leakage grading
    cli.py         the fmcg-agent-intake command line
  ingest/          the production data plane (truth-isolated, R11):
    pack.py        the ingest pack: value ranges, quarantine
                   and refusal vocabularies, connector kinds
    models.py      source registration / batch / quarantine /
                   provenance / correction / replay artefacts
    connectors.py  file-drop and API-push delivery parsing
    validate.py    the one validation path, in pure functions
    service.py     register / load / correct / replay — one workflow
    verify.py      batch, correction, provenance, replay
                   re-performance
    cli.py         the fmcg-agent-ingest command line
  analytics/       the forecast-ops analytics package
                   (truth-isolated, R12):
    pack.py        the analytics pack: trend windows +
                   epsilon, outcome rule, minimum class
                   sample, shock-window rule
    models.py      trend / signal outcome / transmission /
                   shock-window rows and the ops report
    engine.py      trends, outcomes, transmission error,
                   shock pools — in code, from artefacts
    verify.py      whole-report re-performance + the
                   honesty invariants, named
    service.py     build / read / verify — one workflow
    cli.py         the fmcg-agent-analytics command line
migrations/        0001-0012 SQL, sqlite + postgres dialects
scripts/           demo.py, local_harness.py, prod_smoke.py
evals/             the eval gate
docs/              architecture.md
```

Apache 2.0. A Trida AI blueprint — patterns are the point; the fictional
buyer's data is ours, generated for this repo.
