# Changelog — Commodity Price Forecasting & Procurement Intelligence Agent

The full release history, one entry per round. Every round was gated
on the same bar: the full test suite with the Postgres parity leg
live, the zero-tolerance eval gate, the demo, the HTTP harness and —
from R11 — the production smoke on a live cluster.

## 1.0.0 — Round 20: release hardening

Version 1.0.0 set in the package metadata, `__version__`, the API's
stated version and the lockfile. A docs sweep corrected the docs to
what actually ships: the stack line no longer claims DuckDB,
pandas or statsmodels (pinned in the manifest, imported nowhere —
the engine's numerics are numpy under the stated in-repo engines),
the layout and architecture component lists now run through R19,
and the migration set is stated as 0001–0019. A migration review
re-performed both dialect sets against the repo's own runner:
identical names, gapless numbering 0001–0019, clean application in
order on fresh databases, idempotent re-run. The release freeze ran
the complete gate set twice on the finished tree with identical
figures. The README's work-in-progress notice stays: hands-on
developer testing and the companion blog post are still outstanding.

## Round 19 — the integration surface (F20-IA1 + F20-IA2 + F20-DR2)

Scoped tokens (secret shown once, stored only as its hash;
out-of-scope 403, unknown or revoked 401; revocation a named act),
signed webhook deliveries whose payloads are the artefact reads
byte for byte with every attempt on record, board-pack exports
folded from artefacts by one builder with a checksum manifest,
export jobs whose completion acts name the synchronous pack, and
five MCP-shaped read tools whose figures carry their artefact ids.
Migration 0019.

## Round 18 — cost, usage & freshness monitoring (F20-AM2)

A monitoring pack (closed purposes, a stated token estimator, a
reference rate card, cadence freshness windows) and a recording
model port striking one run record per completed call — hashes and
counts, never text; unrated profiles carry cost None, never zero.
Monitoring boards fold the ledger as-of a stated instant, with
breaches and never-loaded sources named on the board's face.
Migration 0018.

## Round 17 — injection quarantine (F20-AS2)

The red-team round. A screening pack states five closed categories
of instruction-shaped text and the folding discipline they are
judged under; the sentiment pipeline screens every item before the
model port, and a flagged item becomes a content-addressed
quarantine record and stops there. Corpus integrity (count and
digest against the manifest) is re-performed inside the sentiment
verifier. Obfuscation past the stated normalisation is a stated
limit. Migration 0017.

## Round 16 — identity, scopes, access audit; master data (F20-AS1 + F20-AD1)

An access pack states the trader / desk head / viewer roles and
their surfaces; principal grants are chained insert-only acts,
governed reads are judged under the standing grant and answered
existence-hiding (the identical 404 a missing artefact gets), and
every judged read strikes a gapless access entry the audit log
folds. Master data restates the catalogue as a genesis state;
versions are struck whole by named desk-head editors with
field-by-field diffs, and calendar edits re-derive coverage,
naming every changed date per window. Migration 0016.

## Round 15 — desk policy, approvals, annotations (F20-AD2 + F20-CA2 + F20-CA1)

A desk policy pack states the coverage exposure threshold and one
approval chain per decision kind as versioned data. A proposal
carries the whole pack plus a re-derived field-by-field diff and
becomes standing only through its own pack-change chain — there is
no other activation path. Decisions pin their pack version and
resolved steps at opening; acts are judged in order, in role,
never the opener, never twice from one folded name. Comments and
follow-up tasks pin to artefacts that exist. Migration 0015.

## Round 14 — geospatial basis & netting (F20-PO4 + F20-GS1 + F20-GS2)

Basis readings pair same-date modal prices against the catalogue's
reference market, paise-exact, naming insufficient or absent
pairing instead of interpolating. Desk-entered cost lines are the
landed layer's only money inputs — a comparison missing a line
reads not computable, never an assumed rate. The market map is a
stated schematic grid whose stored page re-renders byte-for-byte.
Migration 0014.

## Round 13 — operator console (F20-OW2 + F20-OW3 + F20-OW4 + F20-MF2)

The desk day as governed acts: a review queue where rejection is
an act inside the approval path itself, an event triage queue
gating the official view (an event is officially clear only when
measured-verified or confirmed by a named analyst), a coverage
pre-flight whose gap list a run can pin into its own content
address, and desktop and phone consoles whose action parity is
graded byte-for-byte. Migration 0013.

## Round 12 — forecast-ops analytics (F20-AM1)

The desk's track record as one re-performable artefact: accuracy
trends pooled by the ledger's own rule, signal outcomes struck at
grid origins with as-of accuracy attachments and measured against
realised prices (pending signals named, never graded),
transmission error per event class with small samples named
anecdote, and shock-window grades split at the planted windows.
Migration 0012.

## Round 11 — production data plane (F20-DI1 + F20-DI2 + F20-DI4)

A source registry under a versioned ingest pack; file drops and
API pushes judged by one validation path; bad rows quarantined
with exact named reasons and whole-batch refusals stored as
artefacts; provenance rows for every landed fact; corrections as
insert-only overlays with the effective fact a fold; backfill
replay earning a series its accuracy ledger through the harness's
own seams. The Postgres production smoke joins the gate set.
Migration 0011.

## Round 10 — thin-data depth & assisted intake (F20-DI3)

A thin-data pack judges each forecast's own series: operating-day
coverage with every missing date named, per-driver states with
last-observed dates, per-horizon confidence tiers computed in code
— caps only ever lower a tier, and an unearned tier stated
anywhere is a graded contradiction. Assisted intake keeps
desk-entered figures in pending tables no engine can see until a
named checker who is not the enterer confirms. Migration 0010.

## Round 9 — alerting, subscriptions & escalation (F20-AL1 + F20-AL2 + F20-AL3)

Desk-entered subscriptions, superseded by link; a sweep derives
alerts from artefacts of record — struck signals, declared event
windows, computed price crossings, accuracy episodes — each
content-addressed by (subscription, kind, trigger) so a crossing
fires exactly once. Acknowledgement and closure are attributed
acts; escalation state is a fold of the acts plus the pack's
windows. Daily digests carry exactly a subscriber's alerts.
Migration 0009.

## Round 8 — buy-window signals & coverage planning (F20-PO2 + F20-PO3)

Each series' head forecast becomes one computed buy-window call
under the signal pack — reasoning on the artefact's face, degraded
and unmeasured series capped by hard rule, overlapping shocks
named. Desk-entered requirement plans carry their own lineage
terminal class (never market provenance); assessments price them
against the official forecast or an adopted scenario's fork with
paise-exact exposure and options ranked only by the pack's
criteria. No trade is ever placed. Migration 0008.

## Round 7 — prompt-to-dashboard (F20-OW1 + F20-DR3)

A plain-language prompt compiles through the model port to a
stated spec — catalogue panels or named gap panels, never dropped
clauses. Assemblies re-resolve to current artefact heads and are
verified whole before they are stored: figures re-performed,
every figure's lineage walked to stored facts, the rendered page
byte-exact. Re-runs carry a computed diff, and the morning desk
board ranks the day's exceptions as an artefact. Migration 0007.

## Round 6 — scenario studio

The bounded lever catalogue as a versioned pack; typed what-ifs
parsed through the model port into shown-back requests with
named-clause refusals; pinned forks computed by the engine with
levers applied to driver inputs — the decomposition identity
intact, the base artefact never mutated; the integer-paise diff;
adoption only by a named human act, supersession by link.
Migration 0006.

## Round 5 — declared events & the registry

The event pack (classes, channels, bases, the path rule, the
measurement rule, the widening factor) as versioned data; the
governed registry of content-addressed declarations; historical
seeding from the generator manifest with every planted
transmission verified against seasonally-matched measurement —
forged and wrong-sign claims flagged unverified on the event's
face; per-event forecast lines with interval widening exactly per
pack on shocked days only. Migration 0005.

## Round 4 — sentiment as a scored pack

A 27-phrase lexicon, direction ladder, index formula and
estimation floors as versioned data; a planted 583-item corpus
whose intent lives only in the grading store; extraction through
the model port graded exact against planted intent over the whole
corpus; the weekly index computed in code (absent, never zero);
the forecast sentiment line estimated where the pack's floors are
met and named not-estimable where they are not. Migration 0004.

## Round 3 — backtests & the accuracy ledger

Rolling-origin backtests over the 2025 grid under a versioned
accuracy pack; the pooled ledger (most recent six origins,
degraded bar at pooled MAPE > 5.0%); every forecast pins the
ledger's current records as a self-contained snapshot whose state
— measured, degraded, unmeasured — no read path can suppress.
Coffee's unstatable origins are recorded as named skips.
Migration 0003.

## Round 2 — the forecast engine

Trend + day-of-year-seasonality baseline (OLS on log price) plus
per-driver contributions — arrivals, stock, trade, weather — each
estimated by a stated regression and attributed sequentially, so
baseline + contributions + events equals the forecast total
exactly, to the paisa. Honest P10/P90 intervals widened by a
measured sparsity multiplier. A forecast is born a draft; the
official view takes a named human approval. Commentary figures
must resolve to the artefact or the draft is refused wholesale.
Migration 0002.

## Round 1 — the spine

A gold-by-construction dataset generator: three years of daily
series for seven commodities across 14 market series with planted
seasonality, trend breaks, a tariff shock, an export ban and a
drought, all restated in a generator manifest; the next 90 days
sealed behind a truth store the forecast package is structurally
forbidden from reading. The insert-only store port (SQLite and
Postgres dialects, numbered migrations), the model port with an
offline deterministic default and fail-closed hosted profiles, the
LangGraph ingest workflow, and the operations API. Migration 0001.
