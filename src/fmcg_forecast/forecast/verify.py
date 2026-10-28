"""Re-performance verification for forecast artefacts.

The verifier trusts nothing stored: it re-adds every day's
decomposition, re-checks every line against the days it claims to
summarise, re-checks the horizon summaries against the day rows, and
recomputes the content address. A tampered line, total, coefficient
or path makes the artefact fail here even if it still parses.
"""

from __future__ import annotations

from datetime import timedelta

from fmcg_forecast.forecast.engine import forecast_content_id
from fmcg_forecast.forecast.models import (
    ATTRIBUTION_ORDER,
    FORECAST_DAYS,
    HORIZONS,
    Forecast,
)

# INR figures are stored rounded to 2dp; the decomposition is exact
# by construction, so anything beyond a paisa of float noise is a
# discrepancy, not rounding.
ROUNDING_TOLERANCE = 0.011


def verify_forecast(forecast: Forecast) -> list[str]:
    """Return the list of problems with a stored forecast artefact."""
    problems: list[str] = []

    if forecast_content_id(forecast) != forecast.forecast_id:
        problems.append(
            f"content id mismatch: stored {forecast.forecast_id}, recomputed "
            f"{forecast_content_id(forecast)} — the artefact was altered after the run"
        )
    if forecast.method.attribution_order != list(ATTRIBUTION_ORDER):
        problems.append("attribution order differs from the stated method")
    if len(forecast.days) != FORECAST_DAYS:
        problems.append(f"forecast carries {len(forecast.days)} days, expected {FORECAST_DAYS}")
        return problems

    expected_dates = [
        forecast.as_of + timedelta(days=h) for h in range(1, FORECAST_DAYS + 1)
    ]
    if [d.forecast_date for d in forecast.days] != expected_dates:
        problems.append("forecast dates are not the 90 calendar days after as_of")

    lines_by_driver = {line.driver: line for line in forecast.lines}
    for i, day in enumerate(forecast.days):
        parts = day.baseline + sum(day.contributions.values()) + day.events_adjustment
        if abs(parts - day.p50) > ROUNDING_TOLERANCE:
            problems.append(
                f"{day.forecast_date}: decomposition does not sum — baseline "
                f"{day.baseline} + contributions {sum(day.contributions.values())} "
                f"+ events {day.events_adjustment} != p50 {day.p50}"
            )
        if not (day.p10 <= day.p50 <= day.p90):
            problems.append(
                f"{day.forecast_date}: interval ordering broken "
                f"(p10 {day.p10}, p50 {day.p50}, p90 {day.p90})"
            )
        for driver, value in day.contributions.items():
            line = lines_by_driver.get(driver)
            if line is None:
                problems.append(f"{day.forecast_date}: contribution from {driver} has no line")
            elif abs(line.contribution_path_inr[i] - value) > ROUNDING_TOLERANCE:
                problems.append(
                    f"{day.forecast_date}: {driver} day value {value} != line path "
                    f"{line.contribution_path_inr[i]}"
                )
        events_line = lines_by_driver.get("events")
        if events_line is not None and abs(
            events_line.contribution_path_inr[i] - day.events_adjustment
        ) > ROUNDING_TOLERANCE:
            problems.append(
                f"{day.forecast_date}: events adjustment {day.events_adjustment} != "
                f"events line path {events_line.contribution_path_inr[i]}"
            )

    for line in forecast.lines:
        if len(line.input_path) != FORECAST_DAYS or len(line.contribution_path_inr) != FORECAST_DAYS:
            problems.append(f"line {line.driver}: paths are not {FORECAST_DAYS} days")
            continue
        for h in HORIZONS:
            if abs(line.at_horizon[str(h)] - line.contribution_path_inr[h - 1]) > ROUNDING_TOLERANCE:
                problems.append(
                    f"line {line.driver}: at_horizon[{h}] {line.at_horizon[str(h)]} != "
                    f"path value {line.contribution_path_inr[h - 1]}"
                )

    # Per-event lines (R5): each declared event's own INR path is
    # recorded on the events line; the paths must sum to the day
    # adjustments they compose, and each at_horizon must match its
    # path. Absent on unshocked forecasts — nothing to check there.
    events_line = lines_by_driver.get("events")
    per_event = (
        events_line.input_summary.get("per_event") if events_line is not None else None
    ) or {}
    for event_id, entry in per_event.items():
        path = entry.get("contribution_path_inr", [])
        if len(path) != FORECAST_DAYS:
            problems.append(
                f"event {event_id}: contribution path is not {FORECAST_DAYS} days"
            )
            continue
        for h in HORIZONS:
            if abs(entry["at_horizon"][str(h)] - path[h - 1]) > ROUNDING_TOLERANCE:
                problems.append(
                    f"event {event_id}: at_horizon[{h}] {entry['at_horizon'][str(h)]} "
                    f"!= path value {path[h - 1]}"
                )
    if per_event:
        for i, day in enumerate(forecast.days):
            total = sum(
                entry["contribution_path_inr"][i] for entry in per_event.values()
            )
            if abs(total - day.events_adjustment) > ROUNDING_TOLERANCE * len(per_event):
                problems.append(
                    f"{day.forecast_date}: per-event contributions sum to "
                    f"{total}, != events adjustment {day.events_adjustment}"
                )

    for summary in forecast.horizons_summary:
        day = forecast.days[summary.horizon_days - 1]
        if (
            summary.forecast_date != day.forecast_date
            or abs(summary.baseline - day.baseline) > ROUNDING_TOLERANCE
            or abs(summary.p50 - day.p50) > ROUNDING_TOLERANCE
            or abs(summary.p10 - day.p10) > ROUNDING_TOLERANCE
            or abs(summary.p90 - day.p90) > ROUNDING_TOLERANCE
            or summary.contributions != day.contributions
            or abs(summary.events_adjustment - day.events_adjustment) > ROUNDING_TOLERANCE
        ):
            problems.append(
                f"horizon summary {summary.horizon_days}d does not match its day row"
            )

    return problems
