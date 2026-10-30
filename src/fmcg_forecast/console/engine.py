"""The console engine — checklists, folds and queues, in code.

Everything here is computed from the store and the console
pack, and nothing is authored:

- the *pre-flight* reads the series' own observations, the
  sentiment indices and the accuracy ledger, and names every
  failed check as a gap in the pack's stated order;
- the *triage fold* reduces an event's acts to its state —
  the latest act by (acted_on, act_id) decides;
- *officially clear* is the gate the approval path enforces:
  an event is clear when its transmission verdict is verified
  or a confirm act stands; retired and superseded events are
  never clear;
- the *review queue* derives its rows from the draft
  forecasts of record, ordered by the pack's rule.
"""

from __future__ import annotations

from datetime import date

from fmcg_forecast.catalogue import ALL_DRIVERS, BY_NAME
from fmcg_forecast.console.models import (
    AppliedEventFlag,
    DriverCheck,
    EventTriageAct,
    HorizonCoverage,
    PreflightReport,
    ReviewQueueRow,
    SentimentCheck,
    TriageQueueRow,
    preflight_content_id,
)
from fmcg_forecast.console.pack import ConsolePack
from fmcg_forecast.events.models import MarketEvent
from fmcg_forecast.forecast.models import HORIZONS, Forecast


class ConsoleError(RuntimeError):
    """Base for console refusals."""


class ConsoleValidationError(ConsoleError):
    """The request itself is malformed."""


class ConsoleNotFoundError(ConsoleError):
    """No artefact with that id."""


class ConsoleStateError(ConsoleError):
    """The artefact is not in a state that admits the act."""


# ---------------------------------------------------------------------------
# The pre-flight (F20-OW4)
# ---------------------------------------------------------------------------


def compute_preflight(
    store, commodity: str, market: str, as_of: date, pack: ConsolePack
) -> PreflightReport:
    """The checklist for one series at one as-of, from the store."""
    spec = BY_NAME.get(commodity)
    if spec is None or market not in {m.market for m in spec.markets}:
        raise ConsoleValidationError(
            f"no catalogue series {commodity}/{market} to pre-flight — "
            "the console pack judges catalogue series"
        )
    gaps: list[str] = []
    drivers: list[DriverCheck] = []
    last_price_date: date | None = None
    for driver in ALL_DRIVERS:
        if driver not in spec.drivers:
            drivers.append(
                DriverCheck(
                    driver=driver,
                    state="missing",
                    last_observed_date=None,
                    age_days=None,
                )
            )
            gaps.append(
                f"driver {driver} is missing — {spec.display} does not "
                "report it"
            )
            continue
        rows = store.series(commodity, market, driver, None, as_of)
        if not rows:
            drivers.append(
                DriverCheck(
                    driver=driver,
                    state="missing",
                    last_observed_date=None,
                    age_days=None,
                )
            )
            gaps.append(
                f"driver {driver} is missing — never reported for "
                f"{commodity}/{market}"
            )
            continue
        last = max(r.obs_date for r in rows)
        age = (as_of - last).days
        if driver == "modal_price":
            last_price_date = last
        if age <= pack.obs_fresh_days:
            state = "present"
        else:
            state = "stale"
            gaps.append(
                f"driver {driver} is stale — last observed "
                f"{last.isoformat()}, {age} days before the as-of"
            )
        drivers.append(
            DriverCheck(
                driver=driver,
                state=state,  # type: ignore[arg-type]
                last_observed_date=last,
                age_days=age,
            )
        )

    indices = store.list_indices(commodity)
    if not indices:
        sentiment = SentimentCheck(
            state="absent",
            last_index_week_end=None,
            age_days=None,
            n_index_weeks=0,
        )
        gaps.append(
            f"sentiment is absent — no index week stands for {commodity}"
        )
    else:
        last_end = max(i.week_end for i in indices)
        age = (as_of - last_end).days
        state = "current" if age <= pack.sentiment_fresh_days else "stale"
        if state == "stale":
            gaps.append(
                f"sentiment is stale — last index week ended "
                f"{last_end.isoformat()}, {age} days before the as-of"
            )
        sentiment = SentimentCheck(
            state=state,  # type: ignore[arg-type]
            last_index_week_end=last_end,
            age_days=age,
            n_index_weeks=len(indices),
        )

    coverage: list[HorizonCoverage] = []
    for horizon in HORIZONS:
        record = store.get_accuracy_record(commodity, market, horizon)
        if record is None:
            coverage.append(
                HorizonCoverage(
                    horizon_days=horizon,
                    state="unmeasured",
                    record_id=None,
                    n_origins=0,
                    mape=None,
                )
            )
            gaps.append(
                f"no backtest coverage at the {horizon}-day horizon — "
                "accuracy unmeasured"
            )
            continue
        coverage.append(
            HorizonCoverage(
                horizon_days=horizon,
                state="degraded" if record.degraded else "measured",
                record_id=record.record_id,
                n_origins=record.n_results,
                mape=record.mape,
            )
        )

    report = PreflightReport(
        report_id="PRE-pending",
        pack_version=pack.version,
        commodity=commodity,
        market=market,
        as_of=as_of,
        last_observation_date=last_price_date,
        drivers=drivers,
        sentiment=sentiment,
        coverage=coverage,
        gaps=gaps,
        state="gapped" if gaps else "clear",
    )
    report.report_id = preflight_content_id(report)
    return report


# ---------------------------------------------------------------------------
# Triage folds and the official-view gate (F20-OW3)
# ---------------------------------------------------------------------------


def fold_triage_state(acts: list[EventTriageAct]) -> str:
    """An event's triage state: the fold of its acts.

    No acts reads ``declared``; otherwise the latest act by
    (acted_on, act_id) decides — confirm leaves the event
    confirmed, retire leaves it retired, amend leaves it
    superseded by the replacement the act records.
    """
    if not acts:
        return "declared"
    latest = sorted(acts, key=lambda a: (a.acted_on, a.act_id))[-1]
    return {"confirm": "confirmed", "retire": "retired", "amend": "superseded"}[
        latest.act
    ]


def triage_states(store) -> dict[str, str]:
    """Every triaged event's state, folded from the act record."""
    by_event: dict[str, list[EventTriageAct]] = {}
    for act in store.list_event_triage_acts():
        by_event.setdefault(act.event_id, []).append(act)
    return {event_id: fold_triage_state(acts) for event_id, acts in by_event.items()}


def excluded_event_ids(store) -> set[str]:
    """Events new runs must not apply: retired or superseded."""
    return {
        event_id
        for event_id, state in triage_states(store).items()
        if state in ("retired", "superseded")
    }


def approval_blockers(store, events, forecast: Forecast) -> list[str]:
    """Why this forecast cannot become the official view today.

    One named blocker per applied event that is not officially
    clear. An adjustment no registry declaration stands behind
    (a hand-fed engine fixture) is not the registry's to gate.
    """
    states = triage_states(store)
    blockers: list[str] = []
    for event_id in forecast.method.events_applied:
        event = store.get_market_event(event_id)
        if event is None:
            continue
        state = states.get(event_id, "declared")
        if state == "retired":
            blockers.append(
                f"event {event_id} was retired in triage — a retired "
                "event cannot enter the official view"
            )
            continue
        if state == "superseded":
            acts = sorted(
                store.list_event_triage_acts(event_id),
                key=lambda a: (a.acted_on, a.act_id),
            )
            replacement = next(
                (a.replacement_event_id for a in reversed(acts) if a.act == "amend"),
                None,
            )
            blockers.append(
                f"event {event_id} was superseded in triage by "
                f"{replacement} — the draft carries the replaced "
                "declaration"
            )
            continue
        if state == "confirmed":
            continue
        verdict = events.verify_event(event_id)
        if verdict.status != "verified":
            blockers.append(
                f"event {event_id} is {verdict.status} and not "
                "confirmed in triage — an unconfirmed event "
                "contributes to drafts only, never to the official "
                "view"
            )
    return blockers


def applied_event_flags(store, events, forecast: Forecast) -> list[AppliedEventFlag]:
    """The label every draft read carries for its applied events."""
    states = triage_states(store)
    flags: list[AppliedEventFlag] = []
    for event_id in forecast.method.events_applied:
        event = store.get_market_event(event_id)
        if event is None:
            flags.append(
                AppliedEventFlag(
                    event_id=event_id,
                    verification_status="not_in_registry",
                    triage_state="not_in_registry",
                )
            )
            continue
        flags.append(
            AppliedEventFlag(
                event_id=event_id,
                verification_status=events.verify_event(event_id).status,
                triage_state=states.get(event_id, "declared"),
            )
        )
    return flags


# ---------------------------------------------------------------------------
# The queues (F20-OW2, F20-OW3)
# ---------------------------------------------------------------------------


def review_queue(store, events, pack: ConsolePack) -> list[ReviewQueueRow]:
    """Drafts awaiting review, in the pack's stated order."""
    rank = {state: i for i, state in enumerate(pack.queue_state_order)}
    officials: dict[tuple[str, str], Forecast] = {}
    for forecast in store.list_forecasts():
        if forecast.status != "official":
            continue
        key = (forecast.commodity, forecast.market)
        current = officials.get(key)
        if current is None or (forecast.as_of, forecast.forecast_id) > (
            current.as_of,
            current.forecast_id,
        ):
            officials[key] = forecast

    rows: list[ReviewQueueRow] = []
    for forecast in store.list_forecasts():
        if forecast.status != "draft":
            continue
        if store.get_forecast_rejection(forecast.forecast_id) is not None:
            continue
        accuracy_state = (
            forecast.accuracy.state if forecast.accuracy else "unmeasured"
        )
        p50 = {
            str(s.horizon_days): s.p50 for s in forecast.horizons_summary
        }
        summary_30 = next(
            s for s in forecast.horizons_summary if s.horizon_days == 30
        )
        prior = officials.get((forecast.commodity, forecast.market))
        prior_30 = None
        if prior is not None:
            prior_30 = next(
                s for s in prior.horizons_summary if s.horizon_days == 30
            ).p50
        rows.append(
            ReviewQueueRow(
                forecast_id=forecast.forecast_id,
                commodity=forecast.commodity,
                market=forecast.market,
                as_of=forecast.as_of,
                accuracy_state=accuracy_state,
                degraded_horizons=[
                    s.horizon_days
                    for s in (forecast.accuracy.per_horizon if forecast.accuracy else [])
                    if s.state == "degraded"
                ],
                p50_by_horizon=p50,
                contributions_30d=dict(summary_30.contributions),
                prior_official_id=prior.forecast_id if prior else None,
                prior_official_as_of=prior.as_of if prior else None,
                prior_p50_30=prior_30,
                delta_p50_30=(
                    round(summary_30.p50 - prior_30, 2)
                    if prior_30 is not None
                    else None
                ),
                events=applied_event_flags(store, events, forecast),
                blockers=approval_blockers(store, events, forecast),
                preflight_id=(
                    forecast.preflight.preflight_id if forecast.preflight else None
                ),
            )
        )
    rows.sort(
        key=lambda r: (
            rank.get(r.accuracy_state, len(rank)),
            r.as_of,
            r.forecast_id,
        )
    )
    return rows


def triage_queue(store, events) -> list[TriageQueueRow]:
    """Events awaiting triage, in their verdicts' lanes.

    The lane order is the pack's discipline made visible:
    unverified first (the ones that must not slip into the
    official view unexamined), then not_measurable, then
    verified — each lane by window start, then event id.
    """
    states = triage_states(store)
    lane_rank = {"unverified": 0, "not_measurable": 1, "verified": 2}
    rows: list[TriageQueueRow] = []
    for event in store.list_market_events():
        if states.get(event.event_id, "declared") != "declared":
            continue
        verdict = events.verify_event(event.event_id)
        rows.append(
            TriageQueueRow(
                event_id=event.event_id,
                event_class=event.event_class,
                commodity=event.commodity,
                window_start=event.window_start,
                window_end=event.window_end,
                claimed_peak_log=event.transmission.peak_log_price_effect,
                basis=event.transmission.basis,
                declared_by=event.declared_by,
                declared_on=event.declared_on,
                verification_status=verdict.status,
                measured_ratio=verdict.measured_ratio,
                triage_state="declared",
                lane=verdict.status,  # type: ignore[arg-type]
            )
        )
    rows.sort(
        key=lambda r: (lane_rank[r.lane], r.window_start, r.event_id)
    )
    return rows


def event_state_view(store, events, event: MarketEvent) -> dict:
    """One event with its verdict and triage fold on its face."""
    acts = sorted(
        store.list_event_triage_acts(event.event_id),
        key=lambda a: (a.acted_on, a.act_id),
    )
    view = event.model_dump(mode="json")
    view["verification"] = events.verify_event(event.event_id).model_dump(
        mode="json"
    )
    view["triage_state"] = fold_triage_state(acts)
    view["triage_acts"] = [a.model_dump(mode="json") for a in acts]
    return view
