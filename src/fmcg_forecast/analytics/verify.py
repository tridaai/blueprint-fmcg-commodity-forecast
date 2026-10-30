"""Re-performance verification for ops reports.

The verifier trusts nothing stored. It recomputes the content
address, resolves the four packs the report names (fail-closed:
a report struck under an unknown pack version cannot be
re-performed and is flagged, never quietly re-read), and then
re-performs the whole report from the store and compares it
field for field. On top of the re-performance it checks the
pack's honesty invariants on their own lines, so a violation is
named for what it is: a pending signal carrying a grade, a
transmission class whose sample naming disagrees with its
counts, or a shock row presenting figures for a pool it names
empty.
"""

from __future__ import annotations

from fmcg_forecast.analytics.engine import compute_report
from fmcg_forecast.analytics.models import OpsReport, report_content_id
from fmcg_forecast.analytics.pack import load_analytics_pack
from fmcg_forecast.backtest.pack import load_accuracy_pack
from fmcg_forecast.events.pack import load_event_pack
from fmcg_forecast.signals.pack import load_signal_pack
from fmcg_forecast.store import Store


def verify_report(store: Store, report: OpsReport) -> list[str]:
    problems: list[str] = []
    if report_content_id(report) != report.report_id:
        problems.append(
            f"content id mismatch: stored {report.report_id}, "
            f"recomputed {report_content_id(report)} — the "
            "artefact was altered after computation"
        )
    try:
        analytics_pack = load_analytics_pack(report.analytics_pack_version)
        accuracy_pack = load_accuracy_pack(report.accuracy_pack_version)
        signal_pack = load_signal_pack(report.signal_pack_version)
        event_pack = load_event_pack(report.event_pack_version)
    except ValueError as exc:
        problems.append(f"unresolvable pack version: {exc}")
        return problems

    # the honesty invariants, named on their own lines
    for row in report.signal_outcomes:
        if row.state == "pending" and (
            row.favourable is not None or row.move is not None
        ):
            problems.append(
                f"pending signal graded: {row.signal_id} "
                f"({row.commodity}/{row.market} as of "
                f"{row.as_of}) carries a move/verdict while "
                "named pending — an unlanded horizon is never "
                "graded"
            )
        if row.state == "graded" and row.favourable is None:
            problems.append(
                f"graded signal without a verdict: {row.signal_id} "
                f"({row.commodity}/{row.market} as of {row.as_of})"
            )
    for row in report.transmission:
        if row.n_measurable == 0:
            expected_state = "no_measurable_events"
        elif row.n_measurable < analytics_pack.min_class_sample:
            expected_state = "small_sample"
        else:
            expected_state = "evidence"
        if row.sample_state != expected_state:
            problems.append(
                f"transmission class {row.event_class}: sample "
                f"state {row.sample_state} disagrees with its "
                f"counts ({row.n_measurable} measurable against "
                f"the pack minimum {analytics_pack.min_class_sample}) "
                f"— the naming must read {expected_state}"
            )
        if row.n_measurable != len(row.measurable_event_ids):
            problems.append(
                f"transmission class {row.event_class}: "
                f"n_measurable {row.n_measurable} disagrees with "
                f"its measurable event list "
                f"({len(row.measurable_event_ids)})"
            )
    named = {
        row.event_class
        for row in report.transmission
        if row.sample_state != "evidence"
    }
    if set(report.small_sample_classes) != named:
        problems.append(
            f"small_sample_classes {sorted(report.small_sample_classes)} "
            f"does not collect exactly the classes named on "
            f"their rows: {sorted(named)}"
        )
    for row in report.shock_windows:
        if row.state == "no_shock_window_days" and row.shock_n_days != 0:
            problems.append(
                f"shock row {row.event_id}/{row.market}/"
                f"{row.horizon_days}d names no shock days but "
                f"carries {row.shock_n_days}"
            )
        if row.state == "graded" and row.delta_mape_pp is None:
            problems.append(
                f"shock row {row.event_id}/{row.market}/"
                f"{row.horizon_days}d is graded without a delta"
            )
    for row in report.trends:
        if row.direction == "insufficient_history" and row.delta_mape_pp is not None:
            problems.append(
                f"trend {row.commodity}/{row.market}/"
                f"{row.horizon_days}d is named insufficient but "
                "carries a delta — a trend over too few origins "
                "is named, never asserted"
            )

    try:
        recomputed = compute_report(
            store, analytics_pack, accuracy_pack, signal_pack, event_pack
        )
    except Exception as exc:  # the recompute itself refused
        problems.append(f"re-performance refused: {exc}")
        return problems
    if recomputed.model_dump(
        mode="json", exclude={"report_id"}
    ) != report.model_dump(mode="json", exclude={"report_id"}):
        problems.append(
            "re-performance mismatch: the stored report does "
            "not equal a fresh computation from the store's "
            "artefacts of record, field for field"
        )
    return problems
