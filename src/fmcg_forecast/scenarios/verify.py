"""Re-performance verification for scenario artefacts.

The verifier trusts nothing stored: it recomputes the content
addresses, re-verifies the base and fork forecasts with the
forecast verifier, recomputes the diff from the two artefacts
and checks its paise-exact identity, re-performs every recorded
shift from the store and the pack, and re-derives every
scenario event's path from the event pack's rule — comparing it
against the path the fork's events line records. A tampered
lever, shift, event window or fork line fails here even if the
artefact still parses.
"""

from __future__ import annotations

import math
from datetime import timedelta

from fmcg_forecast.events.models import event_content_id
from fmcg_forecast.events.pack import EventPack
from fmcg_forecast.events.paths import build_event_path
from fmcg_forecast.forecast.models import FORECAST_DAYS
from fmcg_forecast.forecast.verify import verify_forecast
from fmcg_forecast.scenarios.diff import compute_diff
from fmcg_forecast.scenarios.models import (
    ScenarioRequest,
    ScenarioRun,
    request_content_id,
    scenario_content_id,
)
from fmcg_forecast.scenarios.pack import ScenarioPack
from fmcg_forecast.scenarios.shifts import ShiftError, compute_shift

_TOL = 1e-9


def _close(a: float, b: float, tol: float = _TOL) -> bool:
    return abs(a - b) <= tol


def verify_scenario(
    store,
    run: ScenarioRun,
    request: ScenarioRequest,
    base,
    pack: ScenarioPack,
    event_pack: EventPack,
) -> list[str]:
    """Return the list of problems with a stored scenario run."""
    problems: list[str] = []

    if request_content_id(request) != request.request_id:
        problems.append(
            f"request {request.request_id}: content id mismatch — "
            "the parse was altered after the fact"
        )
    if run.request_id != request.request_id:
        problems.append(
            f"run pins request {run.request_id}, verified against "
            f"{request.request_id}"
        )
    if scenario_content_id(run) != run.scenario_id:
        problems.append(
            f"scenario {run.scenario_id}: content id mismatch — "
            "the run was altered after the fact"
        )
    if run.base_forecast_id != base.forecast_id:
        problems.append(
            f"run pins base {run.base_forecast_id}, verified "
            f"against {base.forecast_id}"
        )
    if run.fork.forecast_id != run.fork_forecast_id:
        problems.append("the run's fork id disagrees with its fork artefact")
    if (run.commodity, run.market, run.as_of) != (
        base.commodity,
        base.market,
        base.as_of,
    ):
        problems.append("the run's series or as_of disagrees with its base")

    problems.extend(
        f"base forecast: {p}" for p in verify_forecast(base)
    )
    problems.extend(f"fork forecast: {p}" for p in verify_forecast(run.fork))

    # The diff identity, recomputed from the two artefacts.
    _, diff_problems = compute_diff(run.scenario_id, base, run.fork)
    problems.extend(diff_problems)

    # Shifts re-performed from the store and the pack.
    levers_by_name = {lever.lever: lever for lever in request.levers}
    recorded = {shift.lever: shift for shift in run.shifts}
    numeric = [
        lever
        for lever in request.levers
        if lever.lever
        in (
            "arrivals_shift_pct",
            "stock_cover_days",
            "trade_flow_shift_pct",
            "weather_deviation",
            "sentiment_override",
        )
    ]
    for lever in numeric:
        shift = recorded.get(lever.lever)
        if shift is None:
            problems.append(f"lever {lever.lever} has no recorded shift")
            continue
        try:
            expected = compute_shift(
                store, run.commodity, run.market, run.as_of, lever, pack
            )
        except ShiftError as exc:
            problems.append(f"lever {lever.lever}: shift does not re-perform: {exc}")
            continue
        if shift.driver != expected.driver or shift.mode != expected.mode:
            problems.append(
                f"lever {lever.lever}: recorded shift moves "
                f"{shift.driver} ({shift.mode}), re-performance "
                f"gives {expected.driver} ({expected.mode})"
            )
        elif not _close(shift.value, expected.value, 1e-9):
            problems.append(
                f"lever {lever.lever}: recorded shift value "
                f"{shift.value} != re-performed {expected.value}"
            )
        # The fork's line states the application on its face.
        line = next(
            (l for l in run.fork.lines if l.driver == shift.driver), None
        )
        marker = (
            line.input_summary.get("scenario_shift") if line is not None else None
        )
        if marker is None:
            problems.append(
                f"the fork's {shift.driver} line carries no "
                "scenario_shift marker — the application is not "
                "stated on the artefact"
            )
        elif not _close(float(marker.get("value")), shift.value, 1e-4):
            problems.append(
                f"the fork's {shift.driver} line marker states "
                f"{marker.get('value')}, the run records {shift.value}"
            )
    for name in recorded:
        if name not in levers_by_name:
            problems.append(f"a shift is recorded for unparsed lever {name}")

    # Scenario events: shape, provenance, and the paths the fork
    # actually consumed (recorded per-event on the fork's events
    # line).
    events_line = next(
        (l for l in run.fork.lines if l.driver == "events"), None
    )
    per_event = (
        events_line.input_summary.get("per_event") if events_line else None
    ) or {}
    first_day = run.as_of + timedelta(days=1)
    for event in run.scenario_events:
        if event_content_id(event) != event.event_id:
            problems.append(
                f"scenario event {event.event_id}: content id mismatch"
            )
        if event.origin != "scenario":
            problems.append(
                f"scenario event {event.event_id}: origin is "
                f"{event.origin!r}, not 'scenario'"
            )
        entry = per_event.get(event.event_id)
        if entry is None:
            problems.append(
                f"scenario event {event.event_id} is not on the "
                "fork's events line — created but never applied"
            )
            continue
        expected_path = build_event_path(event, first_day, FORECAST_DAYS, event_pack)
        recorded_path = entry.get("input_path", [])
        if len(recorded_path) != FORECAST_DAYS or any(
            not _close(float(a), float(b), 1.1e-4)
            for a, b in zip(recorded_path, expected_path)
        ):
            problems.append(
                f"scenario event {event.event_id}: the fork's "
                "recorded path does not re-perform from the "
                "event pack's path rule"
            )
    extension_levers = {
        lever.event_id: lever
        for lever in request.levers
        if lever.lever == "event_extension"
    }
    hypothetical_levers = [
        lever for lever in request.levers if lever.lever == "hypothetical_event"
    ]
    for event in run.scenario_events:
        if event.source_record_id in extension_levers:
            lever = extension_levers[event.source_record_id]
            source = store.get_market_event(event.source_record_id)
            if source is None:
                problems.append(
                    f"extension event {event.event_id}: its source "
                    f"{event.source_record_id} is not in the registry"
                )
                continue
            if event.window_start != source.window_start:
                problems.append(
                    f"extension event {event.event_id}: window "
                    "start moved — an extension prolongs, never reschedules"
                )
            expected_end = (
                source.window_end + timedelta(days=lever.extra_days)
                if source.window_end is not None
                else None
            )
            if event.window_end != expected_end:
                problems.append(
                    f"extension event {event.event_id}: window end "
                    f"{event.window_end} != the source's "
                    f"{source.window_end} + {lever.extra_days} days"
                )
            if event.transmission != source.transmission:
                problems.append(
                    f"extension event {event.event_id}: the "
                    "transmission differs from its source event's"
                )
    if hypothetical_levers:
        hypotheticals = [
            e for e in run.scenario_events if e.source_record_id is None
        ]
        if len(hypotheticals) != len(hypothetical_levers):
            problems.append(
                f"{len(hypothetical_levers)} hypothetical levers "
                f"but {len(hypotheticals)} hypothetical events on the run"
            )
        for lever in hypothetical_levers:
            expected_peak = round(math.log(1.0 + lever.value / 100.0), 6)
            expected_start = run.as_of + timedelta(
                days=(lever.start_offset_days or 0) + 1
            )
            match = next(
                (
                    e
                    for e in hypotheticals
                    if e.event_class == lever.event_class
                    and e.window_start == expected_start
                    and _close(
                        e.transmission.peak_log_price_effect,
                        expected_peak,
                        1e-6,
                    )
                ),
                None,
            )
            if match is None:
                problems.append(
                    f"hypothetical lever ({lever.event_class}, "
                    f"{lever.value:+g}%) has no matching scenario "
                    "event on the run at the stated peak and window"
                )
    return problems
